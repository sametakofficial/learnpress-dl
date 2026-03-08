import html
import json
import re
import urllib.parse
from html.parser import HTMLParser

from .common import VOID_TAGS, attr_map, class_list, strip_tags


def normalize_page_url(url):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or "/"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def is_course_url(url):
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) >= 2 and parts[0] == "courses" and "lessons" not in parts


def is_lesson_url(url):
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return len(parts) >= 4 and parts[0] == "courses" and parts[2] == "lessons"


def extract_course_slug(url):
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "courses":
        return parts[1]
    return ""


def extract_course_url(url):
    parsed = urllib.parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "courses":
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, f"/courses/{parts[1]}/", "", "", ""))
    return normalize_page_url(url)


def extract_course_title(html_text):
    match = re.search(r"<title>(.*?)</title>", html_text, re.S | re.I)
    if not match:
        return "course"
    title = strip_tags(match.group(1))
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    return title or "course"


class CourseArchiveParser(HTMLParser):
    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.links = []
        self.current_href = None
        self.current_text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        absolute_url = normalize_page_url(urllib.parse.urljoin(self.page_url, html.unescape(href)))
        if not is_course_url(absolute_url):
            return
        self.current_href = absolute_url
        self.current_text_parts = []

    def handle_data(self, data):
        if self.current_href:
            self.current_text_parts.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or not self.current_href:
            return
        text = " ".join("".join(self.current_text_parts).split())
        self.links.append({"url": self.current_href, "title": text})
        self.current_href = None
        self.current_text_parts = []


class CourseEntryLinkParser(HTMLParser):
    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.entry_url = None

    def handle_starttag(self, tag, attrs):
        if tag != "a" or self.entry_url:
            return
        attrs_dict = attr_map(attrs)
        classes = class_list(attrs)
        href = attrs_dict.get("href")
        if not href or "course-item__link" not in classes:
            return
        absolute_url = normalize_page_url(urllib.parse.urljoin(self.page_url, html.unescape(href)))
        if is_lesson_url(absolute_url):
            self.entry_url = absolute_url


def extract_archive_courses(html_text, page_url):
    parser = CourseArchiveParser(page_url)
    parser.feed(html_text)
    parser.close()

    courses_by_url = {}
    ordered_urls = []
    for link in parser.links:
        url = link["url"]
        title = link.get("title") or ""
        if url not in courses_by_url:
            courses_by_url[url] = {
                "title": title,
                "url": url,
                "slug": extract_course_slug(url),
            }
            ordered_urls.append(url)
        elif len(title) > len(courses_by_url[url].get("title") or ""):
            courses_by_url[url]["title"] = title

    return [courses_by_url[url] for url in ordered_urls]


def extract_course_entry_url(html_text, page_url):
    parser = CourseEntryLinkParser(page_url)
    parser.feed(html_text)
    parser.close()
    return parser.entry_url


def extract_curriculum_sections(html_text, page_url):
    section_pattern = re.compile(
        r'<li class="course-section[^\"]*"[^>]*data-section-id="(?P<section_id>\d+)"[^>]*>'
        r'.*?<div class="course-section__title">(?P<section_title>.*?)</div>'
        r'.*?<ul class="course-section__items">(?P<section_items>.*?)</ul>\s*</li>',
        re.S,
    )
    item_pattern = re.compile(
        r'<li class="course-item[^\"]*"[^>]*data-item-id="(?P<item_id>\d+)"[^>]*'
        r'data-item-order="(?P<item_order>\d+)"[^>]*data-item-type="(?P<item_type>[^"]+)"[^>]*>'
        r'.*?<a href="(?P<url>[^"]+)" class="course-item__link">'
        r'.*?<div class="course-item-title">(?P<title>.*?)</div>',
        re.S,
    )

    sections = []
    lesson_index = 1

    for section_index, match in enumerate(section_pattern.finditer(html_text), start=1):
        section_title = strip_tags(match.group("section_title"))
        section = {
            "section_id": match.group("section_id"),
            "section_index": section_index,
            "section_title": section_title,
            "lessons": [],
        }
        for lesson_in_section, item_match in enumerate(
            item_pattern.finditer(match.group("section_items")),
            start=1,
        ):
            lesson = {
                "global_index": lesson_index,
                "section_index": section_index,
                "section_id": section["section_id"],
                "section_title": section_title,
                "lesson_in_section": lesson_in_section,
                "item_id": item_match.group("item_id"),
                "item_order": item_match.group("item_order"),
                "item_type": item_match.group("item_type"),
                "url": urllib.parse.urljoin(page_url, html.unescape(item_match.group("url"))),
                "title": strip_tags(item_match.group("title")),
            }
            section["lessons"].append(lesson)
            lesson_index += 1
        sections.append(section)

    return sections


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.current_href = href
                self.current_text = []

    def handle_data(self, data):
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current_href:
            text = " ".join("".join(self.current_text).split())
            self.links.append({"href": self.current_href, "text": text})
            self.current_href = None
            self.current_text = []


