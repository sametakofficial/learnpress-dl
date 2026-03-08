import unittest

from yzm_dl.discovery import bootstrap_course, discover_courses
from yzm_dl.parsers import extract_archive_courses, extract_continue_url


ARCHIVE_HTML = """
<html>
  <body>
    <div class="thim-ekits-course__item course">
      <h5><a href="https://www.example.com/courses/course-one/">Course One Title</a></h5>
      <a class="elementor-button" href="https://www.example.com/courses/course-one/">View Detail</a>
    </div>
    <div class="thim-ekits-course__item course">
      <a href="https://www.example.com/courses/course-two/"><img src="thumb.jpg" alt=""></a>
      <h5><a href="https://www.example.com/courses/course-two/">Course Two Title</a></h5>
    </div>
  </body>
</html>
"""


COURSE_HTML = """
<html>
  <head>
    <title>Course One Title - Example Site</title>
  </head>
  <body>
    <div class="thim-ekit-single-course__buttons">
      <a href="https://www.example.com/courses/course-one/lessons/welcome/">
        <button class="lp-button course-btn-continue">Devam Et</button>
      </a>
    </div>

    <ul class="curriculum-sections">
      <li class="course-section" data-section-id="10">
        <div class="course-section__title">Intro</div>
        <ul class="course-section__items">
          <li class="course-item" data-item-id="101" data-item-order="1" data-item-type="lp_lesson">
            <a href="/courses/course-one/lessons/welcome/" class="course-item__link">
              <div class="course-item-title">Welcome</div>
            </a>
          </li>
          <li class="course-item" data-item-id="102" data-item-order="2" data-item-type="lp_lesson">
            <a href="/courses/course-one/lessons/setup/" class="course-item__link">
              <div class="course-item-title">Setup</div>
            </a>
          </li>
        </ul>
      </li>
      <li class="course-section" data-section-id="20">
        <div class="course-section__title">Advanced</div>
        <ul class="course-section__items">
          <li class="course-item" data-item-id="201" data-item-order="1" data-item-type="lp_lesson">
            <a href="/courses/course-one/lessons/deep-dive/" class="course-item__link">
              <div class="course-item-title">Deep Dive</div>
            </a>
          </li>
        </ul>
      </li>
    </ul>
  </body>
</html>
"""


class FakeDownloader:
    def __init__(self, pages):
        self.pages = pages

    def request_text(self, url):
        return self.pages[url], url


class DiscoveryTests(unittest.TestCase):
    def test_extract_archive_courses_deduplicates_and_keeps_titles(self):
        courses = extract_archive_courses(ARCHIVE_HTML, "https://www.example.com/kurslar/")

        self.assertEqual(2, len(courses))
        self.assertEqual("Course One Title", courses[0]["title"])
        self.assertEqual("course-one", courses[0]["slug"])
        self.assertEqual("Course Two Title", courses[1]["title"])
        self.assertEqual("https://www.example.com/courses/course-two/", courses[1]["url"])

    def test_extract_continue_url_from_button_wrapped_link(self):
        continue_url = extract_continue_url(COURSE_HTML, "https://www.example.com/courses/course-one/")
        self.assertEqual("https://www.example.com/courses/course-one/lessons/welcome/", continue_url)

    def test_discover_and_bootstrap_courses(self):
        downloader = FakeDownloader(
            {
                "https://www.example.com/kurslar/": ARCHIVE_HTML,
                "https://www.example.com/courses/course-one/": COURSE_HTML,
            }
        )

        discovery = discover_courses(downloader, "https://www.example.com")
        self.assertEqual("https://www.example.com/kurslar/", discovery["archive_url"])
        self.assertEqual(2, len(discovery["courses"]))

        course_info = bootstrap_course(downloader, discovery["courses"][0])
        self.assertEqual("Course One Title", course_info["title"])
        self.assertEqual("https://www.example.com/courses/course-one/lessons/welcome/", course_info["continue_url"])
        self.assertEqual(2, course_info["section_count"])
        self.assertEqual(3, course_info["lesson_count"])


if __name__ == "__main__":
    unittest.main()
