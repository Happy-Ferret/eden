#!/usr/bin/env python3
#
# Copyright (c) 2004-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

from textwrap import dedent

from .lib.hg_extension_test_base import EdenHgTestCase, hg_test


@hg_test
class CopyTest(EdenHgTestCase):
    def populate_backing_repo(self, repo):
        repo.write_file('hello.txt', 'hola')
        repo.commit('Initial commit.\n')

    def test_copy_file_within_directory(self):
        self.hg('copy', 'hello.txt', 'goodbye.txt')
        self.assert_status({'goodbye.txt': 'A'})
        extended_status = self.hg('status', '--copies')
        self.assertEqual(dedent('''\
        A goodbye.txt
          hello.txt
        '''), extended_status)
        self.assert_copy_map({'goodbye.txt': 'hello.txt'})

        self.repo.commit('Commit copied file.\n')
        self.assert_status_empty()
        self.assert_copy_map({})

    def test_copy_file_then_revert_it(self):
        self.hg('copy', 'hello.txt', 'goodbye.txt')
        self.assert_status({'goodbye.txt': 'A'})
        self.assert_copy_map({'goodbye.txt': 'hello.txt'})

        self.hg('revert', '--no-backup', '--all')
        self.assert_status({'goodbye.txt': '?'})
        self.assert_copy_map({})

        self.hg('add', 'goodbye.txt')
        extended_status = self.hg('status', '--copies')
        self.assertEqual(dedent('''\
        A goodbye.txt
        '''), extended_status)
