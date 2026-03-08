import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from learnpress_dl.course_runner import filter_sections_to_lessons


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


if __name__ == "__main__":
    unittest.main()
