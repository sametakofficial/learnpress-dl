import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from .common import (
    Downloader,
    derive_download_root,
    ensure_dir,
    is_retryable_error,
    log,
    ordered_slug,
    retry_call,
    resolve_groq_api_key,
    write_text,
)
from .inventory import build_course_check_from_lessons, write_course_check
from .media import download_videos_for_lesson, maybe_transcribe_video
from .parsers import (
    collect_via_next,
    detect_access_problem,
    extract_course_title,
    extract_curriculum_sections,
    extract_lp_data,
    extract_materials,
    extract_course_url,
    flatten_curriculum_sections,
    parse_page,
)
from .planner import build_course_plan, write_course_plan
from .render import get_lesson_dirs, save_lesson
from .state import (
    acquire_course_lock,
    build_initial_course_state,
    build_initial_progress,
    classify_from_parser,
    infer_progress_from_lesson_meta,
    is_media_classification,
    lesson_satisfies_run,
    load_course_state,
    load_existing_lesson_meta,
    load_progress,
    recover_legacy_manifest,
    refresh_course_state,
    release_course_lock,
    save_course_state,
    save_progress,
    set_classification,
    set_status,
    set_step,
    summarize_progress_counts,
)


def build_downloader_from_args(args):
    return Downloader(
        cookie_file=args.cookie_file,
        cookie_header=args.cookie_header,
        delay=max(args.delay, 0.0),
        request_timeout=max(args.request_timeout, 1.0),
    )


def print_course_check_summary(index, total, check):
    validation = check.get("validation") or {}
    print(
        f"[{index}/{total}] {check['course_title']} [{check['status']}]\n"
        f"  check depth: {check.get('check_mode', 'fast')}\n"
        f"  local dir: {check.get('output_dir') or '-'}\n"
        f"  remote lessons: {check['remote']['lesson_count']}\n"
        f"  local completed: {check['local']['completed_lessons']}\n"
        f"  local partial: {check['local']['partial_lessons']}\n"
        f"  local missing: {check['local']['missing_lessons']}\n"
        f"  validation invalid: {validation.get('invalid_lessons', 0)}",
        flush=True,
    )


def print_course_plan_summary(course_plan):
    print(
        f"Plan\n"
        f"  status: {course_plan['status']}\n"
        f"  reason: {course_plan['reason']}\n"
        f"  actionable lessons: {course_plan['actionable_lesson_count']}",
        flush=True,
    )


def build_section_rows(curriculum_sections):
    return [
        {
            "section_index": section["section_index"],
            "section_title": section["section_title"],
            "lesson_count": len(section["lessons"]),
            "directory": ordered_slug(section["section_index"], section["section_title"], "section"),
        }
        for section in curriculum_sections
    ]


def filter_sections_to_lessons(curriculum_sections, lesson_items):
    allowed_urls = {lesson["url"] for lesson in lesson_items}
    filtered = []
    for section in curriculum_sections:
        lessons = [lesson for lesson in section.get("lessons", []) if lesson.get("url") in allowed_urls]
        if lessons:
            section_copy = dict(section)
            section_copy["lessons"] = lessons
            filtered.append(section_copy)
    return filtered


def ensure_state(output_dir, course_title, start_url, resolved_url, mode, sections, lesson_count, require_videos, require_transcripts):
    state = load_course_state(output_dir)
    recovered = {}
    if state is None:
        state = build_initial_course_state(course_title, start_url, resolved_url, mode, sections, lesson_count)
        state, recovered = recover_legacy_manifest(
            output_dir,
            state,
            require_videos=require_videos,
            require_transcripts=require_transcripts,
        )
        if not recovered:
            save_course_state(output_dir, state)
    else:
        state = refresh_course_state(state, course_title, start_url, resolved_url, mode, sections, lesson_count)
        save_course_state(output_dir, state)
    return state, recovered


def build_existing_entries(output_dir, lesson_items, recovered_entries):
    existing = dict(recovered_entries)
    for lesson in lesson_items:
        if lesson["url"] in existing:
            continue
        _, _, lesson_dir = get_lesson_dirs(output_dir, lesson, lesson.get("title") or "lesson")
        lesson_meta = load_existing_lesson_meta(lesson_dir)
        progress = load_progress(lesson_dir)
        if lesson_meta and not progress:
            progress = infer_progress_from_lesson_meta(lesson_meta)
            save_progress(lesson_dir, progress)
        if lesson_meta or progress:
            existing[lesson["url"]] = {
                "lesson_meta": lesson_meta,
                "progress": progress,
                "lesson_dir": lesson_dir,
            }
    return existing


