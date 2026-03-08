from .common import build_courses_archive_url, is_retryable_error, retry_call
from .parsers import (
    extract_archive_courses,
    extract_continue_url,
    extract_course_title,
    extract_curriculum_sections,
)


def discover_courses(downloader, base_url, retries=3, retry_delay=2.0):
    archive_url = build_courses_archive_url(base_url)
    html_text, final_url = retry_call(
        lambda: downloader.request_text(archive_url),
        retries=max(1, retries),
        base_delay=max(retry_delay, 0.1),
        should_retry=is_retryable_error,
    )
    return {
        "archive_url": final_url,
        "courses": extract_archive_courses(html_text, final_url),
    }


def bootstrap_course(downloader, course, retries=3, retry_delay=2.0):
    course_url = course["url"] if isinstance(course, dict) else course
    html_text, final_url = retry_call(
        lambda: downloader.request_text(course_url),
        retries=max(1, retries),
        base_delay=max(retry_delay, 0.1),
        should_retry=is_retryable_error,
    )
    curriculum_sections = extract_curriculum_sections(html_text, final_url)
    continue_url = extract_continue_url(html_text, final_url)
    return {
        "title": (course.get("title") if isinstance(course, dict) else "") or extract_course_title(html_text),
        "url": course_url,
        "resolved_url": final_url,
        "continue_url": continue_url,
        "section_count": len(curriculum_sections),
        "lesson_count": sum(len(section.get("lessons", [])) for section in curriculum_sections),
        "curriculum_sections": curriculum_sections,
        "slug": (course.get("slug") if isinstance(course, dict) else None),
    }
