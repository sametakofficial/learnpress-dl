# learnpress-dl

Cookie-authenticated downloader for LearnPress-based course sites.

It supports:

- single-course runs when a URL is provided
- site-wide runs when no URL is provided
- site-wide course discovery from a configurable courses page
- recovery from old partial downloads
- `fast` and `deep` compare depths before downloading
- persisted `check` and `plan` files
- optional video download and optional transcript generation
- local-only failed lesson retries with `--retry-failed`
- optional timestamped run archives with `--zip-courses`

## Requirements

- Python 3.10+
- `ffmpeg`
- `yt-dlp` for non-Dailymotion embedded videos
- valid site cookies in Netscape cookie-file format or a raw `Cookie` header

## Environment Variables

Project env file: `.env`

Supported variables:

- `BASE_URL`
  - required for site-wide discovery mode
  - example: `https://www.example.com`
- `COURSES_PAGE`
  - relative or absolute courses archive path used for discovery
  - examples:
    - `kurslar/`
    - `site/kurslar/`
    - `proje/kurslar`
    - `/kurslar/`
- `GROQ_API_KEY`
  - only required when using `--download-transcripts`

Example `.env`:

```env
BASE_URL=https://www.yapayzekamaster.com
COURSES_PAGE=kurslar/
GROQ_API_KEY=your_groq_key_here
```

## Entry Point

Use the package entrypoint:

```bash
python3 -m learnpress_dl --help
```

## Windows Release Plan

For non-technical Windows users, the recommended distribution format is a portable release folder instead of a raw Python setup.

Portable release contents:

- `learnpress-dl.exe`
- `yt-dlp.exe`
- `ffmpeg.exe`
- `ffprobe.exe`
- `.env.example`
- `run.bat`
- `retry-failed.bat`

Windows packaging files live in `packaging/windows/`.

Important detail:

- the executable automatically looks for `yt-dlp.exe`, `ffmpeg.exe`, and `ffprobe.exe` next to itself
- this avoids asking end users to install those tools globally

## Docker Support

The project now includes `Dockerfile` and `docker-compose.yml` so it can run on Docker Desktop without installing Python, `ffmpeg`, or `yt-dlp` on the host.

Recommended host layout:

```text
learnpress-dl/
  .env
  docker-compose.yml
  runtime/
    cookies.txt
  downloads/
```

Quick start:

1. Copy `.env.example` to `.env` and fill in your values.
2. Put your Netscape cookie export at `runtime/cookies.txt`.
3. Run the default full downloader service:

```bash
docker compose up --build learnpress-dl
```

Default compose behavior:

- reads cookies from `/work/runtime/cookies.txt`
- writes output to `/work/downloads`
- enables video download, transcripts, fast check depth, and run-level zip archives
- includes a separate retry service with the same defaults

Retry only local failures with the built-in retry service:

```bash
docker compose up --build learnpress-dl-retry-failed
```

Run a single course:

```bash
docker compose run --rm learnpress-dl \
  --cookie-file /work/runtime/cookies.txt \
  --output-dir /work/downloads \
  --download-videos \
  --download-transcripts \
  --parallel 2 \
  --zip-courses \
  "https://www.example.com/courses/.../lessons/.../"
```

## Authentication

Use one of these:

- `--cookie-file /path/to/cookies.txt`
- `--cookie-header 'cookie_name=value; ...'`

## Common Usage

### Download one course

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  "https://www.example.com/courses/.../lessons/.../"
```

### Download one course with deep comparison

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --check-depth deep \
  "https://www.example.com/courses/.../lessons/.../"
```

### Download all discovered courses

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --download-videos \
  --download-transcripts
```

### Override the courses page path

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --base-url "https://example.com" \
  --courses-page "site/kurslar/" \
  --check-depth fast
```

### Download all discovered courses with deep comparison

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --check-depth deep \
  --download-videos \
  --download-transcripts
```

### Retry only locally failed lessons

This mode skips the normal compare/check flow. It reads saved local `progress.json` files and retries only lessons that have a failed overall status or a failed step.

Retry a single course output:

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --output-dir "downloads/course-dir" \
  --retry-failed \
  "https://www.example.com/courses/.../lessons/.../"
```

