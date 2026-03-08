import os
import time
import sys

from .common import DEFAULT_DOWNLOADS_DIR, derive_download_root, ensure_dir, log, timestamped_archive_base_path, zip_directory
from .course_runner import build_downloader_from_args, collect_failed_lesson_urls, print_course_check_summary, run_single_course
from .discovery import bootstrap_course, discover_courses
from .inventory import (
    build_bootstrap_failed_check,
    build_course_check,
    compact_course_check,
    index_local_courses,
    match_local_course,
    summarize_site_check,
    write_course_check,
    write_site_check,
)
from .planner import build_course_plan, build_site_plan, compact_course_plan, write_course_plan, write_site_plan
from .state import load_course_state
from .ui import TreeProgressUI


def print_course_bootstrap_summary(index, total, course_info):
    title = course_info.get("title") or course_info.get("url")
    continue_url = course_info.get("continue_url") or "-"
    print(
        f"[{index}/{total}] {title}\n"
        f"  course: {course_info.get('resolved_url') or course_info.get('url')}\n"
        f"  continue: {continue_url}\n"
        f"  sections/lessons: {course_info.get('section_count', 0)} / {course_info.get('lesson_count', 0)}",
        flush=True,
    )


def print_site_check_summary(summary):
    counts = summary["counts"]
    print(
        "\nSummary\n"
        f"  check depth: {summary.get('check_mode', 'fast')}\n"
        f"  complete: {counts['complete']}\n"
        f"  partial: {counts['partial']}\n"
        f"  new: {counts['new']}\n"
        f"  bootstrap_failed: {counts['bootstrap_failed']}\n"
        f"  total missing lessons: {summary['missing_lessons']}\n"
        f"  total partial lessons: {summary['partial_lessons']}\n"
        f"  total failed lessons: {summary['failed_lessons']}\n"
        f"  total invalid lessons: {summary.get('invalid_lessons', 0)}",
        flush=True,
    )

    top_items = summary["actionable"][:5]
    if not top_items:
        return

    lines = ["Actionable courses"]
    for item in top_items:
        diff = item.get("diff") or {}
        lines.append(
            f"  - {item['course_title']} [{item['status']}] missing={diff.get('missing_lessons', 0)} partial={diff.get('partial_lessons', 0)}"
        )
    print("\n" + "\n".join(lines), flush=True)


def should_use_tree_progress(args):
    if args.tree_progress is not None:
        return args.tree_progress
    return sys.stdout.isatty()


def course_check_succeeded(check):
    local = check.get("local") or {}
    remote = check.get("remote") or {}
    return int(local.get("failed_lessons") or 0) == 0 and int(local.get("completed_lessons") or 0) >= int(remote.get("lesson_count") or 0)


def list_local_course_output_dirs(base_output_dir):
    if not os.path.isdir(base_output_dir):
        return []
    course_dirs = []
    for entry in os.scandir(base_output_dir):
        if entry.is_dir() and os.path.isfile(os.path.join(entry.path, "state.json")):
            course_dirs.append(entry.path)
    return sorted(course_dirs)


def create_run_archive(output_dir):
    archive_path = zip_directory(output_dir, archive_base_path=timestamped_archive_base_path(output_dir, timestamp=time.strftime("%Y%m%d-%H%M%S", time.localtime())))
    log(f"[archive] Created run zip: {archive_path}", level="SUCCESS")
    return archive_path


def run_retry_failed_courses(args):
    base_output_dir = args.output_dir or DEFAULT_DOWNLOADS_DIR
    ensure_dir(base_output_dir)
    tree_ui = TreeProgressUI(enabled=should_use_tree_progress(args))
    try:
        course_dirs = list_local_course_output_dirs(base_output_dir)
        if not course_dirs:
            raise SystemExit(f"No local course outputs were found under {base_output_dir}")

        for course_dir in course_dirs:
            state = load_course_state(course_dir) or {}
            course_title = state.get("course_title") or os.path.basename(course_dir)
            start_url = state.get("start_url") or state.get("resolved_url")
            failed_urls = collect_failed_lesson_urls(course_dir)
            if not failed_urls:
                log(f"[retry] Skipping {course_title}: no locally failed lessons found", level="SUCCESS")
                continue
            if not start_url:
                log(f"[retry] Skipping {course_title}: start URL is missing from local state", level="WARNING")
                continue
            log(f"[retry] Retrying {len(failed_urls)} failed lessons for {course_title}")
            result = run_single_course(
                args,
                start_url,
                output_dir=course_dir,
                progress_ui=tree_ui,
                course_key=state.get("resolved_url") or start_url or course_dir,
                course_title_hint=course_title,
            )

        if args.zip_courses:
            create_run_archive(base_output_dir)
    finally:
        tree_ui.finish()


