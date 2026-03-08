import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from learnpress_dl.media import download_videos_for_lesson, download_with_ytdlp


class MediaTests(unittest.TestCase):
    def test_download_with_ytdlp_sets_headers_and_skips_cookies_when_disabled(self):
        downloader = SimpleNamespace(cookie_file="/tmp/cookies.txt", cookie_header="sid=abc")
        with mock.patch("learnpress_dl.media.shutil.which", return_value="/usr/bin/yt-dlp"):
            with mock.patch("learnpress_dl.media.run_command") as run_command:
                download_with_ytdlp(
                    downloader,
                    "https://www.dailymotion.com/embed/video/x1",
                    "/tmp/out.%(ext)s",
                    "https://example.com/lesson",
                    timeout_seconds=10,
                    include_cookies=False,
                )

        command = run_command.call_args[0][0]
        self.assertIn("--referer", command)
        self.assertIn("https://example.com/lesson", command)
        self.assertIn("--user-agent", command)
        self.assertIn("--extractor-args", command)
        self.assertIn("generic:impersonate", command)
        self.assertIn("--no-cookies", command)
        self.assertNotIn("--cookies", command)
        self.assertNotIn("--add-header", command)

    def test_dailymotion_retries_use_iframe_url_via_ytdlp(self):
        parser = SimpleNamespace(
            iframes=[{"src": "https://www.dailymotion.com/embed/video/xabc123", "title": "Demo Video"}]
        )
        downloader = SimpleNamespace(cookie_file="/tmp/cookies.txt", cookie_header="sid=abc")
        calls = []

        with tempfile.TemporaryDirectory() as lesson_dir:
            def fake_download(_downloader, iframe_src, output_path, _page_url, _timeout_seconds, include_cookies=True):
                calls.append((iframe_src, include_cookies))
                if len(calls) == 1:
                    raise RuntimeError("HTTP 503 temporary")
                final_path = output_path.replace("%(ext)s", "mp4")
                with open(final_path, "w", encoding="utf-8") as handle:
                    handle.write("ok")

            with mock.patch("learnpress_dl.media.download_with_ytdlp", side_effect=fake_download):
                downloaded = download_videos_for_lesson(
                    downloader,
                    lesson_dir,
                    "https://example.com/lesson",
                    parser,
                    timeout_seconds=30,
                    retries=2,
                    retry_delay=0.0,
                )

        self.assertEqual(
            [
                ("https://www.dailymotion.com/embed/video/xabc123", False),
                ("https://www.dailymotion.com/embed/video/xabc123", False),
            ],
            calls,
        )
        self.assertEqual("video-01-demo-video.mp4", downloaded[0]["file"])


if __name__ == "__main__":
    unittest.main()
