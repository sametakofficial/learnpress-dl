import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from learnpress_dl.site_runner import course_check_succeeded


class SiteRunnerTests(unittest.TestCase):
    def test_course_check_succeeded_requires_all_lessons_and_zero_failures(self):
        success_check = {
            "remote": {"lesson_count": 4},
            "local": {"completed_lessons": 4, "failed_lessons": 0},
        }
        partial_check = {
            "remote": {"lesson_count": 4},
            "local": {"completed_lessons": 3, "failed_lessons": 0},
        }
        failed_check = {
            "remote": {"lesson_count": 4},
            "local": {"completed_lessons": 4, "failed_lessons": 1},
        }

        self.assertTrue(course_check_succeeded(success_check))
        self.assertFalse(course_check_succeeded(partial_check))
        self.assertFalse(course_check_succeeded(failed_check))


if __name__ == "__main__":
    unittest.main()
