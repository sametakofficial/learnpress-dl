# learnpress-dl

Cookie-authenticated downloader for LearnPress-based course sites.

It supports:

- single-course runs
- site-wide course discovery from a configurable courses page
- recovery from old partial downloads
- lightweight `--check` mode before downloading
- optional `--check-deep` mode for file/content/video validation
- persisted `check` and `plan` files
- optional video download and optional transcript generation

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

## Entry Points

Preferred:

```bash
python3 -m learnpress_dl --help
```

Wrapper scripts:

```bash
python3 learnpress_dl.py --help
python3 learnpress_course_downloader.py --help
```

## Authentication

Use one of these:

- `--cookie-file /path/to/cookies.txt`
- `--cookie-header 'cookie_name=value; ...'`

## Common Usage

### Check a single course without downloading

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --check \
  "https://www.example.com/courses/.../lessons/.../"
```

### Resume a single course

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  "https://www.example.com/courses/.../lessons/.../"
```

### Check all courses from the configured courses page

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses \
  --check
```

### Override the courses page path

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --base-url "https://example.com" \
  --courses-page "site/kurslar/" \
  --all-courses \
  --check
```

### Discover all courses only

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses \
  --discover-only
```

### Resume all courses

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses
```

This flow:

1. discovers courses from `BASE_URL + COURSES_PAGE`
2. opens each course page
3. resolves the first lesson link from the first `a.course-item__link`
4. checks local state
5. generates course/site plans
6. skips completed courses
7. resumes only actionable courses

## Check Modes

- `--check`
  - default shallow check
  - matches the remote LearnPress sidebar lesson/category structure against local course folders
  - fast and intended as the default preflight behavior
- `--check-deep`
  - deeper local validation mode
  - includes content file presence/length checks and local video/transcript artifact validation
  - slower than `--check`

Normal non-check runs also use the shallow check/planning model by default.

### Download videos too

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses \
  --download-videos
```

### Download transcripts too

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses \
  --download-videos \
  --download-transcripts
```

## Important Flags

- `--check`
  - inspect and plan only, no download; shallow mode
- `--check-deep`
  - inspect and plan only, no download; deeper local file validation
- `--all-courses`
  - run site-wide mode using `BASE_URL` and `COURSES_PAGE`
- `--discover-only`
  - discovery/bootstrap only, no planning/download
- `--base-url`
  - override `BASE_URL`
- `--courses-page`
  - override `COURSES_PAGE`
- `--download-videos`
  - download embedded videos for media lessons
- `--download-transcripts`
  - generate transcripts for downloaded videos
- `--tree-progress` / `--no-tree-progress`
  - enable or disable the live tree UI for multi-course download runs

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
- transcript files are not regenerated unless the lesson still needs transcript work
- shallow checks only compare sidebar lesson/category structure against local folders
- deep checks also validate local lesson file sizes and local video/transcript artifacts

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
- no courses found in `--all-courses`
  - check cookies, `BASE_URL`, and `COURSES_PAGE`
- transcript failure
  - verify `GROQ_API_KEY`
- no tree UI visible
  - tree UI is mainly for interactive TTY download runs

## Current Status

The project is now positioned as a generic LearnPress downloader, not a site-specific downloader.

Project-only downloader docs now live in this README.
