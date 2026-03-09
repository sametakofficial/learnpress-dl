import ast
import json
import os
import re
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
    resolve_tool_path,
    run_command,
    slugify,
    write_json,
    write_text,
)

# Quality preference for Canva video downloads (highest first)
_CANVA_QUALITY_ORDER = ["SOURCE", "1080P", "720P", "480P", "360P", "240P"]


def parse_iframe_video_sources(iframes):
    sources = []
    for iframe in iframes:
        src = iframe.get("src") or ""
        parsed = urllib.parse.urlparse(src)
        host = parsed.netloc.lower()
        video_id = None
        provider = parsed.scheme or "unknown"

        if "dailymotion.com" in host:
            query = urllib.parse.parse_qs(parsed.query)
            if "video" in query and query["video"]:
                video_id = query["video"][0]
            else:
                match = re.search(r"/(?:embed/)?video/([^/?&]+)", parsed.path)
                if match:
                    video_id = match.group(1)
            if video_id:
                provider = "dailymotion"
        elif "canva.com" in host:
            provider = "canva"

        sources.append(
            {
                "provider": provider,
                "iframe_src": src,
                "title": iframe.get("title") or "",
                "video_id": video_id,
            }
        )
    return sources


def download_with_ytdlp(
    downloader, iframe_src, output_path, page_url, timeout_seconds, include_cookies=True, include_referer=True
):
    tool = resolve_tool_path("yt-dlp")
    if tool == "yt-dlp":
        raise RuntimeError("yt-dlp is not installed")
    command = [
        tool,
        "--no-playlist",
        "--impersonate",
        "chrome",
        "--extractor-args",
        "generic:impersonate",
    ]
    if include_referer:
        command.extend(["--referer", page_url])
        command.extend(["--user-agent", DEFAULT_UA])
    if include_cookies:
        if getattr(downloader, "cookie_file", None):
            command.extend(["--cookies", downloader.cookie_file])
        elif getattr(downloader, "cookie_header", None):
            command.extend(["--add-header", f"Cookie: {downloader.cookie_header}"])
    else:
        command.append("--no-cookies")
    command.extend(["-o", output_path, iframe_src])
    run_command(command, timeout=timeout_seconds)


