#!/usr/bin/env python3
#
# Copyright (c) 2016-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

import atexit
import errno
import inspect
import logging
import os
import shutil
import tempfile
import time
import typing
import unittest
from hypothesis import settings, HealthCheck
import hypothesis.strategies as st
from hypothesis.internal.detection import is_hypothesis_test
from hypothesis.configuration import (
    set_hypothesis_home_dir,
    hypothesis_home_dir)
from typing import Dict, List, Optional

from . import edenclient
from . import hgrepo
from . import gitrepo


def is_sandcastle():
    return 'SANDCASTLE' in os.environ


default_settings = settings(
    # Turn off the health checks because setUp/tearDown are too slow
    suppress_health_check=[HealthCheck.too_slow],

    # Turn off the example database; we don't have a way to persist this
    # or share this across runs, so we don't derive any benefit from it at
    # this time.
    database=None,
)

# Configure Hypothesis to run faster when iterating locally
settings.register_profile("dev", settings(default_settings,
                                          max_examples=5,
                                          timeout=0))
# ... and use the defaults (which have more combinations) when running
# on CI, which we want to be more deterministic.
settings.register_profile("ci", settings(default_settings,
                                         derandomize=True,
                                         timeout=0))

# Use the dev profile by default, but use the ci profile on sandcastle.
settings.load_profile('ci' if is_sandcastle()
                      else os.getenv('HYPOTHESIS_PROFILE', 'dev'))

# Some helpers for Hypothesis decorators
FILENAME_STRATEGY = st.text(
    st.characters(min_codepoint=1,
                  max_codepoint=1000,
                  blacklist_characters="/:\\",
                  ),
    min_size=1)

# We need to set a global (but non-conflicting) path to store some state
# during hypothesis example runs.  We want to avoid putting this state in
# the repo.
set_hypothesis_home_dir(tempfile.mkdtemp(prefix='eden_hypothesis.'))
atexit.register(shutil.rmtree, hypothesis_home_dir())

if not edenclient.can_run_eden():
    # This is avoiding a reporting noise issue in our CI that files
    # tasks about skipped tests.  Let's just skip defining most of them
    # to avoid the noise if we know that they won't work anyway.
    TestParent = typing.cast(unittest.TestCase, object)
else:
    TestParent = unittest.TestCase


