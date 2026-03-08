# yapayzekamaster-dl

Cookie-authenticated downloader for `yapayzekamaster.com` LearnPress courses.

It supports:

- single-course runs
- all-courses discovery from `/kurslar/`
- recovery from old partial downloads
- lightweight `check` mode before downloading
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
  - example: `https://www.yapayzekamaster.com`
- `GROQ_API_KEY`
  - only required when using `--download-transcripts`
  - not used in plain `check` mode or plain content-only runs

Example `.env`:

```env
BASE_URL=https://www.yapayzekamaster.com
GROQ_API_KEY=your_groq_key_here
```

## Main Entry Points

Preferred:

```bash
python3 -m yzm_dl --help
```

Compatibility wrapper:

```bash
python3 learnpress_course_downloader.py --help
```

## Authentication

Use one of these:

- `--cookie-file /path/to/cookies.txt`
- `--cookie-header 'cookie_name=value; ...'`

The tool requires one of them for all real runs.

## Common Usage

### 1. Check a single course without downloading

```bash
python3 -m yzm_dl \
  --cookie-file "/path/to/cookies.txt" \
  --check \
  "https://www.yapayzekamaster.com/courses/.../lessons/.../"
```

This:

- reads the course curriculum
- recovers old local state if present
- writes `course-check.json`
- writes `course-plan.json`
- does not download anything

### 2. Resume a single course

```bash
python3 -m yzm_dl \
  --cookie-file "/path/to/cookies.txt" \
  "https://www.yapayzekamaster.com/courses/.../lessons/.../"
```

If the course output directory already exists, the run resumes from local state.

### 3. Check all courses from `/kurslar/`

```bash
python3 -m yzm_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses \
  --check
```

This uses `BASE_URL` from `.env` unless `--base-url` is provided.

Outputs:

- `downloads/site-check.json`
- `downloads/site-plan.json`
- `<course>/course-check.json` for existing local course dirs
- `<course>/course-plan.json` for existing local course dirs

### 4. Discover all courses only

```bash
python3 -m yzm_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses \
  --discover-only
```

This prints discovered courses and their `Devam Et` bootstrap links.

### 5. Resume all courses

```bash
python3 -m yzm_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses
```

This flow:

1. discovers courses from `/kurslar/`
2. resolves each course's `Devam Et` lesson URL
3. checks local state
4. generates course/site plans
5. skips completed courses
6. resumes only actionable courses

### 6. Download videos too

```bash
python3 -m yzm_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses \
  --download-videos
```

### 7. Download transcripts too

```bash
python3 -m yzm_dl \
  --cookie-file "/path/to/cookies.txt" \
  --all-courses \
  --download-videos \
  --download-transcripts
```

Notes:

- transcripts are only attempted when `--download-transcripts` is set
- `GROQ_API_KEY` must exist for transcript runs
- existing transcript files are preserved and reused by the planner/check logic

## Important Flags

- `--check`
  - inspect and plan only, no download
- `--all-courses`
  - run site-wide mode using `/kurslar/`
- `--discover-only`
  - discovery/bootstrap only, no planning/download
- `--base-url`
  - override `BASE_URL`
- `--download-videos`
  - download embedded videos for media lessons
- `--download-transcripts`
  - generate transcripts for downloaded videos
- `--tree-progress` / `--no-tree-progress`
  - enable or disable the live tree UI for multi-course download runs
- `--limit N`
  - limit lessons in single-course runs
- `--mode auto|curriculum|next`
  - lesson traversal strategy

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

Old partial downloads are recovered by scanning existing lesson folders and manifests.

Current behavior:

- completed lessons are skipped
- missing lessons are planned as actionable
- failed lessons are planned for retry
- transcript files are not regenerated unless the lesson still needs transcript work

## Output Layout

Typical structure:

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

## Current Planning Model

`course-plan.json` contains lesson actions such as:

- `skip_complete`
- `new_lesson`
- `retry_failed`
- `fetch_content`
- `download_needed`
- `transcribe_only`
- `repair_metadata`

Course-level statuses currently include:

- `complete`
- `resume_needed`
- `recovery_needed`
- `new`
- `bootstrap_failed`

## Troubleshooting

- `Database Error` / `HTTP 500`
  - this is usually site-side instability; rerun later and resume from state
- no courses found in `--all-courses`
  - check cookies and membership access
- transcript failure
  - verify `GROQ_API_KEY`
  - verify the video file actually exists
- no tree UI visible
  - tree UI is mainly for interactive TTY download runs
  - `--check` and non-interactive runs use summary output instead

## Current Status

The project is functional and already supports recovery/check/planning, but it is still under active refactoring.

See `refactoring-plan.md` for the next cleanup phases.
