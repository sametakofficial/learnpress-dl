import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from yzm_dl.ui import TreeProgressUI


class FakeStream:
    def __init__(self):
        self.buffer = []

    def isatty(self):
        return False

    def write(self, text):
        self.buffer.append(text)

    def flush(self):
        return None


class FakeSize:
    def __init__(self, columns=80, lines=20):
        self.columns = columns
        self.lines = lines


class TreeUiTests(unittest.TestCase):
    def test_build_lines_prioritizes_active_course_and_lesson(self):
        ui = TreeProgressUI(enabled=False, stream=FakeStream(), terminal_size_fn=lambda: FakeSize(80, 12))
        ui.register_course(
            "course-1",
            "Course One",
            status="running",
            sections=[{"section_title": "Intro"}, {"section_title": "Advanced"}],
            lessons=[
                {"url": "lesson-1", "title": "Lesson One", "section_title": "Intro", "global_index": 1},
                {"url": "lesson-2", "title": "Lesson Two", "section_title": "Advanced", "global_index": 2},
            ],
        )
        ui.set_lesson_status("course-1", "lesson-1", "fetching-content")
        ui.set_lesson_status("course-1", "lesson-2", "finished")
        ui.register_course("course-2", "Course Two", status="new", sections=[], lessons=[])

        lines = ui.build_lines(max_height=10, max_width=80)
        joined = "\n".join(lines)

        self.assertIn("Course One", joined)
        self.assertIn("Lesson One  fetching-content", joined)
        self.assertIn("Course Two", joined)
        self.assertIn("running=1", joined)

    def test_build_lines_respects_height_limit(self):
        ui = TreeProgressUI(enabled=False, stream=FakeStream(), terminal_size_fn=lambda: FakeSize(60, 8))
        ui.register_course(
            "course-1",
            "Long Course",
            status="partial",
            sections=[{"section_title": "Section A"}],
            lessons=[
                {"url": f"lesson-{index}", "title": f"Lesson {index}", "section_title": "Section A", "global_index": index}
                for index in range(1, 6)
            ],
        )
        for index in range(1, 6):
            ui.set_lesson_status("course-1", f"lesson-{index}", "pending")

        lines = ui.build_lines(max_height=5, max_width=60)
        self.assertLessEqual(len(lines), 5)


if __name__ == "__main__":
    unittest.main()