def sync_course_tree(ui, course_key, course_title, curriculum_sections, lesson_items, existing_entries, require_videos, require_transcripts):
    if not ui:
        return
    ui.register_course(course_key, course_title, status="running", sections=curriculum_sections, lessons=lesson_items)
    for lesson in lesson_items:
        existing = existing_entries.get(lesson["url"]) or {}
        progress = existing.get("progress")
        status = "pending"
        if progress and lesson_satisfies_run(progress, require_videos=require_videos, require_transcripts=require_transcripts):
            status = "finished"
        elif (progress or {}).get("status") == "failed":
            status = "failed"
        ui.set_lesson_status(
            course_key,
            lesson["url"],
            status,
            title=lesson.get("title"),
            section_title=lesson.get("section_title"),
        )


def discover_lessons(
    args,
    lesson_items,
    downloader,
    first_url,
    first_html,
    first_final_url,
    first_parser,
    existing_entries,
    require_videos,
    require_transcripts,
    progress_ui=None,
    course_key=None,
):
    text_contexts = []
    media_contexts = []
    other_contexts = []
    saved_by_url = {}
    progress_by_url = {}
    classification_counts = {"text": 0, "video": 0, "text+video": 0, "other": 0, "unknown": 0}
    total = len(lesson_items)

    for index, lesson in enumerate(lesson_items, start=1):
        existing = existing_entries.get(lesson["url"]) or {}
        existing_meta = existing.get("lesson_meta")
        existing_progress = existing.get("progress")

        if existing_progress and lesson_satisfies_run(existing_progress, require_videos=require_videos, require_transcripts=require_transcripts):
            if existing_meta:
                saved_by_url[lesson["url"]] = existing_meta
            progress_by_url[lesson["url"]] = existing_progress
            classification = existing_progress.get("classification") or (existing_meta or {}).get("content_type") or "unknown"
            classification_counts[classification if classification in classification_counts else "unknown"] += 1
            if progress_ui and course_key:
                progress_ui.set_lesson_status(course_key, lesson["url"], "finished", title=lesson.get("title"), section_title=lesson.get("section_title"))
            log(f"[check] {index}/{total} skipping satisfied lesson: {lesson.get('title') or lesson['url']}", level="SUCCESS")
            continue

        title_hint = lesson.get("title") or f"lesson-{index:03d}"
        _, _, initial_lesson_dir = get_lesson_dirs(args.output_dir, lesson, title_hint)
        progress = existing_progress or build_initial_progress(lesson)
        set_status(progress, "in_progress", error=None)
        save_progress(initial_lesson_dir, progress)
        if progress_ui and course_key:
            progress_ui.set_lesson_status(course_key, lesson["url"], "fetching-content", title=lesson.get("title"), section_title=lesson.get("section_title"))

        target_url = lesson["url"]
        log(f"[discover] {index}/{total} fetching lesson metadata: {lesson.get('title') or target_url}", level="DEBUG")
        try:
            if target_url == first_url:
                html_text = first_html
                final_url = first_final_url
                page_parser = first_parser
            else:
                html_text, final_url = retry_call(
                    lambda: downloader.request_text(target_url),
                    retries=max(1, args.retry_count),
                    base_delay=max(args.retry_delay, 0.1),
                    should_retry=is_retryable_error,
                    on_retry=lambda attempt, retry_total, exc, delay: log(
                        f"[http] lesson retry {attempt}/{retry_total} for {target_url}: {exc} ({delay:.1f}s)",
                        level="WARNING",
                    ),
                )
                page_parser = parse_page(final_url, html_text)
        except RuntimeError as exc:
            set_step(progress, "page_fetch", "failed", error=str(exc))
            set_status(progress, "failed", error=str(exc))
            save_progress(initial_lesson_dir, progress)
            progress_by_url[lesson["url"]] = progress
            if progress_ui and course_key:
                progress_ui.set_lesson_status(course_key, lesson["url"], "failed", title=lesson.get("title"), section_title=lesson.get("section_title"))
            log(f"[discover] {index}/{total} failed to fetch lesson page: {exc}", level="WARNING")
            continue

        problem = detect_access_problem(html_text, page_parser)
        if problem:
            set_step(progress, "page_fetch", "failed", error=problem)
            set_status(progress, "failed", error=problem)
            save_progress(initial_lesson_dir, progress)
            progress_by_url[lesson["url"]] = progress
            if progress_ui and course_key:
                progress_ui.set_lesson_status(course_key, lesson["url"], "failed", title=lesson.get("title"), section_title=lesson.get("section_title"))
            log(f"[discover] {index}/{total} skipped lesson due to access problem: {problem}", level="WARNING")
            continue

        classification = classify_from_parser(page_parser)
        lesson_title = page_parser.lesson_title or lesson.get("title") or title_hint
        _, _, lesson_dir = get_lesson_dirs(args.output_dir, lesson, lesson_title)

        set_classification(progress, classification)
        set_step(progress, "page_fetch", "completed")
        progress_by_url[lesson["url"]] = progress
        save_progress(lesson_dir, progress)
        if progress_ui and course_key:
            progress_ui.set_lesson_status(course_key, lesson["url"], "pending", title=lesson_title, section_title=lesson.get("section_title"))

        context = {
            "index": index,
            "total": total,
            "lesson": lesson,
            "html_text": html_text,
            "final_url": final_url,
            "page_parser": page_parser,
            "page_lp_data": extract_lp_data(html_text),
            "lesson_dir": lesson_dir,
            "lesson_title": lesson_title,
            "progress": progress,
            "classification": classification,
        }
        classification_counts[classification if classification in classification_counts else "unknown"] += 1

        if classification == "text":
            text_contexts.append(context)
        elif classification in {"video", "text+video"}:
            media_contexts.append(context)
        else:
            other_contexts.append(context)

    return text_contexts, media_contexts, other_contexts, saved_by_url, progress_by_url, classification_counts


