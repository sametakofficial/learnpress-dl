import shutil
import sys
import threading
import time


ACTIVE_LESSON_STATUSES = {
    "checking",
    "fetching-content",
    "fetching-materials",
    "fetching-video",
    "transcription",
    "rendering",
}

COURSE_STATUS_PRIORITY = {
    "running": 0,
    "checking": 1,
    "partial": 2,
    "resume_needed": 2,
    "recovery_needed": 3,
    "new": 3,
    "queued": 4,
    "complete": 5,
    "finished": 6,
    "skipped": 7,
    "failed": 8,
}


def truncate_text(text, width):
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


class TreeProgressUI:
    def __init__(self, enabled=True, stream=None, terminal_size_fn=None, redraw_interval=0.12):
        self.stream = stream or sys.stdout
        self.terminal_size_fn = terminal_size_fn or (lambda: shutil.get_terminal_size((120, 40)))
        self.enabled = bool(enabled and getattr(self.stream, "isatty", lambda: False)())
        self.redraw_interval = redraw_interval
        self.lock = threading.Lock()
        self.courses = {}
        self.course_order = []
        self.last_render_at = 0.0

    def register_course(self, course_key, title, status="queued", sections=None, lessons=None):
        with self.lock:
            course = self.courses.get(course_key)
            if not course:
                course = {
                    "key": course_key,
                    "title": title,
                    "status": status,
                    "sections": {},
                    "section_order": [],
                    "lessons": {},
                    "last_update": time.time(),
                }
                self.courses[course_key] = course
                self.course_order.append(course_key)
            else:
                course["title"] = title or course["title"]
                course["status"] = status or course["status"]
                course["last_update"] = time.time()

            if sections is not None and lessons is not None:
                self._attach_course_structure_locked(course, sections, lessons)

        self.render()

    def attach_course_structure(self, course_key, sections, lessons):
        with self.lock:
            course = self.courses.get(course_key)
            if not course:
                return
            self._attach_course_structure_locked(course, sections, lessons)
            course["last_update"] = time.time()
        self.render()

    def _attach_course_structure_locked(self, course, sections, lessons):
        section_titles = []
        for section in sections:
            title = section.get("section_title") or f"Section {section.get('section_index') or len(section_titles) + 1}"
            if title not in course["sections"]:
                course["sections"][title] = {"title": title, "lesson_urls": []}
            section_titles.append(title)
        course["section_order"] = section_titles or course["section_order"]

        for lesson in lessons:
            lesson_url = lesson["url"]
            section_title = lesson.get("section_title") or (section_titles[0] if section_titles else "Other")
            if section_title not in course["sections"]:
                course["sections"][section_title] = {"title": section_title, "lesson_urls": []}
                course["section_order"].append(section_title)
            lesson_entry = course["lessons"].get(lesson_url)
            if not lesson_entry:
                lesson_entry = {
                    "title": lesson.get("title") or lesson_url,
                    "section_title": section_title,
                    "status": "pending",
                    "order": lesson.get("global_index") or len(course["lessons"]) + 1,
                    "last_update": time.time(),
                }
                course["lessons"][lesson_url] = lesson_entry
                course["sections"][section_title]["lesson_urls"].append(lesson_url)
            else:
                lesson_entry["title"] = lesson.get("title") or lesson_entry["title"]
                lesson_entry["section_title"] = section_title

    def set_course_status(self, course_key, status):
        with self.lock:
            course = self.courses.get(course_key)
            if not course:
                return
            course["status"] = status
            course["last_update"] = time.time()
        self.render()

    def set_lesson_status(self, course_key, lesson_url, status, title=None, section_title=None):
        with self.lock:
            course = self.courses.get(course_key)
            if not course:
                return
            lesson = course["lessons"].get(lesson_url)
            if not lesson:
                normalized_section = section_title or "Other"
                if normalized_section not in course["sections"]:
                    course["sections"][normalized_section] = {"title": normalized_section, "lesson_urls": []}
                    course["section_order"].append(normalized_section)
                lesson = {
                    "title": title or lesson_url,
                    "section_title": normalized_section,
                    "status": status,
                    "order": len(course["lessons"]) + 1,
                    "last_update": time.time(),
                }
                course["lessons"][lesson_url] = lesson
                course["sections"][normalized_section]["lesson_urls"].append(lesson_url)
            else:
                if title:
                    lesson["title"] = title
                if section_title and section_title != lesson["section_title"]:
                    old_section = lesson["section_title"]
                    if lesson_url in course["sections"].get(old_section, {}).get("lesson_urls", []):
                        course["sections"][old_section]["lesson_urls"].remove(lesson_url)
                    if section_title not in course["sections"]:
                        course["sections"][section_title] = {"title": section_title, "lesson_urls": []}
                        course["section_order"].append(section_title)
                    course["sections"][section_title]["lesson_urls"].append(lesson_url)
                    lesson["section_title"] = section_title
                lesson["status"] = status
                lesson["last_update"] = time.time()
            course["last_update"] = time.time()
        self.render()

    def build_lines(self, max_height=None, max_width=None):
        with self.lock:
            size = self.terminal_size_fn()
            width = max_width or size.columns
            height = max_height or max(10, size.lines - 1)

            header = self._build_header_lines(width)
            available = max(0, height - len(header))
            body = self._build_body_lines(width, available)
            return header + body[:available]

    def _build_header_lines(self, width):
        counts = {"running": 0, "checking": 0, "partial": 0, "new": 0, "complete": 0}
        active_lessons = 0
        for course in self.courses.values():
            status = course.get("status")
            if status in {"partial", "resume_needed", "recovery_needed"}:
                counts["partial"] += 1
            elif status in counts:
                counts[status] += 1
            for lesson in course["lessons"].values():
                if lesson.get("status") in ACTIVE_LESSON_STATUSES:
                    active_lessons += 1

        line1 = truncate_text(
            f"LearnPress DL | running={counts['running']} checking={counts['checking']} partial={counts['partial']} new={counts['new']} complete={counts['complete']}",
            width,
        )
        line2 = truncate_text(f"Active lessons={active_lessons}", width)
        return [line1, line2, ""]

    def _build_body_lines(self, width, available):
        lines = []
        for course in self._ordered_courses():
            block = self._build_course_block(course, width)
            if not block:
                continue
            if available and len(lines) + len(block) > available:
                remaining = available - len(lines)
                if remaining > 0:
                    lines.extend(block[:remaining])
                break
            lines.extend(block)
        return lines

    def _ordered_courses(self):
        def sort_key(course):
            return (
                COURSE_STATUS_PRIORITY.get(course.get("status"), 99),
                -course.get("last_update", 0.0),
                self.course_order.index(course["key"]),
            )

        return sorted((self.courses[key] for key in self.course_order), key=sort_key)

    def _build_course_block(self, course, width):
        total_lessons = len(course["lessons"])
        finished_lessons = sum(1 for lesson in course["lessons"].values() if lesson.get("status") == "finished")
        course_line = truncate_text(
            f"{course['title']}  {finished_lessons}/{total_lessons or 0}  {course.get('status')}",
            width,
        )
        lines = [course_line]

        interesting_sections = self._pick_interesting_sections(course)
        for section_title in interesting_sections:
            section = course["sections"][section_title]
            lesson_urls = section["lesson_urls"]
            section_total = len(lesson_urls)
            section_finished = sum(1 for url in lesson_urls if course["lessons"].get(url, {}).get("status") == "finished")
            lines.append(truncate_text(f"  {section_title}  {section_finished}/{section_total}", width))

            for lesson_url in self._pick_section_lessons(course, section_title):
                lesson = course["lessons"][lesson_url]
                lines.append(truncate_text(f"    {lesson['title']}  {lesson['status']}", width))

        return lines + [""]

    def _pick_interesting_sections(self, course):
        ranked = []
        for section_title in course["section_order"]:
            section = course["sections"][section_title]
            lessons = [course["lessons"][url] for url in section["lesson_urls"] if url in course["lessons"]]
            active = sum(1 for lesson in lessons if lesson.get("status") in ACTIVE_LESSON_STATUSES)
            unfinished = sum(1 for lesson in lessons if lesson.get("status") != "finished")
            last_update = max((lesson.get("last_update", 0.0) for lesson in lessons), default=0.0)
            if active or unfinished or course.get("status") in {"running", "checking", "partial"}:
                ranked.append((active, unfinished, last_update, section_title))
        ranked.sort(reverse=True)
        return [section_title for _active, _unfinished, _last_update, section_title in ranked[:2]]

    def _pick_section_lessons(self, course, section_title):
        section = course["sections"][section_title]
        lesson_urls = [url for url in section["lesson_urls"] if url in course["lessons"]]
        lesson_urls.sort(
            key=lambda url: (
                course["lessons"][url].get("status") not in ACTIVE_LESSON_STATUSES,
                course["lessons"][url].get("status") == "finished",
                -course["lessons"][url].get("last_update", 0.0),
                course["lessons"][url].get("order", 0),
            )
        )
        return lesson_urls[:3]

    def render(self, force=False):
        if not self.enabled:
            return
        now = time.time()
        if not force and now - self.last_render_at < self.redraw_interval:
            return
        self.last_render_at = now
        lines = self.build_lines()
        output = "\x1b[2J\x1b[H" + "\n".join(lines)
        self.stream.write(output)
        self.stream.flush()

    def finish(self):
        if not self.enabled:
            return
        self.render(force=True)
        self.stream.write("\n")
        self.stream.flush()
