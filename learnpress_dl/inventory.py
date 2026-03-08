import os

from .common import ensure_dir, ordered_slug, run_command
from .common import read_json, write_json
from .parsers import extract_course_slug, extract_course_url, flatten_curriculum_sections
from .state import file_nonempty, infer_progress_from_lesson_meta, is_media_classification, lesson_satisfies_run


CHECK_MODE_FAST = "fast"
CHECK_MODE_DEEP = "deep"


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


def _expected_lesson_dir(output_dir, lesson):
    if not output_dir:
        return None
    section_title = lesson.get("section_title") or "Other"
    lesson_title = lesson.get("title") or "lesson"
    section_dir = os.path.join(output_dir, ordered_slug(lesson.get("section_index") or 1, section_title, "section"))
    return os.path.join(section_dir, ordered_slug(lesson.get("lesson_in_section") or 1, lesson_title, "lesson"))


def _build_shallow_local_lessons_by_url(output_dir, remote_lessons):
    lessons_by_url = {}
    for lesson in remote_lessons:
        lesson_dir = _expected_lesson_dir(output_dir, lesson)
        if lesson_dir and os.path.isdir(lesson_dir):
            entry = _lesson_inventory_from_dir(lesson_dir) or {}
            entry["lesson_dir"] = lesson_dir
            lessons_by_url[lesson["url"]] = entry
    return lessons_by_url


def _read_text_length(path):
    if not file_nonempty(path):
        return 0
    with open(path, "r", encoding="utf-8") as handle:
        return len(handle.read().strip())


def _probe_media_duration_seconds(path):
    if not file_nonempty(path):
        return 0.0
    try:
        completed = run_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            timeout=30,
        )
        return float((completed.stdout or "0").strip() or "0")
    except Exception:
        return 0.0


def deep_validate_lesson(local_entry, require_videos=False, require_transcripts=False):
    lesson_meta = (local_entry or {}).get("lesson_meta") or {}
    progress = (local_entry or {}).get("progress") or {}
    lesson_dir = (local_entry or {}).get("lesson_dir")
    classification = progress.get("classification") or lesson_meta.get("content_type") or "unknown"
    issues = []
    metrics = {}

    if not lesson_dir or not os.path.isdir(lesson_dir):
        return {"ok": False, "issues": ["missing_lesson_dir"], "metrics": {}}

    html_path = os.path.join(lesson_dir, "lesson.html")
    text_path = os.path.join(lesson_dir, "lesson.txt")
    json_path = os.path.join(lesson_dir, "lesson.json")

    if not file_nonempty(html_path):
        issues.append("missing_html")
    if not file_nonempty(text_path):
        issues.append("missing_text")
    if not file_nonempty(json_path):
        issues.append("missing_json")

    metrics["html_size_bytes"] = os.path.getsize(html_path) if os.path.exists(html_path) else 0
    metrics["text_length"] = _read_text_length(text_path)
    if file_nonempty(text_path) and metrics["text_length"] < 20:
        issues.append("text_too_short")

    videos = lesson_meta.get("videos") or []
    if is_media_classification(classification):
        metrics["video_count"] = len(videos)
        if require_videos and not videos:
            issues.append("missing_video_metadata")

    for index, video in enumerate(videos, start=1):
        prefix = f"video_{index}"
        video_path = os.path.join(lesson_dir, video.get("file")) if video.get("file") else None
        duration = _probe_media_duration_seconds(video_path) if video_path else 0.0
        metrics[f"{prefix}_duration_seconds"] = duration
        if require_videos and duration <= 0:
            issues.append(f"{prefix}_invalid_duration")

        transcript = video.get("transcript") or {}
        if require_transcripts:
            audio_path = os.path.join(lesson_dir, transcript.get("audio_file")) if transcript.get("audio_file") else None
            text_transcript_path = os.path.join(lesson_dir, transcript.get("transcript_text_file")) if transcript.get("transcript_text_file") else None
            json_transcript_path = os.path.join(lesson_dir, transcript.get("transcript_json_file")) if transcript.get("transcript_json_file") else None
            if not audio_path or not file_nonempty(audio_path):
                issues.append(f"{prefix}_missing_audio")
            if not text_transcript_path or not file_nonempty(text_transcript_path):
                issues.append(f"{prefix}_missing_transcript_text")
            if not json_transcript_path or not file_nonempty(json_transcript_path):
                issues.append(f"{prefix}_missing_transcript_json")

    return {"ok": not issues, "issues": issues, "metrics": metrics}