class LessonPageParser(HTMLParser):
    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.lesson_title = ""
        self.title_capture = False
        self.title_parts = []
        self.course_items = []
        self.current_course_item_meta = None
        self.current_item_capture = False
        self.current_item_title_parts = []
        self.content_depth = 0
        self.content_html_parts = []
        self.iframes = []
        self.notice_capture = False
        self.notice_parts = []
        self.notices = []
        self.prev_url = None
        self.next_url = None
        self.lp_target_data = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = attr_map(attrs)
        classes = class_list(attrs)

        if tag == "iframe":
            self.iframes.append({"src": attrs_dict.get("src", ""), "title": attrs_dict.get("title", "")})

        if self.content_depth:
            self.content_html_parts.append(self.get_starttag_text())
            if tag not in VOID_TAGS:
                self.content_depth += 1
            return

        if tag == "li" and "course-item" in classes:
            self.current_course_item_meta = {
                "item_id": attrs_dict.get("data-item-id"),
                "item_order": attrs_dict.get("data-item-order"),
                "item_type": attrs_dict.get("data-item-type"),
                "url": None,
                "title": "",
            }

        if tag == "a" and "course-item__link" in classes and self.current_course_item_meta:
            href = attrs_dict.get("href")
            if href:
                self.current_course_item_meta["url"] = urllib.parse.urljoin(self.page_url, href)

        if tag == "div" and "course-item-title" in classes and self.current_course_item_meta:
            self.current_item_capture = True
            self.current_item_title_parts = []

        if tag == "h1" and {"course-item-title", "lesson-title"}.issubset(classes):
            self.title_capture = True
            self.title_parts = []

        if tag == "div" and {"content-item-description", "lesson-description"}.issubset(classes):
            self.content_depth = 1

        if tag == "div" and "learn-press-message" in classes and "notice" in classes:
            self.notice_capture = True
            self.notice_parts = []

        if tag == "a":
            rel = attrs_dict.get("rel", "")
            href = attrs_dict.get("href")
            if href and "prev" in rel.split():
                self.prev_url = urllib.parse.urljoin(self.page_url, href)
            if href and "next" in rel.split():
                self.next_url = urllib.parse.urljoin(self.page_url, href)

        if tag == "div" and "lp-target" in classes and attrs_dict.get("data-send"):
            raw_data = html.unescape(attrs_dict["data-send"])
            try:
                self.lp_target_data = json.loads(raw_data)
            except json.JSONDecodeError:
                self.lp_target_data = None

    def handle_endtag(self, tag):
        if self.content_depth:
            self.content_depth -= 1
            if self.content_depth:
                self.content_html_parts.append(f"</{tag}>")
            return

        if tag == "h1" and self.title_capture:
            self.lesson_title = " ".join("".join(self.title_parts).split())
            self.title_capture = False

        if tag == "div" and self.notice_capture:
            notice_text = " ".join("".join(self.notice_parts).split())
            if notice_text:
                self.notices.append(notice_text)
            self.notice_capture = False
            self.notice_parts = []

        if tag == "div" and self.current_item_capture and self.current_course_item_meta:
            self.current_course_item_meta["title"] = " ".join("".join(self.current_item_title_parts).split())
            self.current_item_capture = False
            self.current_item_title_parts = []

        if tag == "li" and self.current_course_item_meta:
            if self.current_course_item_meta.get("url"):
                self.course_items.append(self.current_course_item_meta)
            self.current_course_item_meta = None

    def handle_startendtag(self, tag, attrs):
        attrs_dict = attr_map(attrs)
        if tag == "iframe":
            self.iframes.append({"src": attrs_dict.get("src", ""), "title": attrs_dict.get("title", "")})
        if self.content_depth:
            self.content_html_parts.append(self.get_starttag_text())

    def handle_data(self, data):
        if self.content_depth:
            self.content_html_parts.append(data)
            return
        if self.title_capture:
            self.title_parts.append(data)
        if self.current_item_capture:
            self.current_item_title_parts.append(data)
        if self.notice_capture:
            self.notice_parts.append(data)

    def handle_entityref(self, name):
        text = f"&{name};"
        if self.content_depth:
            self.content_html_parts.append(text)
        elif self.title_capture:
            self.title_parts.append(html.unescape(text))
        elif self.current_item_capture:
            self.current_item_title_parts.append(html.unescape(text))

    def handle_charref(self, name):
        text = f"&#{name};"
        if self.content_depth:
            self.content_html_parts.append(text)
        elif self.title_capture:
            self.title_parts.append(html.unescape(text))
        elif self.current_item_capture:
            self.current_item_title_parts.append(html.unescape(text))

    @property
    def content_html(self):
        return "".join(self.content_html_parts).strip()


