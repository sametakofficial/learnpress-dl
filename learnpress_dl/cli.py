import argparse

from .common import PROJECT_ENV_PATH, resolve_base_url, resolve_courses_page
from .course_runner import run_single_course
from .site_runner import run_all_courses


def build_parser():
    parser = argparse.ArgumentParser(description="LearnPress ders sayfalarini cookie ile indirir.")
    parser.add_argument("start_url", nargs="?", help="Ilk ders veya kurs ici ders URL'si")
    parser.add_argument("--cookie-file", help="Netscape formatli cookie dosyasi")
    parser.add_argument("--cookie-header", help="Ham Cookie header degeri")
    parser.add_argument("--run-mode", choices=("single", "multi"), help="Calisma modu")
    parser.add_argument("--base-url", help="Tum kurs kesfi icin site kok URL'si")
    parser.add_argument("--courses-page", help="Kurslar arsiv sayfasi yolu, ornek: kurslar/ veya proje/kurslar/")
    parser.add_argument("--check-depth", choices=("fast", "deep"), default="fast", help="Karsilastirma derinligi")
    parser.add_argument(
        "--tree-progress",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Tum kurs calismalarinda agac tipi canli ilerleme ekranini ac/kapat",
    )
    parser.add_argument(
        "--lesson-mode",
        choices=("auto", "curriculum", "next"),
        default="auto",
        help="Dersler arasi gecis yontemi",
    )
    parser.add_argument("--output-dir", default=None, help="Cikti klasoru")
    parser.add_argument("--delay", type=float, default=0.0, help="Istekler arasina saniye cinsinden bekleme ekler")
    parser.add_argument("--limit", type=int, default=0, help="Sadece ilk N dersi indirir")
    parser.add_argument("--request-timeout", type=float, default=30.0, help="Her HTTP istegi icin saniye bazli timeout")
    parser.add_argument("--download-videos", action="store_true", help="Iframe videolarini da indirir")
    parser.add_argument("--video-timeout", type=float, default=1800.0, help="Tek bir video indirme islemi icin timeout")
    parser.add_argument("--download-transcripts", action="store_true", help="Indirilen videolar icin transcript uretir")
    parser.add_argument("--transcript-timeout", type=float, default=1800.0, help="Tek bir transcript API istegi icin timeout")
    parser.add_argument("--audio-timeout", type=float, default=1800.0, help="Videodan ses ayirma islemi icin timeout")
    parser.add_argument("--dotenv-path", default=PROJECT_ENV_PATH, help="GROQ_API_KEY okunacak .env dosyasi")
    parser.add_argument("--text-workers", type=int, default=4, help="Text-only dersler icin eszamanli worker sayisi")
    parser.add_argument("--retry-count", type=int, default=3, help="Gecici hatalarda deneme sayisi")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Retry backoff icin taban bekleme suresi")
    return parser


def resolve_base_url_from_args(args):
    return args.base_url or resolve_base_url(args.dotenv_path)


def resolve_courses_page_from_args(args):
    return args.courses_page or resolve_courses_page(args.dotenv_path)


def resolve_run_mode(args, base_url):
    if args.run_mode:
        return args.run_mode
    if args.start_url:
        return "single"
    if base_url:
        return "multi"
    return None


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.cookie_file and not args.cookie_header:
        parser.error("--cookie-file veya --cookie-header vermelisin")

    base_url = resolve_base_url_from_args(args)
    courses_page = resolve_courses_page_from_args(args)
    args.check_depth = args.check_depth
    args.check_mode = args.check_depth
    args.mode = args.lesson_mode

    run_mode = resolve_run_mode(args, base_url)
    if args.run_mode == "multi" and args.start_url:
        parser.error("multi modda start_url verme")
    if args.run_mode == "single" and not args.start_url:
        parser.error("single mod icin start_url gerekli")
    if run_mode == "multi":
        run_all_courses(args, parser, base_url, courses_page)
        return
    if run_mode != "single":
        parser.error("--run-mode single icin start_url ver veya --run-mode multi icin BASE_URL kullan")
    if not args.start_url:
        parser.error("single mod icin start_url gerekli")

    run_single_course(args, args.start_url, output_dir=args.output_dir)
