import argparse

from .common import (
    PROJECT_ENV_PATH,
    derive_download_root,
    resolve_base_url,
    resolve_courses_page,
    set_log_level,
    timestamped_archive_base_path,
    zip_directory,
)
from .course_runner import run_single_course
from .site_runner import run_all_courses, run_retry_failed_courses


def build_parser():
    parser = argparse.ArgumentParser(description="Download content from LearnPress course sites.")
    parser.add_argument("url", nargs="?", help="Course or lesson URL. If omitted, all courses are discovered from BASE_URL + COURSES_PAGE.")
    parser.add_argument("--cookie-file", help="Path to a Netscape-format cookie file.")
    parser.add_argument("--cookie-header", help="Raw Cookie header value.")
    parser.add_argument("--base-url", help="Base site URL used when no course URL is provided.")
    parser.add_argument("--courses-page", help="Courses archive path, for example: kurslar/, site/kurslar/, or /courses/.")
    parser.add_argument("--check-depth", choices=("fast", "deep"), default="fast", help="Comparison depth before downloading.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument("--quiet", action="store_true", help="Show warnings and errors only.")
    parser.add_argument(
        "--tree-progress",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable the live tree progress view.",
    )
    parser.add_argument(
        "--lesson-mode",
        choices=("auto", "curriculum", "next"),
        default="auto",
        help="Lesson traversal strategy.",
    )
    parser.add_argument("--output-dir", default=None, help="Output directory.")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay between HTTP requests in seconds.")
    parser.add_argument("--limit", type=int, default=0, help="Limit processing to the first N lessons.")
    parser.add_argument("--request-timeout", type=float, default=30.0, help="Timeout for each HTTP request in seconds.")
    parser.add_argument("--download-videos", action="store_true", help="Download embedded lesson videos.")
    parser.add_argument("--video-timeout", type=float, default=1800.0, help="Timeout for a single video download in seconds.")
    parser.add_argument("--download-transcripts", action="store_true", help="Generate transcripts for downloaded videos.")
    parser.add_argument("--transcript-timeout", type=float, default=1800.0, help="Timeout for a single transcript request in seconds.")
    parser.add_argument("--audio-timeout", type=float, default=1800.0, help="Timeout for local audio extraction in seconds.")
    parser.add_argument("--zip-courses", action="store_true", help="Create zip archive(s) for successful course outputs.")
    parser.add_argument("--retry-failed", action="store_true", help="Skip check mode and retry only locally failed lessons from saved progress files.")
    parser.add_argument("--dotenv-path", default=PROJECT_ENV_PATH, help="Path to the .env file used for configuration.")
    parser.add_argument(
        "--parallel",
        "--text-workers",
        dest="parallel",
        type=int,
        default=4,
        help="Maximum number of lessons to process in parallel.",
    )
    parser.add_argument("--retry-count", type=int, default=3, help="Retry count for transient failures.")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Base retry backoff delay in seconds.")
    return parser


def resolve_base_url_from_args(args):
    return args.base_url or resolve_base_url(args.dotenv_path)


def resolve_courses_page_from_args(args):
    return args.courses_page or resolve_courses_page(args.dotenv_path)


def resolve_target_scope(url, base_url):
    if url:
        return "single"
    if base_url:
        return "multi"
    return None


def configure_logging(args):
    if args.verbose and args.quiet:
        raise ValueError("--verbose and --quiet cannot be used together")
    if args.verbose:
        set_log_level("DEBUG")
    elif args.quiet:
        set_log_level("WARNING")
    else:
        set_log_level("INFO")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        configure_logging(args)
    except ValueError as exc:
        parser.error(str(exc))

    if not args.cookie_file and not args.cookie_header:
        parser.error("Provide either --cookie-file or --cookie-header")

    base_url = resolve_base_url_from_args(args)
    courses_page = resolve_courses_page_from_args(args)
    args.check_mode = args.check_depth
    args.mode = args.lesson_mode
    args.start_url = args.url

    if args.retry_failed:
        if args.url:
            output_dir = args.output_dir or derive_download_root(args.url)
            result = run_single_course(args, args.url, output_dir=output_dir)
            if args.zip_courses:
                archive_path = zip_directory(output_dir, archive_base_path=timestamped_archive_base_path(output_dir))
                print(f"Created course archive: {archive_path}", flush=True)
            return
        run_retry_failed_courses(args)
        return

    target_scope = resolve_target_scope(args.url, base_url)
    if target_scope == "single":
        result = run_single_course(args, args.url, output_dir=args.output_dir)
        if args.zip_courses:
            output_dir = result.get("output_dir") or args.output_dir or derive_download_root(args.url)
            archive_path = zip_directory(output_dir, archive_base_path=timestamped_archive_base_path(output_dir))
            print(f"Created course archive: {archive_path}", flush=True)
        return

    if target_scope != "multi":
        parser.error("Provide a course URL, or set BASE_URL for site-wide discovery")

    run_all_courses(args, parser, base_url, courses_page)