@unittest.skipIf(not edenclient.can_run_eden(), "unable to run edenfs")
class EdenTestCase(TestParent):
    '''
    Base class for eden integration test cases.

    This starts an eden daemon during setUp(), and cleans it up during
    tearDown().
    '''

    def run(self, report=None):
        ''' Some slightly awful magic here to arrange for setUp and
            tearDown to be called at the appropriate times when hypothesis
            is enabled for a test case.
            This can be removed once a future version of hypothesis
            ships with support for this baked in. '''
        if is_hypothesis_test(getattr(self, self._testMethodName)):
            try:
                old_setUp = self.setUp
                old_tearDown = self.tearDown
                self.setUp = lambda: None
                self.tearDown = lambda: None
                self.setup_example = old_setUp
                self.teardown_example = lambda _: old_tearDown()
                return super(EdenTestCase, self).run(report)
            finally:
                self.setUp = old_setUp
                self.tearDown = old_tearDown
                del self.setup_example
                del self.teardown_example
        else:
            return super(EdenTestCase, self).run(report)

    def report_time(self, event):
        '''
        report_time() is a helper function for logging how long different
        parts of the test took.

        Each time it is called it logs a message containing the time since the
        test started and the time since the last time report_time() was called.
        '''
        now = time.time()
        since_last = (now - self.last_event)
        since_start = (now - self.start)
        logging.info('=== %s at %.03fs (+%0.3fs)',
                     event, since_start, since_last)
        self.last_event = now

    def setUp(self):
        self.start = time.time()
        self.last_event = self.start

        self.eden = None
        self.old_home = None

        # Call setup_eden_test() to do most of the setup work, and call
        # tearDown() on any error.  tearDown() won't be called by default if
        # setUp() throws.
        try:
            self.setup_eden_test()
        except Exception as ex:
            self.tearDown()
            raise
        self.report_time('test setup done')

    def setup_eden_test(self):
        self.tmp_dir = tempfile.mkdtemp(prefix='eden_test.')

        # The home directory, to make sure eden looks at this rather than the
        # real home directory of the user running the tests.
        self.home_dir = os.path.join(self.tmp_dir, 'homedir')
        os.mkdir(self.home_dir)
        self.old_home = os.getenv('HOME')
        os.environ['HOME'] = self.home_dir

        # TODO: Make this configurable via ~/.edenrc.
        # The eden config directory.
        self.eden_dir = os.path.join(self.home_dir, 'local/.eden')
        os.makedirs(self.eden_dir)

        self.etc_eden_dir = os.path.join(self.tmp_dir, 'etc-eden')
        os.mkdir(self.etc_eden_dir)
        # The directory holding the system configuration files
        self.system_config_dir = os.path.join(self.etc_eden_dir, 'config.d')
        os.mkdir(self.system_config_dir)
        # Parent directory for any git/hg repositories created during the test
        self.repos_dir = os.path.join(self.tmp_dir, 'repos')
        os.mkdir(self.repos_dir)
        # Parent directory for eden mount points
        self.mounts_dir = os.path.join(self.tmp_dir, 'mounts')
        os.mkdir(self.mounts_dir)
        self.report_time('temporary directory creation done')

        logging_settings = self.edenfs_logging_settings()
        extra_args = self.edenfs_extra_args()
        storage_engine = self.select_storage_engine()
        self.eden = edenclient.EdenFS(self.eden_dir,
                                      etc_eden_dir=self.etc_eden_dir,
                                      home_dir=self.home_dir,
                                      logging_settings=logging_settings,
                                      extra_args=extra_args,
                                      storage_engine=storage_engine)
        self.eden.start()
        self.report_time('eden daemon started')

    def tearDown(self):
        self.report_time('tear down started')
        error = None
        try:
            if self.eden is not None:
                self.eden.cleanup()
        except Exception as ex:
            error = ex

        if self.old_home is not None:
            os.environ['HOME'] = self.old_home
            self.old_home = None

        if self.tmp_dir is not None:
            if os.environ.get('EDEN_TEST_NO_CLEANUP'):
                print('Leaving behind eden test directory %r' % self.tmp_dir)
            else:
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
            self.tmp_dir = None

        self.report_time('tear down done')

        # Re-raise any error that occurred, after we finish
        # trying to clean up our directories.
        if error is not None:
            raise error

    def get_thrift_client(self):
        '''
        Get a thrift client to the edenfs daemon.
        '''
        return self.eden.get_thrift_client()

    def edenfs_logging_settings(self) -> Optional[Dict[str, str]]:
        '''
        Get the log settings to pass to edenfs via the --logging argument.

        This should return a dictionary of {category_name: level}
        - module_name is the C++ log category name.  e.g., "eden.fs.store"
          or "eden.fs.inodes.TreeInode"
        - level is the integer vlog level to use for that module.

        You can return None if you do not want any extra verbose logging
        enabled.
        '''
        return None

    def edenfs_extra_args(self) -> Optional[List[str]]:
        '''
        Get additional arguments to pass to edenfs
        '''
        return None

    def create_repo(self, name, repo_class, **kwargs):
        '''
        Create a new repository.

        Arguments:
        - name
          The repository name.  This determines the repository location inside
          the self.repos_dir directory.  The full repository path can be
          accessed as repo.path on the returned repo object.
        - repo_class
          The repository class object, such as hgrepo.HgRepository or
          gitrepo.GitRepository.
        '''
        repo_path = os.path.join(self.repos_dir, name)
        os.mkdir(repo_path)
        repo = repo_class(repo_path)
        repo.init(**kwargs)

        return repo

    def get_path(self, path: str) -> str:
        '''Resolves the path against self.mount.'''
        return os.path.join(self.mount, path)

    def touch(self, path: str) -> None:
        '''Touch the file at the specified path relative to the clone.'''
        fullpath = self.get_path(path)
        with open(fullpath, 'a'):
            os.utime(fullpath)

    def write_file(self, path: str, contents: str, mode: int = 0o644) -> None:
        '''Create or overwrite a file with the given contents.'''
        fullpath = self.get_path(path)
        self.make_parent_dir(fullpath)
        with open(fullpath, 'w') as f:
            f.write(contents)
        os.chmod(fullpath, mode)

    def read_file(self, path: str) -> str:
        '''Read the file with the specified path inside the eden repository,
        and return its contents.
        '''
        fullpath = self.get_path(path)
        with open(fullpath, 'r') as f:
            return f.read()

    def mkdir(self, path: str) -> None:
        '''Call mkdir for the specified path relative to the clone.'''
        full_path = self.get_path(path)
        try:
            os.makedirs(full_path)
        except OSError as ex:
            if ex.errno != errno.EEXIST:
                raise

    def make_parent_dir(self, path: str) -> None:
        dirname = os.path.dirname(path)
        if dirname:
            self.mkdir(dirname)

    def rm(self, path: str) -> None:
        '''Unlink the file at the specified path relative to the clone.'''
        os.unlink(self.get_path(path))

    def select_storage_engine(self):
        '''
        Prefer to use memory in the integration tests, but allow
        the tests that restart to override this and pick something else.
        '''
        return 'memory'