def process_lesson_context(context, args, groq_api_key, require_videos, require_transcripts, progress_ui=None, course_key=None):
    downloader = build_downloader_from_args(args)
    progress = context["progress"]
    lesson = context["lesson"]
    page_parser = context["page_parser"]
    final_url = context["final_url"]
    lesson_dir = context["lesson_dir"]
    page_lp_data = context["page_lp_data"]
    classification = context["classification"]

    try:
        if progress_ui and course_key:
            progress_ui.set_lesson_status(course_key, lesson["url"], "fetching-materials", title=context["lesson_title"], section_title=lesson.get("section_title"))
        materials = retry_call(
            lambda: extract_materials(downloader, page_lp_data, page_parser),
            retries=max(1, args.retry_count),
            base_delay=max(args.retry_delay, 0.1),
            should_retry=is_retryable_error,
                    on_retry=lambda attempt, retry_total, exc, delay: log(
                f"[http] materials retry {attempt}/{retry_total} for {context['final_url']}: {exc} ({delay:.1f}s)",
                level="WARNING",
            ),
        )
    except RuntimeError as exc:
        log(f"[materials] failed to fetch lesson materials: {exc}", level="WARNING")
        materials = {"html": "", "links": []}
    set_step(progress, "materials_fetch", "completed")
    save_progress(lesson_dir, progress)

    video_files = []
    if require_videos and is_media_classification(classification):
        log(f"[media] {context['index']}/{context['total']} found {len(page_parser.iframes)} video source(s)")
        try:
            if progress_ui and course_key:
                progress_ui.set_lesson_status(course_key, lesson["url"], "fetching-video", title=context["lesson_title"], section_title=lesson.get("section_title"))
            video_files = download_videos_for_lesson(
                downloader,
                lesson_dir,
                final_url,
                page_parser,
                max(args.video_timeout, 1.0),
                retries=max(1, args.retry_count),
                retry_delay=max(args.retry_delay, 0.1),
            )
            set_step(progress, "video_download", "completed")
            log(f"[media] downloaded {len(video_files)} video file(s)", level="SUCCESS")
        except RuntimeError as exc:
            set_step(progress, "video_download", "failed", error=str(exc))
            set_status(progress, "failed", error=str(exc))
            save_progress(lesson_dir, progress)
            log(f"[media] video download failed: {exc}", level="WARNING")
    else:
        step_status = "skipped" if not is_media_classification(classification) or not require_videos else "pending"
        set_step(progress, "video_download", step_status)
        set_step(progress, "audio_extract", "skipped" if step_status == "skipped" else progress["steps"].get("audio_extract", "pending"))
        set_step(progress, "transcript", "skipped" if step_status == "skipped" else progress["steps"].get("transcript", "pending"))

    if require_transcripts and video_files:
        transcript_errors = []
        for video_index, video in enumerate(video_files, start=1):
            video_path = os.path.join(lesson_dir, video["file"])
            log(f"[transcript] processing video {video_index}/{len(video_files)}: {video['file']}")
            try:
                if progress_ui and course_key:
                    progress_ui.set_lesson_status(course_key, lesson["url"], "transcription", title=context["lesson_title"], section_title=lesson.get("section_title"))
                transcript = maybe_transcribe_video(
                    video_path,
                    api_key=groq_api_key,
                    transcript_timeout=max(args.transcript_timeout, 1.0),
                    audio_timeout=max(args.audio_timeout, 1.0),
                    retries=max(1, args.retry_count),
                    retry_delay=max(args.retry_delay, 0.1),
                )
                video["transcript"] = transcript
                log(
                    f"[transcript] transcript ready for video {video_index}/{len(video_files)}",
                    level="SUCCESS",
                )
            except RuntimeError as exc:
                video["transcript_error"] = str(exc)
                transcript_errors.append(str(exc))
                log(
                    f"[transcript] transcript failed for video {video_index}/{len(video_files)}: {exc}",
                    level="WARNING",
                )

        if transcript_errors:
            set_step(progress, "audio_extract", "failed", error=transcript_errors[-1])
            set_step(progress, "transcript", "failed", error=transcript_errors[-1])
            set_status(progress, "failed", error=transcript_errors[-1])
        else:
            set_step(progress, "audio_extract", "completed")
            set_step(progress, "transcript", "completed")
    elif require_transcripts and is_media_classification(classification):
        if progress["steps"].get("video_download") == "completed":
            set_step(progress, "audio_extract", "pending")
            set_step(progress, "transcript", "pending")
        elif progress["steps"].get("audio_extract") not in {"completed", "failed"}:
            set_step(progress, "audio_extract", "skipped")
            set_step(progress, "transcript", "skipped")
    elif is_media_classification(classification):
        if progress["steps"].get("audio_extract") not in {"completed", "failed"}:
            set_step(progress, "audio_extract", "skipped")
            set_step(progress, "transcript", "skipped")

    if progress_ui and course_key:
        progress_ui.set_lesson_status(course_key, lesson["url"], "rendering", title=context["lesson_title"], section_title=lesson.get("section_title"))
    saved = save_lesson(args.output_dir, lesson, final_url, page_parser, materials, page_lp_data, video_files=video_files)
    set_step(progress, "render_html", "completed")
    set_step(progress, "render_text", "completed")
    set_step(progress, "write_json", "completed")
    set_step(progress, "finalize", "completed")

    if lesson_satisfies_run(progress, require_videos=require_videos, require_transcripts=require_transcripts):
        set_status(progress, "completed", error=None)
    elif progress.get("status") != "failed":
        set_status(progress, "failed", error=progress.get("last_error"))

    save_progress(lesson_dir, progress)
    if progress_ui and course_key:
        final_status = "finished" if progress.get("status") == "completed" else "failed"
        progress_ui.set_lesson_status(course_key, lesson["url"], final_status, title=saved.get("title"), section_title=lesson.get("section_title"))
    return saved, progress


