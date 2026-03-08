import os

from .common import write_json
from .parsers import flatten_curriculum_sections
from .state import file_nonempty, is_media_classification, lesson_satisfies_run


CORE_STEPS = ["page_fetch", "materials_fetch", "render_html", "render_text", "write_json", "finalize"]


def _step_done(progress, step_name):
    return (progress or {}).get("steps", {}).get(step_name) in {"completed", "skipped"}


def _content_ready(progress):
    return all(_step_done(progress, step_name) for step_name in CORE_STEPS)


def _video_asset_plans(local_entry, require_videos=False, require_transcripts=False):
    lesson_meta = (local_entry or {}).get("lesson_meta") or {}
    lesson_dir = (local_entry or {}).get("lesson_dir")
    videos = lesson_meta.get("videos") or []
    plans = []

    for index, video in enumerate(videos, start=1):
        transcript = video.get("transcript") or {}
        video_file = video.get("file")
        video_path = os.path.join(lesson_dir, video_file) if lesson_dir and video_file else None
        transcript_text_path = os.path.join(lesson_dir, transcript.get("transcript_text_file")) if lesson_dir and transcript.get("transcript_text_file") else None
        transcript_json_path = os.path.join(lesson_dir, transcript.get("transcript_json_file")) if lesson_dir and transcript.get("transcript_json_file") else None

        has_video = bool(video_path and file_nonempty(video_path))
        has_transcript = bool(
            transcript_text_path
            and transcript_json_path
            and file_nonempty(transcript_text_path)
            and file_nonempty(transcript_json_path)
        )

        action = "skip"
        reason = "asset_complete"
        if require_videos and not has_video:
            action = "download_needed"
            reason = "missing_video_file"
        elif require_transcripts and has_video and not has_transcript:
            action = "transcribe_only"
            reason = "missing_transcript_files"
        elif require_transcripts and not has_video:
            action = "download_needed"
            reason = "video_required_before_transcript"

        plans.append(
            {
                "index": index,
                "title": video.get("title") or video_file or f"video-{index:02d}",
                "file": video_file,
                "has_video": has_video,
                "has_transcript": has_transcript,
                "action": action,
                "reason": reason,
            }
        )

    return plans


def build_lesson_plan(remote_lesson, local_entry, require_videos=False, require_transcripts=False):
    if not local_entry:
        return {
            "lesson_url": remote_lesson["url"],
            "title": remote_lesson.get("title") or remote_lesson["url"],
            "section_title": remote_lesson.get("section_title"),
            "classification": "unknown",
            "status": "new",
            "planned_action": "new_lesson",
            "reason": "missing_local_lesson",
            "video_actions": [],
            "actionable": True,
        }

    progress = local_entry.get("progress") or {}
    lesson_meta = local_entry.get("lesson_meta") or {}
    classification = progress.get("classification") or lesson_meta.get("content_type") or "unknown"
    video_actions = _video_asset_plans(local_entry, require_videos=require_videos, require_transcripts=require_transcripts)

    if lesson_satisfies_run(progress, require_videos=require_videos, require_transcripts=require_transcripts):
        planned_action = "skip_complete"
        reason = "lesson_already_complete"
        actionable = False
        status = "complete"
    elif progress.get("status") == "failed":
        planned_action = "retry_failed"
        reason = "previous_run_failed"
        actionable = True
        status = "resume_needed"
    elif not _content_ready(progress):
        planned_action = "fetch_content"
        reason = "content_outputs_incomplete"
        actionable = True
        status = "resume_needed"
    elif any(item["action"] == "download_needed" for item in video_actions):
        planned_action = "download_needed"
        reason = "video_assets_missing"
        actionable = True
        status = "resume_needed"
    elif any(item["action"] == "transcribe_only" for item in video_actions):
        planned_action = "transcribe_only"
        reason = "transcript_assets_missing"
        actionable = True
        status = "resume_needed"
    elif is_media_classification(classification) and (require_videos or require_transcripts):
        planned_action = "repair_metadata"
        reason = "media_state_unclear"
        actionable = True
        status = "recovery_needed"
    else:
        planned_action = "skip_complete"
        reason = "content_complete_and_media_not_required"
        actionable = False
        status = "complete"

    return {
        "lesson_url": remote_lesson["url"],
        "title": remote_lesson.get("title") or progress.get("title") or remote_lesson["url"],
        "section_title": remote_lesson.get("section_title") or progress.get("section_title"),
        "classification": classification,
        "status": status,
        "planned_action": planned_action,
        "reason": reason,
        "video_actions": video_actions,
        "actionable": actionable,
    }


