import os

from .common import ensure_dir
from .common import read_json, write_json
from .parsers import extract_course_slug, extract_course_url, flatten_curriculum_sections
from .state import infer_progress_from_lesson_meta, lesson_satisfies_run


def _lesson_inventory_from_dir(lesson_dir):
    lesson_meta = read_json(os.path.join(lesson_dir, "lesson.json"), default=None)
    progress = read_json(os.path.join(lesson_dir, "progress.json"), default=None)
    if not lesson_meta and not progress:
        return None
    if lesson_meta and not progress:
        progress = infer_progress_from_lesson_meta(lesson_meta)

    lesson_url = None
    title = None
    classification = None
    if progress:
        lesson_url = progress.get("lesson_url") or lesson_url
        title = progress.get("title") or title
        classification = progress.get("classification") or classification
    if lesson_meta:
        lesson_url = lesson_url or lesson_meta.get("page_url") or ((lesson_meta.get("lesson_meta") or {}).get("url"))
        title = title or lesson_meta.get("title")
        classification = classification or lesson_meta.get("content_type") or "unknown"

    if not lesson_url:
        return None
    return {
        "lesson_url": lesson_url,
        "title": title or lesson_url,
        "classification": classification or "unknown",
        "lesson_meta": lesson_meta,
        "progress": progress,
        "lesson_dir": lesson_dir,
    }


def scan_local_course(output_dir, require_videos=False, require_transcripts=False):
    state = read_json(os.path.join(output_dir, "state.json"), default=None)
    manifest = read_json(os.path.join(output_dir, "manifest.json"), default=None)
    if not state and not manifest:
        return None

    title = ((state or {}).get("course_title") or (manifest or {}).get("course_title") or os.path.basename(output_dir))
    source_url = (
        (state or {}).get("resolved_url")
        or (state or {}).get("start_url")
        or (manifest or {}).get("resolved_url")
        or (manifest or {}).get("start_url")
        or (((manifest or {}).get("lessons") or [{}])[0].get("page_url"))
    )
    course_url = extract_course_url(source_url) if source_url else None

    lessons_by_url = {}
    for root, _dirs, files in os.walk(output_dir):
        if "lesson.json" not in files and "progress.json" not in files:
            continue
        entry = _lesson_inventory_from_dir(root)
        if not entry:
            continue
        lessons_by_url[entry["lesson_url"]] = entry

    completed = 0
    partial = 0
    failed = 0
    for entry in lessons_by_url.values():
        progress = entry.get("progress")
        if progress and lesson_satisfies_run(progress, require_videos=require_videos, require_transcripts=require_transcripts):
            completed += 1
        else:
            partial += 1
        if (progress or {}).get("status") == "failed":
            failed += 1

    return {
        "output_dir": output_dir,
        "title": title,
        "course_url": course_url,
        "course_slug": extract_course_slug(course_url or ""),
        "state": state,
        "manifest": manifest,
        "lessons_by_url": lessons_by_url,
        "lesson_count": len(lessons_by_url),
        "completed_lessons": completed,
        "partial_lessons": partial,
        "failed_lessons": failed,
    }


def _record_score(record):
    return (
        record.get("completed_lessons", 0),
        record.get("lesson_count", 0),
        -(record.get("failed_lessons", 0)),
    )


def index_local_courses(downloads_root, require_videos=False, require_transcripts=False):
    if not os.path.isdir(downloads_root):
        return {"courses": [], "by_course_url": {}, "by_slug": {}}

    records = []
    for name in sorted(os.listdir(downloads_root)):
        output_dir = os.path.join(downloads_root, name)
        if not os.path.isdir(output_dir):
            continue
        record = scan_local_course(
            output_dir,
            require_videos=require_videos,
            require_transcripts=require_transcripts,
        )
        if record:
            records.append(record)

    by_course_url = {}
    by_slug = {}
    for record in records:
        course_url = record.get("course_url")
        slug = record.get("course_slug")
        if course_url and (course_url not in by_course_url or _record_score(record) > _record_score(by_course_url[course_url])):
            by_course_url[course_url] = record
        if slug and (slug not in by_slug or _record_score(record) > _record_score(by_slug[slug])):
            by_slug[slug] = record

    return {"courses": records, "by_course_url": by_course_url, "by_slug": by_slug}


