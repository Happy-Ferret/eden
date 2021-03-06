#!/usr/bin/env python3
#
# Copyright (c) 2016-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

import os
import unittest

from .lib import testcase


@testcase.eden_repo_test
class PersistenceTest:
    def populate_repo(self):
        self.repo.write_file('file_in_root', 'contents1')
        self.repo.write_file('subdir/file_in_subdir', 'contents2')
        self.repo.commit('Initial commit.')

    def edenfs_logging_settings(self):
        return {'eden.strace': 'DBG7', 'eden.fs.fuse': 'DBG7'}

    @unittest.skip('TODO: this is not fully implemented yet')
    def test_preserves_inode_numbers_and_timestamps_for_nonmaterialized_inodes_across_restarts(self):
        inode_paths = [
            'file_in_root',
            'subdir',  # we care about trees too
            'subdir/file_in_subdir',
        ]

        old_stats = [
            os.lstat(os.path.join(self.mount, path))
            for path in inode_paths]

        self.eden.shutdown()
        self.eden.start()

        new_stats = [
            os.lstat(os.path.join(self.mount, path))
            for path in inode_paths]

        for (path, old_stat, new_stat) in zip(inode_paths, old_stats, new_stats):
            self.assertEqual(old_stat.st_ino, new_stat.st_ino,
                             f"inode numbers must line up for path {path}")
            self.assertEqual(old_stat.st_atime, new_stat.st_atime,
                             f"atime must line up for path {path}")
            self.assertEqual(old_stat.st_mtime, new_stat.st_mtime,
                             f"mtime must line up for path {path}")
            self.assertEqual(old_stat.st_ctime, new_stat.st_ctime,
                             f"ctime must line up for path {path}")