def _canva_fetch_page(embed_url, timeout_seconds=60):
    """Fetch a Canva embed page using curl_cffi to bypass Cloudflare."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        raise RuntimeError(
            "curl_cffi is required for Canva video downloads. "
            "Install it with: pip install curl_cffi"
        )

    resp = cffi_requests.get(embed_url, impersonate="chrome", timeout=timeout_seconds)
    if resp.status_code != 200:
        raise RuntimeError(f"Canva page returned HTTP {resp.status_code} for {embed_url}")
    return resp.text


def _canva_extract_bootstrap(html_text):
    """Extract and parse the bootstrap JSON from Canva embed HTML."""
    match = re.search(r"window\['bootstrap'\]\s*=\s*JSON\.parse\('(.+?)'\)", html_text)
    if not match:
        raise RuntimeError("Could not find bootstrap JSON in Canva page")
    raw = match.group(1)
    try:
        # Canva stores the bootstrap payload as a JavaScript string literal.
        # Decode that literal first, then normalize the JSON escapes that remain.
        unescaped = ast.literal_eval("'" + raw + "'")
        unescaped = unescaped.replace("\\'", "'").replace("\\/", "/")
        return json.loads(unescaped)
    except (SyntaxError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to parse Canva bootstrap JSON: {exc}") from exc


def _canva_extract_video_slides(bootstrap_data):
    """Extract video slide information from Canva bootstrap data.

    Returns a list of dicts, one per video slide, each containing:
      - title: slide title
      - duration: duration in seconds
      - width, height: resolution
      - files: list of {url, width, height, quality} dicts (pre-muxed MP4s)
      - has_audio: whether Canva exposes audio-backed media for the slide
    Only includes slides with contentType VIDEO and duration > 10 seconds
    (to skip short stock clip intros/transitions).
    """
    pages = bootstrap_data.get("page", {}).get("E", [])
    video_slides = []
    for page in pages:
        content_type = (page.get("contentType") or "").upper()
        duration = page.get("durationSeconds", 0) or 0
        if content_type != "VIDEO" or duration < 10:
            continue
        regular_files = page.get("files", [])
        if not regular_files:
            continue
        files = []
        for f_item in regular_files:
            if not isinstance(f_item, dict):
                continue
            url = f_item.get("url", "")
            if not url or not url.startswith("http"):
                continue
            files.append(
                {
                    "url": url,
                    "width": f_item.get("width", 0),
                    "height": f_item.get("height", 0),
                    "quality": f_item.get("quality", "UNKNOWN"),
                }
            )
        if files:
            video_sequence = len(video_slides) + 1
            video_slides.append(
                {
                    "sequence": video_sequence,
                    "title": page.get("title", ""),
                    "duration": duration,
                    "width": page.get("width", 0),
                    "height": page.get("height", 0),
                    "has_audio": bool(page.get("dashAudioFiles")),
                    "files": files,
                }
            )
    return video_slides


def _canva_pick_best_file(files):
    """Pick the best quality MP4 from a list of file dicts."""
    quality_rank = {q: i for i, q in enumerate(_CANVA_QUALITY_ORDER)}
    ranked = sorted(
        files,
        key=lambda f: (quality_rank.get(f.get("quality", "").upper(), 999), -(f.get("width", 0) * f.get("height", 0))),
    )
    return ranked[0] if ranked else None


def _canva_download_file(url, output_path, timeout_seconds=600):
    """Download a file from Canva CDN using curl_cffi for Cloudflare bypass."""
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        raise RuntimeError("curl_cffi is required for Canva video downloads")

    resp = cffi_requests.get(url, impersonate="chrome", timeout=timeout_seconds, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"Canva CDN returned HTTP {resp.status_code} for {url}")

    content_length = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(output_path, "wb") as handle:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if chunk:
                handle.write(chunk)
                downloaded += len(chunk)

    if content_length and downloaded < content_length * 0.95:
        os.remove(output_path)
        raise RuntimeError(
            f"Incomplete download: got {downloaded} bytes, expected {content_length}"
        )

    log(f"[canva] downloaded {downloaded / (1024 * 1024):.1f} MB → {os.path.basename(output_path)}", level="DEBUG")


def download_canva_videos(embed_url, lesson_dir, target_base, timeout_seconds=600):
    """Download video(s) from a Canva embed URL.

    Fetches the embed page, extracts video slide data, and downloads
    the best quality pre-muxed MP4 for each video slide.

    Returns a list of downloaded file basenames.
    """
    log(f"[canva] fetching embed page: {embed_url}", level="DEBUG")
    html_text = _canva_fetch_page(embed_url, timeout_seconds=min(timeout_seconds, 60))

    bootstrap = _canva_extract_bootstrap(html_text)
    video_slides = _canva_extract_video_slides(bootstrap)

    audio_backed_slides = [slide for slide in video_slides if slide.get("has_audio")]
    if audio_backed_slides:
        skipped_count = len(video_slides) - len(audio_backed_slides)
        if skipped_count:
            log(f"[canva] skipping {skipped_count} audio-less intro slide(s)", level="DEBUG")
        video_slides = audio_backed_slides

    if not video_slides:
        raise RuntimeError(f"No video content found in Canva presentation: {embed_url}")

    downloaded_files = []
    for slide_idx, slide in enumerate(video_slides):
        best = _canva_pick_best_file(slide["files"])
        if not best:
            log(f"[canva] slide {slide_idx}: no downloadable file found", level="WARNING")
            continue

        # If there's only one video slide, use the target_base directly.
        # If multiple, append a slide index suffix.
        if len(video_slides) == 1:
            out_path = f"{target_base}.mp4"
        else:
            out_path = f"{target_base}-part{slide.get('sequence', slide_idx + 1):02d}.mp4"

        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            log(f"[canva] already exists: {os.path.basename(out_path)}", level="DEBUG")
            downloaded_files.append(os.path.basename(out_path))
            continue

        quality = best.get("quality", "?")
        width = best.get("width", "?")
        height = best.get("height", "?")
        duration = slide.get("duration", 0)
        log(
            f"[canva] downloading slide {slide_idx + 1}/{len(video_slides)}: "
            f"{quality} {width}x{height}, {duration:.0f}s",
            level="INFO",
        )
        _canva_download_file(best["url"], out_path, timeout_seconds=timeout_seconds)
        downloaded_files.append(os.path.basename(out_path))

    if not downloaded_files:
        raise RuntimeError(f"Failed to download any video from Canva: {embed_url}")

    return downloaded_files


def download_videos_for_lesson(downloader, lesson_dir, page_url, parser, timeout_seconds, retries=3, retry_delay=2.0):
    ensure_dir(lesson_dir)
    sources = parse_iframe_video_sources(parser.iframes)
    downloaded = []

    for source_index, source in enumerate(sources, start=1):
        provider = source["provider"]
        source_title = source.get("title") or provider or f"video-{source_index}"
        video_slug = slugify(source_title, fallback=f"video-{source_index:02d}")
        target_base = os.path.join(lesson_dir, f"video-{source_index:02d}-{video_slug}")

        matches = [name for name in os.listdir(lesson_dir) if name.startswith(os.path.basename(target_base) + ".")]

        if provider == "canva":
            canva_files = retry_call(
                lambda: download_canva_videos(
                    source["iframe_src"],
                    lesson_dir,
                    target_base,
                    timeout_seconds=timeout_seconds,
                ),
                retries=retries,
                base_delay=retry_delay,
                should_retry=is_retryable_error,
                on_retry=lambda attempt, total, exc, delay: log(
                    f"[media] canva retry {attempt}/{total}: {exc} ({delay:.1f}s)",
                    level="WARNING",
                ),
            )
            for canva_file in canva_files:
                downloaded.append(
                    {
                        "provider": provider,
                        "title": source_title,
                        "iframe_src": source["iframe_src"],
                        "video_id": source.get("video_id"),
                        "file": canva_file,
                    }
                )
            continue

        if not matches:
            target_path = f"{target_base}.%(ext)s"
            is_dailymotion = provider == "dailymotion"
            retry_call(
                lambda: download_with_ytdlp(
                    downloader,
                    source["iframe_src"],
                    target_path,
                    page_url,
                    timeout_seconds,
                    include_cookies=not is_dailymotion,
                    include_referer=not is_dailymotion,
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