Retry every locally failed lesson under the downloads root:

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --output-dir "downloads" \
  --retry-failed
```

This flow:

1. discovers courses from `BASE_URL + COURSES_PAGE`
2. opens each course page
3. resolves the first lesson link from the first `a.course-item__link`
4. checks local state
5. generates course/site plans
6. skips completed courses
7. resumes only actionable courses

## Check Depths

- `--check-depth fast`
  - default
  - matches the remote LearnPress sidebar lesson/category structure against local course folders
  - fast and intended as the default preflight behavior
- `--check-depth deep`
  - deeper local validation mode
  - includes content file presence/length checks and local video/transcript artifact validation
  - slower than `fast`

Every run does discovery -> compare -> download. Compare depth only changes how strong the compare phase is.

### Download videos too

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --download-videos
```

### Download transcripts too

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --download-videos \
  --download-transcripts
```

## Important Flags

- `--check-depth fast|deep`
  - comparison depth used during stage 2
- `--base-url`
  - override `BASE_URL`
- `--courses-page`
  - override `COURSES_PAGE`
- `--download-videos`
  - download embedded videos for media lessons
- `--download-transcripts`
  - generate transcripts for downloaded videos
- `--retry-failed`
  - skip compare/check and retry only locally failed lessons from saved progress files
- `--zip-courses`
  - create one timestamped zip archive for the run output directory at the end of the run
- `--verbose`
  - enable debug logging
- `--quiet`
  - show warnings and errors only
- `--tree-progress` / `--no-tree-progress`
  - enable or disable the live tree UI during site-wide runs

## Recovery and Resume Behavior

The downloader keeps state in each course directory.

Used files:

- `state.json`
- per-lesson `progress.json`
- `manifest.json`
- `course-check.json`
- `course-plan.json`

The site-wide flow also writes:

- `downloads/site-check.json`
- `downloads/site-plan.json`

Current behavior:

- completed lessons are skipped
- missing lessons are planned as actionable
- failed lessons are planned for retry
- `--retry-failed` bypasses compare/check and only retries locally failed lessons
- transcript files are not regenerated unless the lesson still needs transcript work
- fast checks only compare sidebar lesson/category structure against local folders
- deep checks also validate local lesson file sizes and local video/transcript artifacts

## Archives

When `--zip-courses` is enabled, the downloader creates timestamped `.zip` archives at the end of the run.

- single-course runs archive that single course output directory
- site-wide runs archive the full run output directory once
- `--retry-failed` runs also archive the full run output directory once

## Logging

- default output uses concise `INFO` logs
- `--verbose` enables `DEBUG` logs for requests, retries, and parser decisions
- `--quiet` shows warnings and errors only
- user-facing logs are English-only and intended to be automation-friendly

## Bootstrap Behavior

Course bootstrap no longer uses any site-specific `Devam Et` button logic.

The downloader now treats the course entry lesson as:

- the first lesson URL found in the first `a.course-item__link` on the course page

This keeps the downloader generic for LearnPress sites instead of relying on custom theme buttons.

## Output Layout

```text
downloads/
  site-check.json
  site-plan.json
  <course-dir>/
    state.json
    manifest.json
    course-check.json
    course-plan.json
    01-section/
      01-lesson/
        lesson.html
        lesson.txt
        lesson.json
        progress.json
        video-01-....mp4
        video-01-....audio.mp3
        video-01-....transcript.txt
        video-01-....transcript.json
```

## Troubleshooting

- `Database Error` / `HTTP 500`
  - usually site-side instability; rerun later and resume from state
- no courses found during site-wide discovery
  - check cookies, `BASE_URL`, and `COURSES_PAGE`
- transcript failure
  - verify `GROQ_API_KEY`
- no tree UI visible
  - tree UI is mainly for interactive TTY download runs

## Current Status

The project is now positioned as a generic LearnPress downloader, not a site-specific downloader.

Project-only downloader docs now live in this README.
