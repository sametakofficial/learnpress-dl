import html
import http.cookiejar
import json
import random
import os
import shutil
import sys
import tempfile
import re
import socket
import subprocess
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser


DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DOWNLOADS_DIR = os.path.join(PROJECT_ROOT, "downloads")
PROJECT_ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
GROQ_TRANSCRIPT_MODEL = "whisper-large-v3-turbo"
GROQ_TRANSCRIPT_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 20,
    "WARNING": 30,
    "ERROR": 40,
}
CURRENT_LOG_LEVEL = LOG_LEVELS["INFO"]

VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}

BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tr",
    "td",
    "th",
    "thead",
    "tbody",
    "tfoot",
    "ul",
}


def class_list(attrs):
    value = dict(attrs).get("class", "")
    return {item.strip() for item in value.split() if item.strip()}


def attr_map(attrs):
    return {key: value for key, value in attrs}


def slugify(value, fallback="item"):
    replacements = str.maketrans(
        {
            "ç": "c",
            "Ç": "C",
            "ğ": "g",
            "Ğ": "G",
            "ı": "i",
            "İ": "I",
            "ö": "o",
            "Ö": "O",
            "ş": "s",
            "Ş": "S",
            "ü": "u",
            "Ü": "U",
        }
    )
    normalized = unicodedata.normalize("NFKD", value.translate(replacements))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return cleaned or fallback


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def write_text(path, content):
    directory = os.path.dirname(path) or "."
    ensure_dir(directory)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as handle:
        handle.write(content)
        temp_path = handle.name
    os.replace(temp_path, path)


def write_json(path, payload):
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _sanitize_cookie_file(cookie_file):
    sanitized_lines = ["# Netscape HTTP Cookie File\n"]
    kept_cookie_lines = 0

    with open(cookie_file, "r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if not stripped:
                sanitized_lines.append("\n")
                continue
            if stripped.startswith("#"):
                if stripped != "# Netscape HTTP Cookie File":
                    sanitized_lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
                continue
            if len(raw_line.rstrip("\n").split("\t")) == 7:
                sanitized_lines.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
                kept_cookie_lines += 1

    temp_handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
    try:
        temp_handle.writelines(sanitized_lines)
    finally:
        temp_handle.close()
    return temp_handle.name, kept_cookie_lines


def load_cookie_jar(cookie_file, retries=3, retry_delay=0.2):
    last_exc = None
    for attempt in range(max(1, retries)):
        jar = http.cookiejar.MozillaCookieJar()
        try:
            jar.load(cookie_file, ignore_discard=True, ignore_expires=True)
            return jar
        except http.cookiejar.LoadError as exc:
            last_exc = exc
            if attempt < max(1, retries) - 1:
                time.sleep(retry_delay * (attempt + 1))

    sanitized_path = None
    try:
        sanitized_path, kept_cookie_lines = _sanitize_cookie_file(cookie_file)
        if kept_cookie_lines <= 0:
            raise RuntimeError(f"Cookie file could not be parsed as Netscape format: {cookie_file}") from last_exc
        jar = http.cookiejar.MozillaCookieJar()
        jar.load(sanitized_path, ignore_discard=True, ignore_expires=True)
        log(
            f"[http] cookie file had malformed lines; loaded sanitized copy with {kept_cookie_lines} cookies",
            level="WARNING",
        )
        return jar
    except http.cookiejar.LoadError as exc:
        raise RuntimeError(f"Cookie file could not be parsed as Netscape format: {cookie_file}") from exc
    finally:
        if sanitized_path and os.path.exists(sanitized_path):
            os.remove(sanitized_path)


def is_retryable_error(exc):
    message = str(exc)
    retry_markers = (
        "Timeout after",
        "Request failed",
        "HTTP 429",
        "HTTP 500",
        "HTTP 502",
        "HTTP 503",
        "HTTP 504",
        "Database Error",
    )
    return any(marker in message for marker in retry_markers)


def retry_call(fn, retries=3, base_delay=2.0, should_retry=None, on_retry=None):
    should_retry = should_retry or is_retryable_error
    attempts = max(1, retries)
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except RuntimeError as exc:
            last_exc = exc
            if attempt >= attempts or not should_retry(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.0, 0.5)
            if on_retry:
                on_retry(attempt, attempts, exc, delay)
            time.sleep(delay)
    if last_exc:
        raise last_exc


def run_command(command, timeout=None):
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=True,
        )
        return completed
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out: {' '.join(command)}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or "command failed"
        raise RuntimeError(details[:800]) from exc


