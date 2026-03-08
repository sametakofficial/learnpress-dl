import os
from datetime import datetime, timezone

from .common import read_json, write_json


STATE_FILENAME = "state.json"
PROGRESS_FILENAME = "progress.json"
LESSON_JSON_FILENAME = "lesson.json"
LOCK_FILENAME = "download.lock"

STEP_NAMES = [
    "page_fetch",
    "materials_fetch",
    "video_download",
    "audio_extract",
    "transcript",
    "render_html",
    "render_text",
    "write_json",
    "finalize",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def course_state_path(output_dir):
    return os.path.join(output_dir, STATE_FILENAME)


def course_lock_path(output_dir):
    return os.path.join(output_dir, LOCK_FILENAME)


def lesson_progress_path(lesson_dir):
    return os.path.join(lesson_dir, PROGRESS_FILENAME)


def lesson_json_path(lesson_dir):
    return os.path.join(lesson_dir, LESSON_JSON_FILENAME)


def file_nonempty(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


def process_exists(pid):
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_course_lock(output_dir, start_url):
    lock_path = course_lock_path(output_dir)
    existing = read_json(lock_path, default=None)
    current_pid = os.getpid()

    if existing:
        existing_pid = existing.get("pid")
        if existing_pid == current_pid:
            return lock_path
        if process_exists(existing_pid):
            raise RuntimeError(
                f"This output directory is already in use by another process (pid={existing_pid})"
            )

    write_json(
        lock_path,
        {
            "pid": current_pid,
            "start_url": start_url,
            "created_at": now_iso(),
        },
    )
    return lock_path


def release_course_lock(output_dir):
    lock_path = course_lock_path(output_dir)
    if not os.path.exists(lock_path):
        return
    existing = read_json(lock_path, default=None) or {}
    if existing.get("pid") == os.getpid():
        os.remove(lock_path)


def load_course_state(output_dir):
    return read_json(course_state_path(output_dir), default=None)


def save_course_state(output_dir, state):
    state["updated_at"] = now_iso()
    write_json(course_state_path(output_dir), state)


def load_progress(lesson_dir):
    return read_json(lesson_progress_path(lesson_dir), default=None)


def save_progress(lesson_dir, progress):
    progress["updated_at"] = now_iso()
    write_json(lesson_progress_path(lesson_dir), progress)


def load_existing_lesson_meta(lesson_dir):
    return read_json(lesson_json_path(lesson_dir), default=None)


def build_initial_course_state(course_title, start_url, resolved_url, mode, sections, lesson_count):
    timestamp = now_iso()
    return {
        "course_title": course_title,
        "start_url": start_url,
        "resolved_url": resolved_url,
        "mode": mode,
        "schema_version": 2,
        "status": "in_progress",
        "created_at": timestamp,
        "updated_at": timestamp,
        "section_count": len(sections),
        "lesson_count": lesson_count,
        "recovered_lessons": 0,
        "completed_lessons": 0,
        "failed_lessons": 0,
        "classified": {
            "text": 0,
            "video": 0,
            "text+video": 0,
            "other": 0,
            "unknown": 0,
        },
        "sections": sections,
    }


def refresh_course_state(state, course_title, start_url, resolved_url, mode, sections, lesson_count):
    state["course_title"] = course_title
    state["start_url"] = start_url
    state["resolved_url"] = resolved_url
    state["mode"] = mode
    state["section_count"] = len(sections)
    state["lesson_count"] = lesson_count
    state["sections"] = sections
    if "schema_version" not in state:
        state["schema_version"] = 2
    return state


def build_initial_progress(lesson, classification="unknown", source="fresh"):
    timestamp = now_iso()
    return {
        "lesson_url": lesson["url"],
        "title": lesson.get("title") or lesson["url"],
        "classification": classification,
        "source": source,
        "status": "pending",
        "steps": {step: "pending" for step in STEP_NAMES},
        "retries": {},
        "last_error": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def set_step(progress, step_name, status, error=None):
    progress["steps"][step_name] = status
    if error:
        progress["last_error"] = error
    return progress


def set_classification(progress, classification):
    progress["classification"] = classification
    return progress


def set_status(progress, status, error=None):
    progress["status"] = status
    progress["last_error"] = error
    return progress


def classify_from_parser(parser):
    has_text = bool(getattr(parser, "content_html", ""))
    has_video = bool(getattr(parser, "iframes", []))
    if has_text and has_video:
        return "text+video"
    if has_text:
        return "text"
    if has_video:
        return "video"
    return "unknown"


def is_media_classification(classification):
    return classification in {"video", "text+video"}


def infer_progress_from_lesson_meta(lesson_meta):
    progress = build_initial_progress(lesson_meta.get("lesson_meta") or lesson_meta, lesson_meta.get("content_type") or "unknown", source="recovered")
    progress["title"] = lesson_meta.get("title") or progress["title"]

    progress["steps"]["page_fetch"] = "completed"
    progress["steps"]["materials_fetch"] = "completed"
    progress["steps"]["render_html"] = "completed"
    progress["steps"]["render_text"] = "completed"
    progress["steps"]["write_json"] = "completed"
    progress["steps"]["finalize"] = "completed"

    classification = lesson_meta.get("content_type") or "unknown"
    if is_media_classification(classification):
        videos = lesson_meta.get("videos", [])
        if videos:
            progress["steps"]["video_download"] = "completed"
            transcripts_ready = True
            audio_ready = True
            for video in videos:
                transcript = video.get("transcript") or {}
                if not transcript.get("audio_file"):
                    audio_ready = False
                if not transcript.get("transcript_text_file") or not transcript.get("transcript_json_file"):
                    transcripts_ready = False
            progress["steps"]["audio_extract"] = "completed" if audio_ready else "pending"
            progress["steps"]["transcript"] = "completed" if transcripts_ready else "pending"
        else:
            progress["steps"]["video_download"] = "pending"
            progress["steps"]["audio_extract"] = "pending"
            progress["steps"]["transcript"] = "pending"
    else:
        progress["steps"]["video_download"] = "skipped"
        progress["steps"]["audio_extract"] = "skipped"
        progress["steps"]["transcript"] = "skipped"

    progress["status"] = "completed"
    return progress


def lesson_satisfies_run(progress, require_videos=False, require_transcripts=False):
    if not progress:
        return False

    required_steps = ["page_fetch", "materials_fetch", "render_html", "render_text", "write_json", "finalize"]
    if require_videos and is_media_classification(progress.get("classification", "unknown")):
        required_steps.append("video_download")
    if require_transcripts and is_media_classification(progress.get("classification", "unknown")):
        required_steps.extend(["audio_extract", "transcript"])

    return all(progress["steps"].get(step) in {"completed", "skipped"} for step in required_steps)


def summarize_progress_counts(progress_items):
    completed = 0
    failed = 0
    for progress in progress_items:
        if progress.get("status") == "completed":
            completed += 1
        elif progress.get("status") == "failed":
            failed += 1
    return completed, failed


def recover_legacy_manifest(output_dir, state, require_videos=False, require_transcripts=False):
    manifest_path = os.path.join(output_dir, "manifest.json")
    manifest = read_json(manifest_path, default=None)
    if not manifest:
        return state, {}

    recovered = {}
    recovered_count = 0
    for lesson_meta in manifest.get("lessons", []):
        lesson_rel = (lesson_meta.get("directories") or {}).get("lesson")
        if not lesson_rel:
            continue
        lesson_dir = os.path.join(output_dir, lesson_rel)
        if not file_nonempty(os.path.join(lesson_dir, "lesson.html")):
            continue
        if not file_nonempty(os.path.join(lesson_dir, "lesson.txt")):
            continue
        if not file_nonempty(os.path.join(lesson_dir, "lesson.json")):
            continue

        progress = infer_progress_from_lesson_meta(lesson_meta)
        save_progress(lesson_dir, progress)
        recovered[lesson_meta["page_url"]] = {
            "lesson_meta": lesson_meta,
            "progress": progress,
            "lesson_dir": lesson_dir,
            "satisfies_run": lesson_satisfies_run(progress, require_videos=require_videos, require_transcripts=require_transcripts),
        }
        recovered_count += 1

    state["recovered_lessons"] = recovered_count
    completed, failed = summarize_progress_counts(item["progress"] for item in recovered.values())
    state["completed_lessons"] = completed
    state["failed_lessons"] = failed
    save_course_state(output_dir, state)
    return state, recovered