def build_course_plan(course_info, local_record, check, require_videos=False, require_transcripts=False):
    remote_lessons = flatten_curriculum_sections(course_info.get("curriculum_sections") or [])
    local_lessons = (local_record or {}).get("lessons_by_url") or {}
    lesson_plans = [
        build_lesson_plan(
            lesson,
            local_lessons.get(lesson["url"]),
            require_videos=require_videos,
            require_transcripts=require_transcripts,
        )
        for lesson in remote_lessons
    ]
    actionable_lessons = [item for item in lesson_plans if item["actionable"]]

    if check.get("status") == "bootstrap_failed":
        status = "bootstrap_failed"
        reason = "missing_continue_url"
    elif not actionable_lessons:
        status = "complete"
        reason = "all_lessons_satisfied"
    elif any(item["planned_action"] == "repair_metadata" for item in actionable_lessons):
        status = "recovery_needed"
        reason = "some_lessons_need_recovery"
    elif check.get("status") == "new":
        status = "new"
        reason = "course_not_downloaded_yet"
    else:
        status = "resume_needed"
        reason = "course_has_actionable_lessons"

    return {
        "course_title": check.get("course_title") or course_info.get("title"),
        "course_url": check.get("course_url") or course_info.get("resolved_url") or course_info.get("url"),
        "continue_url": check.get("continue_url") or course_info.get("continue_url"),
        "output_dir": check.get("output_dir"),
        "status": status,
        "check_mode": check.get("check_mode", "shallow"),
        "reason": reason,
        "remote": check.get("remote") or {"section_count": course_info.get("section_count", 0), "lesson_count": len(remote_lessons)},
        "local": check.get("local") or {},
        "diff": check.get("diff") or {},
        "validation": check.get("validation") or {},
        "actionable_lesson_count": len(actionable_lessons),
        "lessons": lesson_plans,
    }


def build_site_plan(base_url, archive_url, course_plans):
    counts = {
        "complete": 0,
        "resume_needed": 0,
        "recovery_needed": 0,
        "new": 0,
        "bootstrap_failed": 0,
    }
    for plan in course_plans:
        status = plan.get("status")
        if status in counts:
            counts[status] += 1

    return {
        "base_url": base_url,
        "archive_url": archive_url,
        "course_count": len(course_plans),
        "check_mode": course_plans[0].get("check_mode", "shallow") if course_plans else "shallow",
        "counts": counts,
        "courses": course_plans,
    }


def compact_course_plan(course_plan):
    return {
        "course_title": course_plan.get("course_title"),
        "course_url": course_plan.get("course_url"),
        "continue_url": course_plan.get("continue_url"),
        "output_dir": course_plan.get("output_dir"),
        "status": course_plan.get("status"),
        "check_mode": course_plan.get("check_mode", "shallow"),
        "reason": course_plan.get("reason"),
        "remote": course_plan.get("remote") or {},
        "local": course_plan.get("local") or {},
        "diff": course_plan.get("diff") or {},
        "validation": course_plan.get("validation") or {},
        "actionable_lesson_count": course_plan.get("actionable_lesson_count", 0),
    }


def write_course_plan(output_dir, payload, create_dir=False):
    if not output_dir:
        return None
    if not os.path.isdir(output_dir):
        if not create_dir:
            return None
        os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "course-plan.json")
    write_json(path, payload)
    return path


def write_site_plan(downloads_root, payload):
    write_json(os.path.join(downloads_root, "site-plan.json"), payload)