def _classify_lesson_coverage(remote_lessons, local_lessons_by_url, require_videos=False, require_transcripts=False, check_mode=CHECK_MODE_FAST):
    missing = []
    partial = []
    completed = []
    failed = []
    validations = {}

    for lesson in remote_lessons:
        lesson_url = lesson["url"]
        local_entry = local_lessons_by_url.get(lesson_url)
        if not local_entry:
            missing.append(lesson_url)
            continue
        if check_mode == CHECK_MODE_FAST:
            progress = local_entry.get("progress") or {}
            if progress.get("status") == "failed":
                failed.append(lesson_url)
                partial.append(lesson_url)
                continue
            completed.append(lesson_url)
            continue
        progress = local_entry.get("progress")
        validation = deep_validate_lesson(
            local_entry,
            require_videos=require_videos,
            require_transcripts=require_transcripts,
        )
        validations[lesson_url] = validation
        if progress and progress.get("status") == "failed":
            failed.append(lesson_url)
        if validation["ok"] and progress and lesson_satisfies_run(progress, require_videos=require_videos, require_transcripts=require_transcripts):
            completed.append(lesson_url)
        else:
            partial.append(lesson_url)

    return missing, partial, completed, failed, validations


def build_course_check_from_lessons(
    course_title,
    course_url,
    continue_url,
    output_dir,
    remote_lessons,
    local_lessons_by_url,
    section_count,
    require_videos=False,
    require_transcripts=False,
    force_status=None,
    check_mode=CHECK_MODE_FAST,
):
    if force_status == "new":
        local_lessons_by_url = {}
    elif check_mode == CHECK_MODE_FAST:
        local_lessons_by_url = _build_shallow_local_lessons_by_url(output_dir, remote_lessons)

    missing, partial, completed, failed, validations = _classify_lesson_coverage(
        remote_lessons,
        local_lessons_by_url,
        require_videos=require_videos,
        require_transcripts=require_transcripts,
        check_mode=check_mode,
    )

    if force_status:
        status = force_status
    elif not local_lessons_by_url:
        status = "new"
    elif not missing and not partial:
        status = "complete"
    else:
        status = "partial"

    return {
        "course_title": course_title,
        "course_url": course_url,
        "continue_url": continue_url,
        "output_dir": output_dir,
        "status": status,
        "check_mode": check_mode,
        "remote": {
            "section_count": section_count,
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
        "validation": {
            "checked_lessons": len(validations),
            "invalid_lessons": sum(1 for item in validations.values() if not item.get("ok")),
            "issues": {
                lesson_url: validation.get("issues", [])
                for lesson_url, validation in validations.items()
                if validation.get("issues")
            },
        },
    }


def build_course_check(course_info, local_record, require_videos=False, require_transcripts=False, check_mode=CHECK_MODE_FAST):
    remote_lessons = flatten_curriculum_sections(course_info.get("curriculum_sections") or [])
    local_lessons_by_url = (local_record or {}).get("lessons_by_url") or {}

    return build_course_check_from_lessons(
        course_title=course_info.get("title") or (local_record or {}).get("title"),
        course_url=course_info.get("resolved_url") or course_info.get("url"),
        continue_url=course_info.get("continue_url"),
        output_dir=(local_record or {}).get("output_dir"),
        remote_lessons=remote_lessons,
        local_lessons_by_url=local_lessons_by_url,
        section_count=course_info.get("section_count", 0),
        require_videos=require_videos,
        require_transcripts=require_transcripts,
        force_status="new" if not local_record else None,
        check_mode=check_mode,
    )


def build_bootstrap_failed_check(course_info, check_mode=CHECK_MODE_FAST):
    lesson_count = course_info.get("lesson_count", 0)
    return {
        "course_title": course_info.get("title") or course_info.get("url"),
        "course_url": course_info.get("resolved_url") or course_info.get("url"),
        "continue_url": None,
        "output_dir": None,
        "status": "bootstrap_failed",
        "check_mode": check_mode,
        "remote": {"section_count": course_info.get("section_count", 0), "lesson_count": lesson_count},
        "local": {"lesson_count": 0, "completed_lessons": 0, "partial_lessons": 0, "failed_lessons": 0, "missing_lessons": lesson_count},
        "diff": {"missing_lessons": lesson_count, "partial_lessons": 0, "failed_lessons": 0, "extra_local_lessons": 0},
        "missing_lesson_urls": [],
        "partial_lesson_urls": [],
        "failed_lesson_urls": [],
        "validation": {"checked_lessons": 0, "invalid_lessons": 0, "issues": {}},
    }


def compact_course_check(check):
    return {
        "course_title": check.get("course_title"),
        "course_url": check.get("course_url"),
        "continue_url": check.get("continue_url"),
        "output_dir": check.get("output_dir"),
        "status": check.get("status"),
        "check_mode": check.get("check_mode", CHECK_MODE_FAST),
        "remote": check.get("remote") or {},
        "local": check.get("local") or {},
        "diff": check.get("diff") or {},
        "validation": check.get("validation") or {},
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
    invalid_lessons = 0

    for check in checks:
        status = check.get("status")
        if status in statuses:
            statuses[status] += 1
        diff = check.get("diff") or {}
        missing_lessons += diff.get("missing_lessons", 0)
        partial_lessons += diff.get("partial_lessons", 0)
        failed_lessons += diff.get("failed_lessons", 0)
        validation = check.get("validation") or {}
        invalid_lessons += validation.get("invalid_lessons", 0)

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
        "invalid_lessons": invalid_lessons,
        "actionable": actionable,
    }