def process_lesson_contexts(contexts, course_args, groq_api_key, require_videos, require_transcripts, progress_ui=None, course_key=None):
    saved_by_url = {}
    progress_by_url = {}
    if not contexts:
        return saved_by_url, progress_by_url

    worker_count = max(1, int(getattr(course_args, "parallel", 1) or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(
                process_lesson_context,
                context,
                course_args,
                groq_api_key,
                require_videos,
                require_transcripts,
                progress_ui,
                course_key,
            ): context
            for context in contexts
        }
        for future in as_completed(future_map):
            context = future_map[future]
            try:
                saved, progress = future.result()
                saved_by_url[context["lesson"]["url"]] = saved
                progress_by_url[context["lesson"]["url"]] = progress
                log(f"[download] saved lesson {context['index']}/{context['total']}: {saved['title']}", level="SUCCESS")
            except RuntimeError as exc:
                progress = context["progress"]
                set_status(progress, "failed", error=str(exc))
                save_progress(context["lesson_dir"], progress)
                progress_by_url[context["lesson"]["url"]] = progress
                if progress_ui and course_key:
                    progress_ui.set_lesson_status(
                        course_key,
                        context["lesson"]["url"],
                        "failed",
                        title=context["lesson_title"],
                        section_title=context["lesson"].get("section_title"),
                    )
                log(f"[download] lesson failed {context['index']}/{context['total']}: {exc}", level="WARNING")

    return saved_by_url, progress_by_url


def finalize_manifest_and_state(args, manifest, saved_by_url, progress_by_url, state, emit_summary=True):
    manifest["lessons"] = sorted(saved_by_url.values(), key=lambda item: item.get("global_index") or 0)
    write_text(os.path.join(args.output_dir, "manifest.json"), json.dumps(manifest, ensure_ascii=False, indent=2))

    completed, failed = summarize_progress_counts(progress_by_url.values())
    state["completed_lessons"] = completed
    state["failed_lessons"] = failed
    state["status"] = "completed" if completed + failed >= manifest["lesson_count"] else "in_progress"
    save_course_state(args.output_dir, state)

    if emit_summary:
        first_meta = manifest["lessons"][0] if manifest["lessons"] else None
        summary_lines = [
            f"Lesson count: {len(manifest['lessons'])}",
            f"Output directory: {os.path.abspath(args.output_dir)}",
            f"Manifest: {os.path.abspath(os.path.join(args.output_dir, 'manifest.json'))}",
        ]
        if first_meta:
            summary_lines.append("First lesson: " + os.path.abspath(os.path.join(args.output_dir, first_meta["directories"]["lesson"])))
        print("\n" + "\n".join(summary_lines), flush=True)


def course_run_succeeded(result):
    if not result:
        return False
    failed = int(result.get("failed") or 0)
    completed = int(result.get("completed") or 0)
    total = int(result.get("total") or 0)
    return failed == 0 and completed >= total


def run_single_course(args, start_url, output_dir=None, progress_ui=None, course_key=None, course_title_hint=None):
    course_args = argparse.Namespace(**vars(args))
    course_args.start_url = start_url
    course_args.output_dir = output_dir or derive_download_root(start_url)
    ensure_dir(course_args.output_dir)
    acquire_course_lock(course_args.output_dir, start_url)

    try:
        require_videos = course_args.download_videos or course_args.download_transcripts
        require_transcripts = course_args.download_transcripts
        groq_api_key = None
        if require_transcripts:
            groq_api_key = resolve_groq_api_key(course_args.dotenv_path)
            if not groq_api_key:
                raise SystemExit(f"GROQ_API_KEY was not found. Check your env file: {course_args.dotenv_path}")

        downloader = build_downloader_from_args(course_args)
        log(f"[discover] Fetching initial page: {course_args.start_url}")
        first_html, first_final_url = retry_call(
            lambda: downloader.request_text(course_args.start_url),
            retries=max(1, course_args.retry_count),
            base_delay=max(course_args.retry_delay, 0.1),
            should_retry=is_retryable_error,
            on_retry=lambda attempt, retry_total, exc, delay: log(
                f"[http] initial page retry {attempt}/{retry_total}: {exc} ({delay:.1f}s)",
                level="WARNING",
            ),
        )
        first_parser = parse_page(first_final_url, first_html)
        problem = detect_access_problem(first_html, first_parser)
        if problem:
            raise SystemExit(problem)

        lp_data = extract_lp_data(first_html)
        course_title = course_title_hint or extract_course_title(first_html)
        curriculum_sections = extract_curriculum_sections(first_html, first_final_url)
        curriculum_items = flatten_curriculum_sections(curriculum_sections)
        curriculum_by_url = {item["url"]: item for item in curriculum_items}
        course_url = extract_course_url(first_final_url)
        effective_course_key = course_key or course_url

        if course_args.mode == "curriculum":
            lesson_items = curriculum_items
        elif course_args.mode == "next":
            lesson_items = [curriculum_by_url.get(item["url"], item) for item in collect_via_next(first_final_url, downloader, limit=course_args.limit or None)]
        else:
            lesson_items = curriculum_items or [
                curriculum_by_url.get(item["url"], item)
                for item in collect_via_next(first_final_url, downloader, limit=course_args.limit or None)
            ]

        if not lesson_items:
            raise SystemExit("No lessons were detected for this course")

        if course_args.limit:
            lesson_items = lesson_items[: course_args.limit]
        planned_curriculum_sections = filter_sections_to_lessons(curriculum_sections, lesson_items)

        log(f"[discover] Found {len(lesson_items)} lessons for this course")

        section_rows = build_section_rows(curriculum_sections)
        state, recovered = ensure_state(
            course_args.output_dir,
            course_title,
            course_args.start_url,
            first_final_url,
            course_args.mode,
            section_rows,
            len(lesson_items),
            require_videos=require_videos,
            require_transcripts=require_transcripts,
        )
        existing_entries = build_existing_entries(course_args.output_dir, lesson_items, recovered)
        single_check = build_course_check_from_lessons(
            course_title=course_title,
            course_url=course_url,
            continue_url=course_args.start_url,
            output_dir=course_args.output_dir,
            remote_lessons=lesson_items,
            local_lessons_by_url=existing_entries,
            section_count=len(curriculum_sections),
            require_videos=require_videos,
            require_transcripts=require_transcripts,
            check_mode=course_args.check_mode,
        )
        write_course_check(course_args.output_dir, single_check, create_dir=True)
        single_course_info = {
            "title": course_title,
            "url": course_url,
            "resolved_url": course_url,
            "continue_url": course_args.start_url,
            "curriculum_sections": planned_curriculum_sections,
            "section_count": len(planned_curriculum_sections),
            "lesson_count": len(lesson_items),
        }
        single_course_plan = build_course_plan(
            single_course_info,
            {
                "output_dir": course_args.output_dir,
                "lessons_by_url": existing_entries,
            },
            single_check,
            require_videos=require_videos,
            require_transcripts=require_transcripts,
        )
        write_course_plan(course_args.output_dir, single_course_plan, create_dir=True)
        if not (progress_ui and progress_ui.enabled):
            print_course_check_summary(1, 1, single_check)
            print_course_plan_summary(single_course_plan)
        if progress_ui:
            progress_ui.register_course(effective_course_key, course_title, status=single_course_plan["status"])
        if single_course_plan["status"] == "complete":
            log("[download] Nothing to do. This course already satisfies the requested outputs.", level="SUCCESS")
            if progress_ui:
                progress_ui.set_course_status(effective_course_key, "complete")
            return {
                "completed": single_check["local"]["completed_lessons"],
                "failed": single_check["local"]["failed_lessons"],
                "total": len(lesson_items),
                "output_dir": course_args.output_dir,
            }

        sync_course_tree(
            progress_ui,
            effective_course_key,
            course_title,
            curriculum_sections,
            lesson_items,
            existing_entries,
            require_videos=require_videos,
            require_transcripts=require_transcripts,
        )

        text_contexts, media_contexts, other_contexts, saved_by_url, progress_by_url, classification_counts = discover_lessons(
            course_args,
            lesson_items,
            downloader,
            first_final_url,
            first_html,
            first_final_url,
            first_parser,
            existing_entries,
            require_videos=require_videos,
            require_transcripts=require_transcripts,
            progress_ui=progress_ui,
            course_key=effective_course_key,
        )

        state["classified"] = classification_counts
        save_course_state(course_args.output_dir, state)

        manifest = {
            "course_title": course_title,
            "start_url": course_args.start_url,
            "resolved_url": first_final_url,
            "mode": course_args.mode,
            "section_count": len(curriculum_sections),
            "lesson_count": len(lesson_items),
            "lp_rest_load_ajax": lp_data.get("lp_rest_load_ajax"),
            "sections": section_rows,
            "lessons": [],
        }

        processed_saved, processed_progress = process_lesson_contexts(
            text_contexts + media_contexts + other_contexts,
            course_args,
            groq_api_key,
            require_videos=require_videos,
            require_transcripts=require_transcripts,
            progress_ui=progress_ui,
            course_key=effective_course_key,
        )
        saved_by_url.update(processed_saved)
        progress_by_url.update(processed_progress)

        finalize_manifest_and_state(
            course_args,
            manifest,
            saved_by_url,
            progress_by_url,
            state,
            emit_summary=not (progress_ui and progress_ui.enabled),
        )
        completed, failed = summarize_progress_counts(progress_by_url.values())
        if progress_ui and effective_course_key:
            final_status = "finished" if completed >= len(lesson_items) and failed == 0 else ("failed" if failed and completed == 0 else "partial")
            progress_ui.set_course_status(effective_course_key, final_status)
        return {
            "completed": completed,
            "failed": failed,
            "total": len(lesson_items),
            "output_dir": course_args.output_dir,
        }
    finally:
        release_course_lock(course_args.output_dir)