def read_dotenv(path):
    env = {}
    if not path or not os.path.exists(path):
        return env

    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            env[key.strip()] = value
    return env


def resolve_groq_api_key(dotenv_path=PROJECT_ENV_PATH):
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key
    return read_dotenv(dotenv_path).get("GROQ_API_KEY")


def normalize_base_url(base_url):
    if not base_url:
        return None
    raw_value = base_url.strip()
    if not raw_value:
        return None
    if not re.match(r"^https?://", raw_value, re.I):
        raw_value = "https://" + raw_value.lstrip("/")
    parsed = urllib.parse.urlparse(raw_value)
    if not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    return urllib.parse.urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", ""))


def resolve_base_url(dotenv_path=PROJECT_ENV_PATH):
    value = os.environ.get("BASE_URL")
    if not value:
        value = read_dotenv(dotenv_path).get("BASE_URL")
    return normalize_base_url(value)


def normalize_courses_page(courses_page):
    if courses_page is None:
        return "kurslar/"
    raw_value = courses_page.strip()
    if not raw_value:
        return "kurslar/"
    if re.match(r"^https?://", raw_value, re.I):
        return raw_value
    normalized = raw_value.lstrip("/")
    if not normalized.endswith("/"):
        normalized += "/"
    return normalized


def resolve_courses_page(dotenv_path=PROJECT_ENV_PATH):
    value = os.environ.get("COURSES_PAGE")
    if value is None:
        value = read_dotenv(dotenv_path).get("COURSES_PAGE")
    return normalize_courses_page(value)


def build_courses_archive_url(base_url, courses_page=None):
    normalized = normalize_base_url(base_url)
    if not normalized:
        raise RuntimeError("BASE_URL is missing or invalid")
    normalized_page = normalize_courses_page(courses_page)
    if re.match(r"^https?://", normalized_page, re.I):
        return normalized_page
    return urllib.parse.urljoin(normalized.rstrip("/") + "/", normalized_page)


def derive_download_root(start_url, downloads_dir=None):
    parsed = urllib.parse.urlparse(start_url)
    pieces = [parsed.netloc] + [part for part in parsed.path.split("/") if part]
    folder_name = slugify("-".join(pieces), fallback="download")
    return os.path.join(downloads_dir or DEFAULT_DOWNLOADS_DIR, folder_name)


def zip_directory(directory_path, archive_base_path=None):
    if not os.path.isdir(directory_path):
        raise RuntimeError(f"Directory does not exist: {directory_path}")
    normalized = os.path.abspath(directory_path)
    parent = os.path.dirname(normalized)
    base_name = archive_base_path or normalized
    archive_path = shutil.make_archive(base_name, "zip", root_dir=parent, base_dir=os.path.basename(normalized))
    return archive_path


def build_multipart_formdata(fields, file_field_name, file_path, file_mime):
    boundary = f"----OpenCodeBoundary{int(time.time() * 1000)}"
    body = bytearray()

    for key, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode(
                "utf-8"
            )
        )

    filename = os.path.basename(file_path)
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field_name}"; '
            f'filename="{filename}"\r\n'
        ).encode("utf-8")
    )
    body.extend(f"Content-Type: {file_mime}\r\n\r\n".encode("utf-8"))
    with open(file_path, "rb") as handle:
        body.extend(handle.read())
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    return boundary, bytes(body)


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def _maybe_break(self, tag):
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")
        else:
            self._maybe_break(tag)

    def handle_endtag(self, tag):
        self._maybe_break(tag)

    def handle_data(self, data):
        if data:
            self.parts.append(data)

    def get_text(self):
        text = "".join(self.parts)
        text = html.unescape(text)
        text = re.sub(r"\r", "", text)
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def html_to_text(fragment):
    parser = TextExtractor()
    parser.feed(fragment)
    parser.close()
    return parser.get_text()


