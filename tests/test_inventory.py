import json
import os
import tempfile
import unittest

from learnpress_dl.inventory import (
    CHECK_MODE_DEEP,
    CHECK_MODE_SHALLOW,
    build_bootstrap_failed_check,
    build_course_check,
    build_course_check_from_lessons,
    compact_course_check,
    deep_validate_lesson,
    index_local_courses,
    match_local_course,
    summarize_site_check,
    write_course_check,
)


class InventoryTests(unittest.TestCase):
    def test_indexes_legacy_course_by_course_url_from_lesson_start_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            course_dir = os.path.join(tmpdir, "legacy-course-dir")
            lesson_dir = os.path.join(course_dir, "01-section", "01-lesson")
            os.makedirs(lesson_dir)

            with open(os.path.join(course_dir, "state.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "course_title": "Legacy Course",
                        "start_url": "https://www.example.com/courses/course-one/lessons/welcome/",
                        "resolved_url": "https://www.example.com/courses/course-one/lessons/welcome/",
                    },
                    handle,
                )

            with open(os.path.join(lesson_dir, "lesson.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "title": "Welcome",
                        "page_url": "https://www.example.com/courses/course-one/lessons/welcome/",
                        "content_type": "text",
                        "lesson_meta": {"url": "https://www.example.com/courses/course-one/lessons/welcome/"},
                        "videos": [],
                    },
                    handle,
                )

            index = index_local_courses(tmpdir)
            record = match_local_course(index, {"resolved_url": "https://www.example.com/courses/course-one/", "slug": "course-one"})

            self.assertIsNotNone(record)
            self.assertEqual(course_dir, record["output_dir"])
            self.assertEqual("https://www.example.com/courses/course-one/", record["course_url"])
            self.assertEqual(1, record["completed_lessons"])

    def test_build_course_check_marks_missing_and_partial_lessons(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            complete_dir = os.path.join(tmpdir, "welcome")
            partial_dir = os.path.join(tmpdir, "setup")
            os.makedirs(complete_dir)
            os.makedirs(partial_dir)
            with open(os.path.join(complete_dir, "lesson.html"), "w", encoding="utf-8") as handle:
                handle.write("<p>hello world content</p>")
            with open(os.path.join(complete_dir, "lesson.txt"), "w", encoding="utf-8") as handle:
                handle.write("hello world content for text length")
            with open(os.path.join(complete_dir, "lesson.json"), "w", encoding="utf-8") as handle:
                json.dump({"content_type": "text", "videos": []}, handle)

            local_record = {
                "output_dir": tmpdir,
                "lessons_by_url": {
                    "https://www.example.com/courses/course-one/lessons/welcome/": {
                        "lesson_dir": complete_dir,
                        "lesson_meta": {"content_type": "text", "videos": []},
                        "progress": {
                            "lesson_url": "https://www.example.com/courses/course-one/lessons/welcome/",
                            "classification": "text",
                            "status": "completed",
                            "steps": {
                                "page_fetch": "completed",
                                "materials_fetch": "completed",
                                "video_download": "skipped",
                                "audio_extract": "skipped",
                                "transcript": "skipped",
                                "render_html": "completed",
                                "render_text": "completed",
                                "write_json": "completed",
                                "finalize": "completed",
                            },
                        },
                    },
                    "https://www.example.com/courses/course-one/lessons/setup/": {
                        "lesson_dir": partial_dir,
                        "lesson_meta": {"content_type": "video", "videos": []},
                        "progress": {
                            "lesson_url": "https://www.example.com/courses/course-one/lessons/setup/",
                            "classification": "video",
                            "status": "in_progress",
                            "steps": {
                                "page_fetch": "completed",
                                "materials_fetch": "completed",
                                "video_download": "pending",
                                "audio_extract": "pending",
                                "transcript": "pending",
                                "render_html": "completed",
                                "render_text": "completed",
                                "write_json": "completed",
                                "finalize": "completed",
                            },
                        },
                    },
                },
            }
            course_info = {
                "title": "Course One",
                "resolved_url": "https://www.example.com/courses/course-one/",
                "continue_url": "https://www.example.com/courses/course-one/lessons/welcome/",
                "curriculum_sections": [
                    {
                        "lessons": [
                            {"url": "https://www.example.com/courses/course-one/lessons/welcome/"},
                            {"url": "https://www.example.com/courses/course-one/lessons/setup/"},
                            {"url": "https://www.example.com/courses/course-one/lessons/deep-dive/"},
                        ]
                    }
                ],
            }

            check = build_course_check(course_info, local_record, require_videos=True, require_transcripts=False, check_mode=CHECK_MODE_DEEP)

            self.assertEqual("partial", check["status"])
            self.assertEqual(1, check["local"]["completed_lessons"])
            self.assertEqual(1, check["diff"]["partial_lessons"])
            self.assertEqual(1, check["diff"]["missing_lessons"])

    def test_shallow_check_uses_folder_match_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lesson_dir = os.path.join(
                tmpdir,
                "01-intro",
                "01-welcome",
            )
            os.makedirs(lesson_dir)

            remote_lessons = [
                {
                    "url": "https://www.example.com/courses/course-one/lessons/welcome/",
                    "title": "Welcome",
                    "section_title": "Intro",
                    "section_index": 1,
                    "lesson_in_section": 1,
                }
            ]
            check = build_course_check_from_lessons(
                course_title="Course One",
                course_url="https://www.example.com/courses/course-one/",
                continue_url=remote_lessons[0]["url"],
                output_dir=tmpdir,
                remote_lessons=remote_lessons,
                local_lessons_by_url={},
                section_count=1,
                check_mode=CHECK_MODE_SHALLOW,
            )

            self.assertEqual("complete", check["status"])
            self.assertEqual(CHECK_MODE_SHALLOW, check["check_mode"])
            self.assertEqual(1, check["local"]["completed_lessons"])

    def test_deep_validate_lesson_detects_missing_content_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lesson_dir = os.path.join(tmpdir, "lesson")
            os.makedirs(lesson_dir)
            with open(os.path.join(lesson_dir, "lesson.json"), "w", encoding="utf-8") as handle:
                json.dump({"content_type": "text"}, handle)

            validation = deep_validate_lesson(
                {
                    "lesson_dir": lesson_dir,
                    "lesson_meta": {"content_type": "text", "videos": []},
                    "progress": {"classification": "text", "steps": {}},
                }
            )

            self.assertFalse(validation["ok"])
            self.assertIn("missing_html", validation["issues"])
            self.assertIn("missing_text", validation["issues"])

    def test_deep_check_marks_complete_progress_as_partial_when_files_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lesson_dir = os.path.join(tmpdir, "lesson")
            os.makedirs(lesson_dir)
            remote_lessons = [
                {
                    "url": "https://www.example.com/courses/course-one/lessons/welcome/",
                    "title": "Welcome",
                    "section_title": "Intro",
                    "section_index": 1,
                    "lesson_in_section": 1,
                }
            ]
            local_lessons = {
                remote_lessons[0]["url"]: {
                    "lesson_dir": lesson_dir,
                    "lesson_meta": {"content_type": "text", "videos": []},
                    "progress": {
                        "classification": "text",
                        "status": "completed",
                        "steps": {
                            "page_fetch": "completed",
                            "materials_fetch": "completed",
                            "render_html": "completed",
                            "render_text": "completed",
                            "write_json": "completed",
                            "finalize": "completed",
                            "video_download": "skipped",
                            "audio_extract": "skipped",
                            "transcript": "skipped",
                        },
                    },
                }
            }
            check = build_course_check_from_lessons(
                course_title="Course One",
                course_url="https://www.example.com/courses/course-one/",
                continue_url=remote_lessons[0]["url"],
                output_dir=tmpdir,
                remote_lessons=remote_lessons,
                local_lessons_by_url=local_lessons,
                section_count=1,
                check_mode=CHECK_MODE_DEEP,
            )

            self.assertEqual("partial", check["status"])
            self.assertEqual(1, check["diff"]["partial_lessons"])
            self.assertEqual(1, check["validation"]["invalid_lessons"])

    def test_summarize_site_check_counts_and_totals(self):
        summary = summarize_site_check(
            [
                {"status": "complete", "diff": {"missing_lessons": 0, "partial_lessons": 0, "failed_lessons": 0}},
                {"status": "partial", "course_title": "Partial Course", "diff": {"missing_lessons": 3, "partial_lessons": 2, "failed_lessons": 1}},
                {"status": "new", "course_title": "New Course", "diff": {"missing_lessons": 10, "partial_lessons": 0, "failed_lessons": 0}},
            ]
        )

        self.assertEqual(1, summary["counts"]["complete"])
        self.assertEqual(1, summary["counts"]["partial"])
        self.assertEqual(1, summary["counts"]["new"])
        self.assertEqual(13, summary["missing_lessons"])
        self.assertEqual(2, summary["partial_lessons"])
        self.assertEqual(1, summary["failed_lessons"])
        self.assertEqual("New Course", summary["actionable"][0]["course_title"])

    def test_write_course_check_writes_only_when_directory_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_dir = os.path.join(tmpdir, "missing")
            existing_dir = os.path.join(tmpdir, "existing")
            os.makedirs(existing_dir)

            payload = {"status": "partial", "course_title": "Course"}
            self.assertIsNone(write_course_check(missing_dir, payload, create_dir=False))

            path = write_course_check(existing_dir, payload, create_dir=False)
            self.assertEqual(os.path.join(existing_dir, "course-check.json"), path)
            self.assertTrue(os.path.exists(path))

    def test_compact_course_check_strips_lesson_level_lists(self):
        compact = compact_course_check(
            {
                "course_title": "Course",
                "course_url": "https://example.com/course",
                "continue_url": "https://example.com/course/lessons/one",
                "output_dir": "/tmp/course",
                "status": "partial",
                "remote": {"lesson_count": 2},
                "local": {"completed_lessons": 1},
                "diff": {"missing_lessons": 1},
                "missing_lesson_urls": ["one"],
            }
        )

        self.assertEqual("Course", compact["course_title"])
        self.assertNotIn("missing_lesson_urls", compact)

    def test_build_bootstrap_failed_check_marks_missing_course(self):
        check = build_bootstrap_failed_check({"title": "Course", "url": "https://example.com/course", "section_count": 2, "lesson_count": 7})

        self.assertEqual("bootstrap_failed", check["status"])
        self.assertEqual(7, check["diff"]["missing_lessons"])


if __name__ == "__main__":
    unittest.main()
