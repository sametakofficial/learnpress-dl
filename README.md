# learnpress-dl

Cookie-authenticated downloader for LearnPress-based course sites.

It supports:

- `single` and `multi` run modes
- site-wide course discovery from a configurable courses page
- recovery from old partial downloads
- `fast` and `deep` compare depths before downloading
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

## Entry Point

Use the package entrypoint:

```bash
python3 -m learnpress_dl --help
```

## Authentication

Use one of these:

- `--cookie-file /path/to/cookies.txt`
- `--cookie-header 'cookie_name=value; ...'`

## Common Usage

### Single mode

```bash
python3 -m learnpress_dl \
  --run-mode single \
  --cookie-file "/path/to/cookies.txt" \
  "https://www.example.com/courses/.../lessons/.../"
```

### Single mode with deep compare

```bash
python3 -m learnpress_dl \
  --run-mode single \
  --cookie-file "/path/to/cookies.txt" \
  --check-depth deep \
  "https://www.example.com/courses/.../lessons/.../"
```

### Multi mode

```bash
python3 -m learnpress_dl \
  --run-mode multi \
  --cookie-file "/path/to/cookies.txt" \
  --download-videos \
  --download-transcripts
```

### Override the courses page path

```bash
python3 -m learnpress_dl \
  --run-mode multi \
  --cookie-file "/path/to/cookies.txt" \
  --base-url "https://example.com" \
  --courses-page "site/kurslar/" \
  --check-depth fast
```

### Multi mode with deep compare

```bash
python3 -m learnpress_dl \
  --run-mode multi \
  --cookie-file "/path/to/cookies.txt" \
  --check-depth deep \
  --download-videos \
  --download-transcripts
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
  --run-mode multi \
  --download-videos
```

### Download transcripts too

```bash
python3 -m learnpress_dl \
  --cookie-file "/path/to/cookies.txt" \
  --run-mode multi \
  --download-videos \
  --download-transcripts
```

## Important Flags

- `--run-mode single|multi`
  - choose tek kurs veya tum kurslar akisi
- `--check-depth fast|deep`
  - karsilastirma asamasi derinligi
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
- fast checks only compare sidebar lesson/category structure against local folders
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
- no courses found in `multi` mode
  - check cookies, `BASE_URL`, and `COURSES_PAGE`
- transcript failure
  - verify `GROQ_API_KEY`
- no tree UI visible
  - tree UI is mainly for interactive TTY download runs

## Current Status

The project is now positioned as a generic LearnPress downloader, not a site-specific downloader.

Project-only downloader docs now live in this README.
