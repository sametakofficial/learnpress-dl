import os
import sys
import tempfile
import unittest
from unittest import mock


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from learnpress_dl.common import load_cookie_jar


class CommonTests(unittest.TestCase):
    def test_load_cookie_jar_sanitizes_malformed_lines(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("# Netscape HTTP Cookie File\n")
            handle.write("example.com\tFALSE\t/\tFALSE\t0\tfoo\tbar\n")
            handle.write("BADLINE\n")
            cookie_path = handle.name

        try:
            jar = load_cookie_jar(cookie_path, retries=1)
        finally:
            os.remove(cookie_path)

        self.assertEqual(1, len(jar))

    def test_load_cookie_jar_retries_before_sanitizing(self):
        real_class = __import__("http.cookiejar", fromlist=["MozillaCookieJar"]).MozillaCookieJar
        attempts = {"count": 0}

        class FlakyJar(real_class):
            def load(self, filename, ignore_discard=False, ignore_expires=False):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise __import__("http.cookiejar", fromlist=["LoadError"]).LoadError("temporary parse failure")
                return super().load(filename, ignore_discard=ignore_discard, ignore_expires=ignore_expires)

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write("# Netscape HTTP Cookie File\n")
            handle.write("example.com\tFALSE\t/\tFALSE\t0\tfoo\tbar\n")
            cookie_path = handle.name

        try:
            with mock.patch("learnpress_dl.common.http.cookiejar.MozillaCookieJar", FlakyJar):
                jar = load_cookie_jar(cookie_path, retries=2, retry_delay=0.0)
        finally:
            os.remove(cookie_path)

        self.assertEqual(1, len(jar))
        self.assertEqual(2, attempts["count"])


if __name__ == "__main__":
    unittest.main()
