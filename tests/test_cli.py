import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from learnpress_dl.cli import build_parser, configure_logging, resolve_target_scope
from learnpress_dl.common import LOG_LEVELS, get_log_level, set_log_level


class CliTests(unittest.TestCase):
    def tearDown(self):
        set_log_level("INFO")

    def test_parser_uses_optional_url_and_check_depth(self):
        parser = build_parser()
        args = parser.parse_args(["--check-depth", "deep", "https://example.com/course"])

        self.assertEqual("https://example.com/course", args.url)
        self.assertEqual("deep", args.check_depth)

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


if __name__ == "__main__":
    unittest.main()