class EdenRepoTestBase(EdenTestCase):
    '''
    Base class for EdenHgTest and EdenGitTest.

    This sets up a repository and mounts it before starting each test function.
    '''
    def setup_eden_test(self):
        super().setup_eden_test()

        self.repo_name = 'main'
        self.mount = os.path.join(self.mounts_dir, self.repo_name)

        self.repo = self.create_repo(self.repo_name, self.get_repo_class())
        self.populate_repo()
        self.report_time('repository setup done')

        self.eden.add_repository(self.repo_name, self.repo.path)
        self.eden.clone(self.repo_name, self.mount)
        self.report_time('eden clone done')

    def populate_repo(self):
        raise NotImplementedError('individual test classes must implement '
                                  'populate_repo()')

class EdenHgTest(EdenRepoTestBase):
    '''
    Subclass of EdenTestCase which uses a single mercurial repository and
    eden mount.

    The repository is available as self.repo, and the client mount path is
    available as self.mount
    '''
    def get_repo_class(self):
        return hgrepo.HgRepository


class EdenGitTest(EdenRepoTestBase):
    '''
    Subclass of EdenTestCase which uses a single mercurial repository and
    eden mount.

    The repository is available as self.repo, and the client mount path is
    available as self.mount
    '''
    def get_repo_class(self):
        return gitrepo.GitRepository


def _replicate_test(caller_scope, replicate, test_class, args, kwargs):
    for suffix, new_class in replicate(test_class, *args, **kwargs):
        # Set the name and module information on our new subclass
        name = test_class.__name__ + suffix
        new_class.__name__ = name
        new_class.__qualname__ = name
        new_class.__module__ = test_class.__module__

        # Add the class to our caller's scope
        caller_scope[name] = new_class


def test_replicator(replicate):
    '''
    A helper function for implementing decorators that replicate TestCase
    classes so that the same test function can be run multiple times with
    several different settings.

    See the @eden_repo_test decorator for an example of how this is used.
    '''
    def decorator(*args, **kwargs):
        # We do some rather hacky things here to define new test class types
        # in our caller's scope.  This is needed so that the unittest TestLoader
        # will find the subclasses we define.
        caller_scope = inspect.currentframe().f_back.f_locals

        if len(args) == 1 and not kwargs and isinstance(args[0], type):
            # The decorator was invoked directly with the test class,
            # with no arguments or keyword arguments
            _replicate_test(caller_scope, replicate, args[0],
                            args=(), kwargs={})
            return
        else:
            def inner_decorator(test_class):
                _replicate_test(caller_scope, replicate, test_class,
                                args, kwargs)
            return inner_decorator

    return decorator


def _replicate_eden_repo_test(test_class):
    repo_types = [
        (EdenHgTest, 'Hg'),
        (EdenGitTest, 'Git'),
    ]

    for (parent_class, suffix) in repo_types:
        # Define a new class that derives from the input class
        # as well as the repo-specific parent class type
        class RepoSpecificTest(test_class, parent_class):
            pass

        yield suffix, RepoSpecificTest


# A decorator function used to create EdenHgTest and EdenGitTest
# subclasses from a given input test class.
#
# Given an input test class named "MyTest", this will create two separate
# classes named "MyTestHg" and "MyTestGit", which run the tests with
# mercurial and git repositories, respectively.
eden_repo_test = test_replicator(_replicate_eden_repo_test)