def extract_lp_data(html_text):
    match = re.search(r"var\s+lpData\s*=\s*(\{.*?\});", html_text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def parse_page(url, html_text):
    parser = LessonPageParser(url)
    parser.feed(html_text)
    parser.close()
    return parser


def unique_urls(items):
    seen = set()
    result = []
    for item in items:
        url = item.get("url")
        if url and url not in seen:
            seen.add(url)
            result.append(item)
    return result


def flatten_curriculum_sections(sections):
    lessons = []
    for section in sections:
        lessons.extend(section.get("lessons", []))
    return unique_urls(lessons)


def collect_via_curriculum(parser, html_text=None, page_url=None):
    if html_text and page_url:
        return flatten_curriculum_sections(extract_curriculum_sections(html_text, page_url))
    return unique_urls(parser.course_items)


def collect_via_next(start_url, downloader, limit=None):
    results = []
    visited = set()
    current_url = start_url
    order = 1

    while current_url and current_url not in visited:
        html_text, final_url = downloader.request_text(current_url)
        parser = parse_page(final_url, html_text)
        visited.add(final_url)
        results.append(
            {
                "item_id": None,
                "item_order": str(order),
                "item_type": "lp_lesson",
                "url": final_url,
                "title": parser.lesson_title or f"Lesson {order}",
            }
        )
        current_url = parser.next_url
        order += 1
        if limit and len(results) >= limit:
            break

    return results


def extract_materials(downloader, lp_data, parser):
    if not parser.lp_target_data:
        return {"html": "", "links": []}

    endpoint = lp_data.get("lp_rest_load_ajax")
    nonce = lp_data.get("nonce")
    if not endpoint or not nonce:
        return {"html": "", "links": []}

    payload = json.dumps(parser.lp_target_data)
    response = downloader.request_json(
        endpoint,
        method="POST",
        headers={"Content-Type": "application/json", "X-WP-Nonce": nonce},
        data=payload,
    )
    content = response.get("data", {}).get("content", "") if isinstance(response, dict) else ""
    collector = LinkCollector()
    collector.feed(content)
    collector.close()
    return {"html": content, "links": collector.links}


def detect_access_problem(html_text, parser):
    if parser.content_html or parser.iframes:
        return None
    if "This content is protected" in html_text:
        return (
            "Sayfa korumali gorunuyor. Cookie gecersiz olabilir ya da kursa erisim yok. "
            "Tarayicidan guncel cookie ile tekrar dene."
        )
    return "Ders icerigi bulunamadi. HTML yapisi degismis olabilir."
