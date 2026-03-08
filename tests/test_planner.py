import json
import os
import tempfile
import unittest


from yzm_dl.planner import build_course_plan, build_lesson_plan, build_site_plan, compact_course_plan, write_course_plan


class PlannerTests(unittest.TestCase):
    def test_build_lesson_plan_marks_transcribe_only_when_video_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lesson_dir = os.path.join(tmpdir, "lesson")
            os.makedirs(lesson_dir)
            video_name = "video-01.mp4"
            with open(os.path.join(lesson_dir, video_name), "wb") as handle:
                handle.write(b"video")

            local_entry = {
                "lesson_dir": lesson_dir,
                "progress": {
                    "status": "in_progress",
                    "classification": "video",
                    "steps": {
                        "page_fetch": "completed",
                        "materials_fetch": "completed",
                        "video_download": "completed",
                        "audio_extract": "pending",
                        "transcript": "pending",
                        "render_html": "completed",
                        "render_text": "completed",
                        "write_json": "completed",
                        "finalize": "completed",
                    },
                },
                "lesson_meta": {
                    "content_type": "video",
                    "videos": [
                        {
                            "file": video_name,
                            "title": "Video One",
                            "transcript": {
                                "transcript_text_file": "video-01.transcript.txt",
                                "transcript_json_file": "video-01.transcript.json",
                            },
                        }
                    ],
                },
            }

            plan = build_lesson_plan(
                {"url": "https://example.com/lesson", "title": "Lesson", "section_title": "Intro"},
                local_entry,
                require_videos=True,
                require_transcripts=True,
            )

            self.assertEqual("transcribe_only", plan["planned_action"])
            self.assertTrue(plan["actionable"])
            self.assertEqual("transcribe_only", plan["video_actions"][0]["action"])

    def test_build_course_plan_counts_actionable_lessons(self):
        course_info = {
            "title": "Course",
            "url": "https://example.com/courses/course/",
            "continue_url": "https://example.com/courses/course/lessons/one/",
            "curriculum_sections": [
                {
                    "lessons": [
                        {"url": "https://example.com/courses/course/lessons/one/", "title": "One", "section_title": "Intro"},
                        {"url": "https://example.com/courses/course/lessons/two/", "title": "Two", "section_title": "Intro"},
                    ]
                }
            ],
        }
        local_record = {
            "lessons_by_url": {
                "https://example.com/courses/course/lessons/one/": {
                    "progress": {
                        "status": "completed",
                        "classification": "text",
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
                    "lesson_meta": {"content_type": "text"},
                }
            }
        }
        check = {
            "course_title": "Course",
            "course_url": "https://example.com/courses/course/",
            "continue_url": "https://example.com/courses/course/lessons/one/",
            "output_dir": "/tmp/course",
            "status": "partial",
            "remote": {"section_count": 1, "lesson_count": 2},
            "local": {"lesson_count": 1, "completed_lessons": 1, "partial_lessons": 0, "failed_lessons": 0, "missing_lessons": 1},
            "diff": {"missing_lessons": 1, "partial_lessons": 0, "failed_lessons": 0, "extra_local_lessons": 0},
        }

        course_plan = build_course_plan(course_info, local_record, check)
        site_plan = build_site_plan("https://example.com", "https://example.com/kurslar/", [course_plan])

        self.assertEqual("resume_needed", course_plan["status"])
        self.assertEqual(1, course_plan["actionable_lesson_count"])
        self.assertEqual(1, site_plan["counts"]["resume_needed"])

    def test_write_course_plan_only_when_directory_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_dir = os.path.join(tmpdir, "missing")
            self.assertIsNone(write_course_plan(missing_dir, {"status": "new"}, create_dir=False))

            existing_dir = os.path.join(tmpdir, "existing")
            os.makedirs(existing_dir)
            path = write_course_plan(existing_dir, {"status": "complete"}, create_dir=False)
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual("complete", json.load(handle)["status"])

    def test_compact_course_plan_strips_lesson_payload(self):
        compact = compact_course_plan(
            {
                "course_title": "Course",
                "course_url": "https://example.com/course",
                "status": "resume_needed",
                "reason": "course_has_actionable_lessons",
                "remote": {"lesson_count": 2},
                "local": {"completed_lessons": 1},
                "diff": {"missing_lessons": 1},
                "actionable_lesson_count": 1,
                "lessons": [{"lesson_url": "x"}],
            }
        )

        self.assertEqual("resume_needed", compact["status"])
        self.assertEqual(1, compact["actionable_lesson_count"])
        self.assertNotIn("lessons", compact)


if __name__ == "__main__":
    unittest.main()
