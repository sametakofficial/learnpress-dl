import os
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from learnpress_dl.site_runner import course_check_succeeded, create_run_archive


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

    def test_create_run_archive_uses_output_directory_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("learnpress_dl.site_runner.time.strftime", return_value="20260308-091500"):
                with mock.patch("learnpress_dl.site_runner.zip_directory", return_value=f"{tmpdir}-20260308-091500.zip") as zip_directory:
                    archive_path = create_run_archive(tmpdir)

        zip_directory.assert_called_once_with(
            tmpdir,
            archive_base_path=f"{tmpdir}-20260308-091500",
        )
        self.assertEqual(f"{tmpdir}-20260308-091500.zip", archive_path)


if __name__ == "__main__":
    unittest.main()