def strip_tags(fragment):
    return html_to_text(fragment).replace("\n", " ").strip()


def safe_relpath(path, start):
    rel = os.path.relpath(path, start)
    return rel.replace(os.sep, "/")


def guess_mime_type(path):
    lowered = path.lower()
    if lowered.endswith(".mp4"):
        return "video/mp4"
    if lowered.endswith(".webm"):
        return "video/webm"
    if lowered.endswith(".mkv"):
        return "video/x-matroska"
    return "application/octet-stream"


def guess_audio_mime_type(path):
    lowered = path.lower()
    if lowered.endswith(".mp3"):
        return "audio/mpeg"
    if lowered.endswith(".wav"):
        return "audio/wav"
    if lowered.endswith(".m4a"):
        return "audio/mp4"
    return "application/octet-stream"


def ordered_slug(index, title, fallback_prefix):
    slug = slugify(title, fallback=f"{fallback_prefix}-{index:02d}")
    return f"{index:02d}-{slug}"


def normalize_notice_texts(notices):
    ignored = {
        "The lesson content is empty.",
        "This lesson content is empty.",
    }
    result = []
    for notice in notices:
        cleaned = " ".join(notice.split()).strip()
        if cleaned and cleaned not in ignored:
            result.append(cleaned)
    return result


class Downloader:
    def __init__(self, cookie_file=None, cookie_header=None, delay=0.0, request_timeout=30.0):
        self.cookie_file = cookie_file
        self.cookie_header = cookie_header
        self.delay = delay
        self.request_timeout = request_timeout
        self.cookie_jar = None
        self.opener = self._build_opener()

    def _build_opener(self):
        handlers = []

        if self.cookie_file:
            jar = load_cookie_jar(self.cookie_file)
            self.cookie_jar = jar
            handlers.append(urllib.request.HTTPCookieProcessor(jar))

        opener = urllib.request.build_opener(*handlers)
        opener.addheaders = [("User-Agent", DEFAULT_UA)]
        if self.cookie_header:
            opener.addheaders.append(("Cookie", self.cookie_header))
        return opener

    def request_text(self, url, method="GET", headers=None, data=None):
        log(f"[http] {method} {url}", level="DEBUG")
        request = urllib.request.Request(url, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if data is not None:
            if isinstance(data, str):
                data = data.encode("utf-8")
            request.data = data

        try:
            with self.opener.open(request, timeout=self.request_timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                text = response.read().decode(charset, errors="replace")
                final_url = response.geturl()
                log(f"[http] response url={final_url} status=ok", level="DEBUG")
                if self.delay:
                    time.sleep(self.delay)
                return text, final_url
        except socket.timeout as exc:
            raise RuntimeError(f"Timeout after {self.request_timeout:.1f}s for {url}") from exc
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} for {url}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Request failed for {url}: {exc}") from exc

    def request_json(self, url, method="GET", headers=None, data=None):
        text, _ = self.request_text(url, method=method, headers=headers, data=data)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from {url}: {text[:500]}") from exc


def set_log_level(level_name):
    global CURRENT_LOG_LEVEL
    CURRENT_LOG_LEVEL = LOG_LEVELS.get((level_name or "INFO").upper(), LOG_LEVELS["INFO"])


def get_log_level():
    return CURRENT_LOG_LEVEL


def log(message, level="INFO"):
    normalized_level = (level or "INFO").upper()
    if LOG_LEVELS.get(normalized_level, LOG_LEVELS["INFO"]) < CURRENT_LOG_LEVEL:
        return
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{normalized_level}] {message}", file=sys.stderr, flush=True)
