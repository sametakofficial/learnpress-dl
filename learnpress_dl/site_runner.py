import sys

from .common import DEFAULT_DOWNLOADS_DIR, derive_download_root, ensure_dir, get_log_enabled, log, set_log_enabled
from .course_runner import build_downloader_from_args, print_course_check_summary, run_single_course
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
        "\nGenel ozet\n"
        f"  check mode: {summary.get('check_mode', 'shallow')}\n"
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

    lines = ["Aksiyon gereken kurslar"]
    for item in top_items:
        diff = item.get("diff") or {}
        lines.append(
            f"  - {item['course_title']} [{item['status']}] missing={diff.get('missing_lessons', 0)} partial={diff.get('partial_lessons', 0)}"
        )
    print("\n" + "\n".join(lines), flush=True)


def should_use_tree_progress(args):
    if args.tree_progress is not None:
        return args.tree_progress
    return not args.check and not args.discover_only and sys.stdout.isatty()


def run_all_courses(args, parser, base_url, courses_page):
    if not base_url:
        parser.error("Tum kurs modu icin --base-url veya .env icinde BASE_URL gerekli")

    require_videos = args.download_videos or args.download_transcripts
    require_transcripts = args.download_transcripts
    tree_ui = TreeProgressUI(enabled=should_use_tree_progress(args))
    previous_log_enabled = get_log_enabled()
    if tree_ui.enabled:
        set_log_enabled(False)
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
            raise SystemExit(f"{discovery['archive_url']} altinda kurs bulunamadi.")

        log(f"{len(courses)} kurs bulundu: {discovery['archive_url']}")
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
            log(f"[{index}/{len(courses)}] Kurs bootstrap aliniyor: {course.get('title') or course['url']}")
            course_info = bootstrap_course(
                downloader,
                course,
                retries=max(1, args.retry_count),
                retry_delay=max(args.retry_delay, 0.1),
            )
            if not tree_ui.enabled:
                print_course_bootstrap_summary(index, len(courses), course_info)

            if not course_info.get("continue_url"):
                log(f"[{index}/{len(courses)}] Ilk course-item__link bulunamadi, atlandi: {course_info.get('title') or course_info['url']}", level="WARN")
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
                log(f"Skip: kurs zaten tamam gorunuyor: {course_plan['course_title']}", level="OK")
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

        if args.discover_only or args.check:
            complete_count = summary["counts"]["complete"]
            partial_count = summary["counts"]["partial"]
            new_count = summary["counts"]["new"]
            bootstrap_failed_count = summary["counts"]["bootstrap_failed"]
            log(
                f"Check ozeti: complete={complete_count}, partial={partial_count}, new={new_count}, bootstrap_failed={bootstrap_failed_count}"
            )
            if not actionable_courses and bootstrap_failed_count == 0:
                log("Eksik bir sey yok. Tum kurslar mevcut gereksinimlere gore tamam gorunuyor.", level="OK")
            return

        if not actionable_courses:
            log("Indirilecek eksik ders bulunamadi. Her sey mevcut gorunuyor.", level="OK")
            return

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
                f"Resume basliyor: {course_info.get('title') or course_info['url']} [{course_plan['status']}] ({', '.join(reason) or 'work_pending'})"
            )
            tree_ui.set_course_status(course_key, "running")
            run_single_course(
                args,
                course_info["continue_url"],
                output_dir=course_output_dir,
                progress_ui=tree_ui,
                course_key=course_key,
                course_title_hint=course_info.get("title"),
            )
    finally:
        set_log_enabled(previous_log_enabled)
        tree_ui.finish()
