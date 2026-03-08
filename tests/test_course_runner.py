import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from learnpress_dl.course_runner import course_run_succeeded, filter_sections_to_lessons, process_lesson_contexts


class CourseRunnerTests(unittest.TestCase):
    def test_filter_sections_to_lessons_keeps_only_requested_lessons(self):
        sections = [
            {
                "section_title": "Section A",
                "lessons": [
                    {"url": "lesson-1", "title": "Lesson 1"},
                    {"url": "lesson-2", "title": "Lesson 2"},
                ],
            },
            {
                "section_title": "Section B",
                "lessons": [
                    {"url": "lesson-3", "title": "Lesson 3"},
                ],
            },
        ]

        filtered = filter_sections_to_lessons(sections, [{"url": "lesson-2"}])

        self.assertEqual(1, len(filtered))
        self.assertEqual("Section A", filtered[0]["section_title"])
        self.assertEqual(["lesson-2"], [lesson["url"] for lesson in filtered[0]["lessons"]])

    def test_course_run_succeeded_requires_no_failures(self):
        self.assertTrue(course_run_succeeded({"completed": 3, "failed": 0, "total": 3}))
        self.assertFalse(course_run_succeeded({"completed": 2, "failed": 1, "total": 3}))
        self.assertFalse(course_run_succeeded({"completed": 1, "failed": 0, "total": 2}))

    def test_process_lesson_contexts_uses_parallel_worker_count(self):
        contexts = [
            {
                "index": 1,
                "total": 2,
                "lesson": {"url": "lesson-1", "section_title": "Section A"},
                "lesson_dir": "/tmp/lesson-1",
                "lesson_title": "Lesson 1",
                "progress": {"status": "pending"},
            },
            {
                "index": 2,
                "total": 2,
                "lesson": {"url": "lesson-2", "section_title": "Section A"},
                "lesson_dir": "/tmp/lesson-2",
                "lesson_title": "Lesson 2",
                "progress": {"status": "pending"},
            },
        ]
        submitted = []
        observed = {}

        class FakeFuture:
            def __init__(self, result):
                self._result = result

            def result(self):
                return self._result

        class FakeExecutor:
            def __init__(self, max_workers):
                observed["max_workers"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, context, *args, **kwargs):
                submitted.append(context["lesson"]["url"])
                return FakeFuture(fn(context, *args, **kwargs))

        def fake_process(context, *_args, **_kwargs):
            return {"title": context["lesson_title"]}, {"status": "completed"}

        args = SimpleNamespace(parallel=3)
        with mock.patch("learnpress_dl.course_runner.ThreadPoolExecutor", FakeExecutor):
            with mock.patch("learnpress_dl.course_runner.as_completed", side_effect=lambda futures: list(futures)):
                with mock.patch("learnpress_dl.course_runner.process_lesson_context", side_effect=fake_process):
                    saved_by_url, progress_by_url = process_lesson_contexts(
                        contexts,
                        args,
                        groq_api_key=None,
                        require_videos=True,
                        require_transcripts=True,
                    )

        self.assertEqual(3, observed["max_workers"])
        self.assertEqual(["lesson-1", "lesson-2"], submitted)
        self.assertEqual(["lesson-1", "lesson-2"], sorted(saved_by_url.keys()))
        self.assertEqual(["lesson-1", "lesson-2"], sorted(progress_by_url.keys()))


if __name__ == "__main__":
    unittest.main()