def run_all_courses(args, parser, base_url, courses_page):
    if not base_url:
        parser.error("BASE_URL is required when no course URL is provided")

    require_videos = args.download_videos or args.download_transcripts
    require_transcripts = args.download_transcripts
    tree_ui = TreeProgressUI(enabled=should_use_tree_progress(args))
    downloader = build_downloader_from_args(args)
    try:
        discovery = discover_courses(
            downloader,
            base_url,
            courses_page=courses_page,
            retries=max(1, args.retry_count),
            retry_delay=max(args.retry_delay, 0.1),
        )
        courses = discovery["courses"]
        if not courses:
            raise SystemExit(f"No courses found at {discovery['archive_url']}")

        log(f"[discover] Found {len(courses)} courses at {discovery['archive_url']}")
        base_output_dir = args.output_dir or DEFAULT_DOWNLOADS_DIR
        ensure_dir(base_output_dir)
        local_index = index_local_courses(
            base_output_dir,
            require_videos=require_videos,
            require_transcripts=require_transcripts,
        )

        for course in courses:
            course_key = course.get("url")
            tree_ui.register_course(course_key, course.get("title") or course_key, status="queued")

        check_results = []
        course_infos_for_plan = []

        for index, course in enumerate(courses, start=1):
            course_key = course.get("url")
            tree_ui.set_course_status(course_key, "checking")
            log(f"[discover] {index}/{len(courses)} bootstrapping {course.get('title') or course['url']}")
            course_info = bootstrap_course(
                downloader,
                course,
                retries=max(1, args.retry_count),
                retry_delay=max(args.retry_delay, 0.1),
            )
            if not tree_ui.enabled:
                print_course_bootstrap_summary(index, len(courses), course_info)

            if not course_info.get("continue_url"):
                log(f"[discover] {index}/{len(courses)} first course-item__link not found, skipping {course_info.get('title') or course_info['url']}", level="WARNING")
                tree_ui.set_course_status(course_key, "failed")
                check_results.append(build_bootstrap_failed_check(course_info, check_mode=args.check_mode))
                course_infos_for_plan.append(course_info)
                continue

            local_record = match_local_course(local_index, course_info)
            default_output_dir = None
            if not local_record:
                default_output_dir = derive_download_root(course_info.get("resolved_url") or course_info["url"], downloads_dir=base_output_dir)

            check = build_course_check(
                course_info,
                local_record,
                require_videos=require_videos,
                require_transcripts=require_transcripts,
                check_mode=args.check_mode,
            )
            if not check.get("output_dir"):
                check["output_dir"] = default_output_dir or (local_record or {}).get("output_dir")
            write_course_check(check.get("output_dir"), check, create_dir=False)
            check_results.append(check)
            course_infos_for_plan.append(course_info)
            tree_ui.set_course_status(course_key, check["status"])
            if not tree_ui.enabled:
                print_course_check_summary(index, len(courses), check)

        course_plans = []
        actionable_courses = []
        for course_info, check in zip(course_infos_for_plan, check_results):
            local_record = match_local_course(local_index, course_info) if check.get("continue_url") else None
            course_plan = build_course_plan(
                course_info,
                local_record,
                check,
                require_videos=require_videos,
                require_transcripts=require_transcripts,
            )
            write_course_plan(course_plan.get("output_dir"), course_plan, create_dir=False)
            course_plans.append(course_plan)
            tree_ui.set_course_status(course_info.get("url"), course_plan["status"])
            if course_plan["status"] == "complete":
                log(f"[download] Skipping already complete course: {course_plan['course_title']}", level="SUCCESS")
            elif course_plan["status"] in {"resume_needed", "recovery_needed", "new"}:
                actionable_courses.append((course_info, check, course_plan))

        site_check = {
            "base_url": base_url,
            "archive_url": discovery["archive_url"],
            "course_count": len(courses),
            "check_mode": args.check_mode,
            "checks": [compact_course_check(check) for check in check_results],
        }
        write_site_check(base_output_dir, site_check)
        site_plan = build_site_plan(base_url, discovery["archive_url"], [compact_course_plan(plan) for plan in course_plans])
        write_site_plan(base_output_dir, site_plan)
        summary = summarize_site_check(check_results)
        summary["check_mode"] = args.check_mode
        if not tree_ui.enabled:
            print_site_check_summary(summary)

        complete_count = summary["counts"]["complete"]
        partial_count = summary["counts"]["partial"]
        new_count = summary["counts"]["new"]
        bootstrap_failed_count = summary["counts"]["bootstrap_failed"]
        log(
            f"[check] complete={complete_count} partial={partial_count} new={new_count} bootstrap_failed={bootstrap_failed_count}"
        )
        if not actionable_courses and bootstrap_failed_count == 0:
            log("[download] Nothing to do. All courses already satisfy the requested outputs.", level="SUCCESS")
        elif not actionable_courses:
            log("[download] No actionable lessons found.", level="SUCCESS")

        for course_info, check, course_plan in actionable_courses:
            course_key = course_info.get("resolved_url") or course_info.get("url")
            course_output_dir = check.get("output_dir")
            if not course_output_dir:
                course_output_dir = derive_download_root(course_info.get("resolved_url") or course_info["url"], downloads_dir=base_output_dir)
            reason = []
            if course_plan.get("actionable_lesson_count"):
                reason.append(f"actionable_lessons={course_plan['actionable_lesson_count']}")
            if check["diff"].get("missing_lessons"):
                reason.append(f"missing={check['diff']['missing_lessons']}")
            if check["diff"].get("partial_lessons"):
                reason.append(f"partial={check['diff']['partial_lessons']}")
            if check["diff"].get("failed_lessons"):
                reason.append(f"failed={check['diff']['failed_lessons']}")
            log(
                f"[download] Starting {course_info.get('title') or course_info['url']} status={course_plan['status']} details={', '.join(reason) or 'work_pending'}"
            )
            tree_ui.set_course_status(course_key, "running")
            result = run_single_course(
                args,
                course_info["continue_url"],
                output_dir=course_output_dir,
                progress_ui=tree_ui,
                course_key=course_key,
                course_title_hint=course_info.get("title"),
            )

        if args.zip_courses:
            create_run_archive(base_output_dir)
    finally:
        tree_ui.finish()
