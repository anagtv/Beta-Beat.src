'''
Created on 15 Oct 2013

@author: vimaier
'''
import unittest
import os

import utils.iotools


class TestReplacingKeywords(unittest.TestCase):
    """ tests function utils.iotools.replace_keywords_in_textfile """

    def setUp(self):
        self.__created_files = []
        self.__text_before_replacing = """This file was generated by utils.test.iotools_test.py
The following should be equal after replacing:
%(key_a)s == value_for_key_a
%(key_b)s == 2345.2123
%(key_c)d == 2345
%(key_d)f == 2345.212300
"""
        self.__text_after_replacing = """This file was generated by utils.test.iotools_test.py
The following should be equal after replacing:
value_for_key_a == value_for_key_a
2345.2123 == 2345.2123
2345 == 2345
2345.212300 == 2345.212300
"""
        self.__dict_for_replacing = {
                        "key_a": "value_for_key_a",
                        "key_b": 2345.2123,
                        "key_c": 2345.2123,
                        "key_d": 2345.2123
        }
        f_name = "replacing_test.txt"
        utils.iotools.write_string_into_new_file(f_name, self.__text_before_replacing)
        self.__created_files.append(f_name)
        self.__created_files.append("replaced_test.txt")

    def tearDown(self):
        for f_name in self.__created_files:
            utils.iotools.delete_item(f_name)

    def test_replacing(self):
        assumed_lines = self.__text_after_replacing

        utils.iotools.replace_keywords_in_textfile("replacing_test.txt", self.__dict_for_replacing, "replaced_test.txt")
        all_lines = utils.iotools.read_all_lines_in_textfile("replaced_test.txt")
        self.assertTrue(all_lines == assumed_lines, "Strings are not equal:\n" + all_lines + assumed_lines)

        # Tests replacing in same file
        utils.iotools.replace_keywords_in_textfile("replacing_test.txt", self.__dict_for_replacing)
        all_lines = utils.iotools.read_all_lines_in_textfile("replacing_test.txt")
        self.assertTrue(all_lines == assumed_lines, "Strings are not equal:\n" + all_lines + assumed_lines)


class TestGetFilenamesInDir(unittest.TestCase):

    def setUp(self):
        self.__assumed_list_of_abs_filepaths = []
        self.__abs_path_to_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "root_for_test")
        self.__create_dirs_and_files()

    def tearDown(self):
        self.__delete_created_dirs_and_files()

    def test_filenames(self):
        received_all_abs_filenames = utils.iotools.get_all_absolute_filenames_in_dir_and_subdirs(self.__abs_path_to_root)
        received_all_abs_filenames.sort()
        self.assertEqual(received_all_abs_filenames, self.__assumed_list_of_abs_filepaths,
                         "Abs. filenames are not equal:\n" + str(received_all_abs_filenames) + "\n" + str(self.__assumed_list_of_abs_filepaths))

        received_filenames = utils.iotools.get_all_filenames_in_dir_and_subdirs(self.__abs_path_to_root)
        received_filenames.sort()
        assumed_filenames = ["file1", "file2", "file3", "file4"]
        self.assertEqual(received_filenames, assumed_filenames,
                         "Filenames are not equal:\n" + str(received_filenames) + "\n" + str(assumed_filenames))

    def __create_dirs_and_files(self):
        self.__assumed_list_of_abs_filepaths.append(os.path.join(self.__abs_path_to_root, "file1"))
        self.__assumed_list_of_abs_filepaths.append(os.path.join(self.__abs_path_to_root, "file2"))
        self.__assumed_list_of_abs_filepaths.append(os.path.join(self.__abs_path_to_root, "subdir1", "file3"))
        self.__assumed_list_of_abs_filepaths.append(os.path.join(self.__abs_path_to_root, "subdir1", "file4"))
        utils.iotools.create_dirs(os.path.join(self.__abs_path_to_root, "subdir1"))
        utils.iotools.create_dirs(os.path.join(self.__abs_path_to_root, "subdir2"))
        for abs_file_name in self.__assumed_list_of_abs_filepaths:
            with open(abs_file_name, "w") as new_file:
                new_file.write("Hello file!")

    def __delete_created_dirs_and_files(self):
        utils.iotools.delete_item(self.__abs_path_to_root)

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()