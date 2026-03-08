import os
import sys
import unittest
from unittest import mock


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from learnpress_dl.cli import build_parser, configure_logging, main, resolve_target_scope
from learnpress_dl.common import LOG_LEVELS, get_log_level, set_log_level


class CliTests(unittest.TestCase):
    def tearDown(self):
        set_log_level("INFO")

    def test_parser_uses_optional_url_and_check_depth(self):
        parser = build_parser()
        args = parser.parse_args(["--check-depth", "deep", "--zip-courses", "--parallel", "8", "https://example.com/course"])

        self.assertEqual("https://example.com/course", args.url)
        self.assertEqual("deep", args.check_depth)
        self.assertTrue(args.zip_courses)
        self.assertEqual(8, args.parallel)

    def test_text_workers_alias_maps_to_parallel(self):
        parser = build_parser()
        args = parser.parse_args(["--text-workers", "6"])

        self.assertEqual(6, args.parallel)

    def test_parser_supports_retry_failed(self):
        parser = build_parser()
        args = parser.parse_args(["--retry-failed"])

        self.assertTrue(args.retry_failed)

    def test_verbose_and_quiet_conflict(self):
        parser = build_parser()
        args = parser.parse_args(["--verbose", "--quiet"])

        with self.assertRaises(ValueError):
            configure_logging(args)

    def test_configure_logging_sets_debug_level(self):
        parser = build_parser()
        args = parser.parse_args(["--verbose"])
        configure_logging(args)

        self.assertEqual(LOG_LEVELS["DEBUG"], get_log_level())

    def test_resolve_target_scope_prefers_url_and_falls_back_to_base_url(self):
        self.assertEqual("single", resolve_target_scope("https://example.com/course", "https://example.com"))
        self.assertEqual("multi", resolve_target_scope(None, "https://example.com"))
        self.assertIsNone(resolve_target_scope(None, None))

    def test_main_zips_single_course_even_when_run_is_partial(self):
        with mock.patch("learnpress_dl.cli.run_single_course", return_value={"completed": 1, "failed": 1, "total": 2, "output_dir": "/tmp/course"}) as run_single_course:
            with mock.patch("learnpress_dl.cli.zip_directory", return_value="/tmp/course-20260308-000000.zip") as zip_directory:
                with mock.patch("builtins.print") as fake_print:
                    main([
                        "--cookie-header",
                        "session=abc",
                        "--zip-courses",
                        "https://example.com/course",
                    ])

        run_single_course.assert_called_once()
        zip_directory.assert_called_once()
        fake_print.assert_called()


if __name__ == "__main__":
    unittest.main()
