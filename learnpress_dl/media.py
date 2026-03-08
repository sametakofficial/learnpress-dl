import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request

from .common import (
    DEFAULT_UA,
    GROQ_TRANSCRIPT_ENDPOINT,
    GROQ_TRANSCRIPT_MODEL,
    build_multipart_formdata,
    ensure_dir,
    guess_audio_mime_type,
    is_retryable_error,
    log,
    retry_call,
    run_command,
    slugify,
    write_json,
    write_text,
)


def parse_iframe_video_sources(iframes):
    sources = []
    for iframe in iframes:
        src = iframe.get("src") or ""
        parsed = urllib.parse.urlparse(src)
        host = parsed.netloc.lower()
        video_id = None

        if "dailymotion.com" in host:
            query = urllib.parse.parse_qs(parsed.query)
            if "video" in query and query["video"]:
                video_id = query["video"][0]
            else:
                match = re.search(r"/(?:embed/)?video/([^/?&]+)", parsed.path)
                if match:
                    video_id = match.group(1)

        sources.append(
            {
                "provider": "dailymotion" if video_id else parsed.scheme or "unknown",
                "iframe_src": src,
                "title": iframe.get("title") or "",
                "video_id": video_id,
            }
        )
    return sources


def download_with_ytdlp(downloader, iframe_src, output_path, page_url, timeout_seconds, include_cookies=True):
    tool = shutil.which("yt-dlp")
    if not tool:
        raise RuntimeError("yt-dlp is not installed")
    command = [
        tool,
        "--referer",
        page_url,
        "--user-agent",
        DEFAULT_UA,
        "--no-playlist",
    ]
    if include_cookies:
        if getattr(downloader, "cookie_file", None):
            command.extend(["--cookies", downloader.cookie_file])
        elif getattr(downloader, "cookie_header", None):
            command.extend(["--add-header", f"Cookie: {downloader.cookie_header}"])
    else:
        command.append("--no-cookies")
    command.extend(["-o", output_path, iframe_src])
    run_command(command, timeout=timeout_seconds)


def download_videos_for_lesson(downloader, lesson_dir, page_url, parser, timeout_seconds, retries=3, retry_delay=2.0):
    ensure_dir(lesson_dir)
    sources = parse_iframe_video_sources(parser.iframes)
    downloaded = []

    for source_index, source in enumerate(sources, start=1):
        provider = source["provider"]
        source_title = source.get("title") or provider or f"video-{source_index}"
        video_slug = slugify(source_title, fallback=f"video-{source_index:02d}")
        target_base = os.path.join(lesson_dir, f"video-{source_index:02d}-{video_slug}")

        target_path = f"{target_base}.%(ext)s"
        matches = [name for name in os.listdir(lesson_dir) if name.startswith(os.path.basename(target_base) + ".")]
        if not matches:
            include_cookies = provider != "dailymotion"
            retry_call(
                lambda: download_with_ytdlp(
                    downloader,
                    source["iframe_src"],
                    target_path,
                    page_url,
                    timeout_seconds,
                    include_cookies=include_cookies,
                ),
                retries=retries,
                base_delay=retry_delay,
                should_retry=is_retryable_error,
                on_retry=lambda attempt, total, exc, delay: log(
                    f"[media] yt-dlp retry {attempt}/{total}: {exc} ({delay:.1f}s)",
                    level="WARNING",
                ),
            )
            matches = [name for name in os.listdir(lesson_dir) if name.startswith(os.path.basename(target_base) + ".")]
        if not matches:
            raise RuntimeError(f"Downloaded video file was not found for {source_title}")
        downloaded.append(
            {
                "provider": provider,
                "title": source_title,
                "iframe_src": source["iframe_src"],
                "video_id": source.get("video_id"),
                "file": sorted(matches)[0],
            }
        )

    return downloaded


def extract_audio_from_video(video_path, audio_path, timeout_seconds, clip_seconds=None):
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
    ]
    if clip_seconds:
        command.extend(["-t", str(clip_seconds)])
    command.extend(["-c:a", "libmp3lame", "-b:a", "64k", audio_path])
    run_command(command, timeout=timeout_seconds)


def groq_transcribe_audio(audio_path, api_key, model=GROQ_TRANSCRIPT_MODEL, timeout_seconds=600):
    fields = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    boundary, body = build_multipart_formdata(
        fields,
        file_field_name="file",
        file_path=audio_path,
        file_mime=guess_audio_mime_type(audio_path),
    )
    request = urllib.request.Request(
        GROQ_TRANSCRIPT_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": DEFAULT_UA,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset, errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Groq transcript request failed with HTTP {exc.code}: {body[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Groq transcript request failed: {exc}") from exc


def format_transcript_text(transcript_response):
    text = (transcript_response or {}).get("text") or ""
    return text.strip()


def save_transcript_files(base_path, transcript_response):
    text_path = f"{base_path}.transcript.txt"
    json_path = f"{base_path}.transcript.json"
    write_text(text_path, format_transcript_text(transcript_response) + "\n")
    write_json(json_path, transcript_response)
    return os.path.basename(text_path), os.path.basename(json_path)


def maybe_transcribe_video(
    video_path,
    api_key,
    transcript_timeout,
    audio_timeout,
    model=GROQ_TRANSCRIPT_MODEL,
    retries=3,
    retry_delay=2.0,
):
    base_path, _ = os.path.splitext(video_path)
    audio_path = f"{base_path}.audio.mp3"
    transcript_txt_path = f"{base_path}.transcript.txt"
    transcript_json_path = f"{base_path}.transcript.json"

    if os.path.exists(transcript_txt_path) and os.path.exists(transcript_json_path):
        with open(transcript_txt_path, "r", encoding="utf-8") as handle:
            transcript_text = handle.read().strip()
        return {
            "text": transcript_text,
            "audio_file": os.path.basename(audio_path) if os.path.exists(audio_path) else None,
            "transcript_text_file": os.path.basename(transcript_txt_path),
            "transcript_json_file": os.path.basename(transcript_json_path),
            "model": model,
        }

    if not os.path.exists(audio_path):
        retry_call(
            lambda: extract_audio_from_video(video_path, audio_path, timeout_seconds=audio_timeout),
            retries=retries,
            base_delay=retry_delay,
            should_retry=is_retryable_error,
            on_retry=lambda attempt, total, exc, delay: log(
                f"[transcript] audio extraction retry {attempt}/{total}: {exc} ({delay:.1f}s)",
                level="WARNING",
            ),
        )

    transcript_response = retry_call(
        lambda: groq_transcribe_audio(
            audio_path,
            api_key=api_key,
            model=model,
            timeout_seconds=transcript_timeout,
        ),
        retries=retries,
        base_delay=retry_delay,
        should_retry=is_retryable_error,
        on_retry=lambda attempt, total, exc, delay: log(
            f"[transcript] request retry {attempt}/{total}: {exc} ({delay:.1f}s)",
            level="WARNING",
        ),
    )
    transcript_text_file, transcript_json_file = save_transcript_files(base_path, transcript_response)
    return {
        "text": format_transcript_text(transcript_response),
        "audio_file": os.path.basename(audio_path),
        "transcript_text_file": transcript_text_file,
        "transcript_json_file": transcript_json_file,
        "model": model,
    }