def match_local_course(index, course_info):
    course_url = course_info.get("resolved_url") or course_info.get("url")
    slug = course_info.get("slug") or extract_course_slug(course_url or "")
    return index["by_course_url"].get(course_url) or index["by_slug"].get(slug)


def build_course_check(course_info, local_record, require_videos=False, require_transcripts=False):
    remote_lessons = flatten_curriculum_sections(course_info.get("curriculum_sections") or [])
    remote_by_url = {lesson["url"]: lesson for lesson in remote_lessons}

    missing = []
    partial = []
    completed = []
    failed = []
    local_lessons_by_url = (local_record or {}).get("lessons_by_url") or {}

    for lesson_url in remote_by_url:
        local_entry = local_lessons_by_url.get(lesson_url)
        if not local_entry:
            missing.append(lesson_url)
            continue
        progress = local_entry.get("progress")
        if progress and progress.get("status") == "failed":
            failed.append(lesson_url)
        if progress and lesson_satisfies_run(progress, require_videos=require_videos, require_transcripts=require_transcripts):
            completed.append(lesson_url)
        else:
            partial.append(lesson_url)

    if not local_record:
        status = "new"
    elif not missing and not partial:
        status = "complete"
    else:
        status = "partial"

    return {
        "course_title": course_info.get("title") or (local_record or {}).get("title"),
        "course_url": course_info.get("resolved_url") or course_info.get("url"),
        "continue_url": course_info.get("continue_url"),
        "output_dir": (local_record or {}).get("output_dir"),
        "status": status,
        "remote": {
            "section_count": course_info.get("section_count", 0),
            "lesson_count": len(remote_lessons),
        },
        "local": {
            "lesson_count": len(local_lessons_by_url),
            "completed_lessons": len(completed),
            "partial_lessons": len(partial),
            "failed_lessons": len(failed),
            "missing_lessons": len(missing),
        },
        "diff": {
            "missing_lessons": len(missing),
            "partial_lessons": len(partial),
            "failed_lessons": len(failed),
            "extra_local_lessons": max(0, len(local_lessons_by_url) - len(remote_lessons)),
        },
        "missing_lesson_urls": missing,
        "partial_lesson_urls": partial,
        "failed_lesson_urls": failed,
    }


def write_site_check(downloads_root, payload):
    write_json(os.path.join(downloads_root, "site-check.json"), payload)


def write_course_check(output_dir, payload, create_dir=False):
    if not output_dir:
        return None
    if not os.path.isdir(output_dir):
        if not create_dir:
            return None
        ensure_dir(output_dir)
    path = os.path.join(output_dir, "course-check.json")
    write_json(path, payload)
    return path


def summarize_site_check(checks):
    statuses = {
        "complete": 0,
        "partial": 0,
        "new": 0,
        "bootstrap_failed": 0,
    }
    missing_lessons = 0
    partial_lessons = 0
    failed_lessons = 0

    for check in checks:
        status = check.get("status")
        if status in statuses:
            statuses[status] += 1
        diff = check.get("diff") or {}
        missing_lessons += diff.get("missing_lessons", 0)
        partial_lessons += diff.get("partial_lessons", 0)
        failed_lessons += diff.get("failed_lessons", 0)

    actionable = [
        check
        for check in checks
        if check.get("status") in {"partial", "new", "bootstrap_failed"}
    ]
    actionable.sort(
        key=lambda item: (
            item.get("status") == "bootstrap_failed",
            (item.get("diff") or {}).get("missing_lessons", 0) + (item.get("diff") or {}).get("partial_lessons", 0),
        ),
        reverse=True,
    )

    return {
        "counts": statuses,
        "missing_lessons": missing_lessons,
        "partial_lessons": partial_lessons,
        "failed_lessons": failed_lessons,
        "actionable": actionable,
    }
