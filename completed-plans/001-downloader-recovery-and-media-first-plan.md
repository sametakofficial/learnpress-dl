# Downloader Recovery and Media-First Plan

## Current State Analysis

The current run already produced valuable outputs that must not be lost or regenerated unnecessarily.

Observed state from the current course output:

- course structure discovered correctly: `7` sections, `37` lessons
- currently saved lessons: `9`
- saved text-only lessons: `1`
- saved video lessons: `8`
- saved transcripts: `8`
- missing core lesson files among saved lessons: `0`

This means the next system must treat the current output as canonical recoverable data, not as disposable partial output.

## Non-Negotiable Requirement

Already generated transcripts are expensive and must never be regenerated unless explicitly forced.

Rules:

- if transcript text and transcript json exist, they are preserved
- if video exists, do not redownload it
- if audio extract exists, do not recreate it unless invalid
- if lesson html/txt/json exist but need new rendering, rerender using existing local assets

## Main Goal

Build a crash-tolerant downloader that:

- resumes from previous progress automatically
- performs a one-time migration of the current output into the new progress model
- prioritizes text lessons first for speed
- processes video lessons after classification
- preserves existing video and transcript artifacts

## New Execution Model

The run should be split into two major phases.

### Phase 1: Discovery and Classification

For the full course:

1. discover all sections and lessons
2. classify each lesson into one of these buckets:
   - `text`
   - `video`
   - `text+video`
   - `other`
   - `unknown`
3. persist the classification before heavy downloads begin

Classification signals:

- `text`: lesson content html exists
- `video`: iframe/media source exists
- `text+video`: both exist
- `other`: future bucket for downloadable files, embeds, slides, attachments, etc.

### Phase 2: Priority Processing

Processing order should be:

1. text-only lessons first, concurrently
2. text+video lessons second
3. video-only lessons after that
4. other/unknown lessons last

Reasoning:

- text pages are cheap and fast
- fast wins make manifest and progress state richer early
- heavy media work starts only after the cheap part is done
- this reduces the chance of spending most runtime on media before basic course capture finishes

## Media Scheduling Policy

Text stage:

- concurrent workers can process text-only lessons
- safe work in this stage:
  - page fetch
  - materials fetch
  - lesson html render
  - lesson txt render
  - lesson json write

Media stage:

- process video downloads sequentially by default
- after a video is successfully stored, transcript can run immediately for that same lesson
- keep transcript tied to the local video that was just validated

Recommended default policy:

- `text_workers > 1`
- `media_workers = 1`
- `transcript_workers = 1`

This keeps media pressure low and avoids overloading either the source website or the transcript API.

## One-Time Recovery Plan for Existing Output

The current output must be migrated into the new progress system exactly once.

### Recovery Source

Use these existing artifacts as the source of truth:

- current `manifest.json`
- existing section and lesson folders
- existing `lesson.html`, `lesson.txt`, `lesson.json`
- existing `video-*.mp4`
- existing `video-*.audio.mp3`
- existing `video-*.transcript.txt`
- existing `video-*.transcript.json`

### Recovery Objective

Convert current saved lessons into the new lesson progress format without redownloading or retranscribing them.

### Recovery Rules

For each existing lesson folder:

1. load current `lesson.json`
2. verify core files exist and are non-empty
3. infer completed steps from files already present
4. generate new `progress.json`
5. add the lesson to course-level `state.json`

Step inference examples:

- `lesson.html` exists -> `render_html = completed`
- `lesson.txt` exists -> `render_text = completed`
- `lesson.json` exists and parses -> `write_json = completed`
- `video-*.mp4` exists -> `video_download = completed`
- `video-*.audio.mp3` exists -> `audio_extract = completed`
- `video-*.transcript.txt` and `video-*.transcript.json` exist -> `transcript = completed`

If a recovered lesson has all required outputs, mark it `completed` immediately.

### Recovery Scope

Recovery is one-time migration logic only.

After migration:

- future runs should use only the new progress model
- current legacy-only assumptions should no longer drive control flow

## New State Model

### Course-Level `state.json`

Store in course root.

Suggested fields:

```json
{
  "course_title": "...",
  "start_url": "...",
  "status": "in_progress",
  "schema_version": 2,
  "created_at": "...",
  "updated_at": "...",
  "section_count": 7,
  "lesson_count": 37,
  "classified": {
    "text": 0,
    "video": 0,
    "text+video": 0,
    "other": 0,
    "unknown": 0
  },
  "completed_lessons": 0,
  "failed_lessons": 0,
  "recovered_lessons": 0
}
```

### Lesson-Level `progress.json`

Store in each lesson folder.

Suggested fields:

```json
{
  "lesson_url": "...",
  "title": "...",
  "classification": "video",
  "status": "pending",
  "source": "fresh_or_recovered",
  "steps": {
    "page_fetch": "pending",
    "materials_fetch": "pending",
    "video_download": "pending",
    "audio_extract": "pending",
    "transcript": "pending",
    "render_html": "pending",
    "render_text": "pending",
    "write_json": "pending",
    "finalize": "pending"
  },
  "retries": {},
  "last_error": null,
  "updated_at": "..."
}
```

## Lesson Pipeline

Every lesson should follow this pipeline:

1. `page_fetch`
2. `materials_fetch`
3. `classify`
4. `video_download`
5. `audio_extract`
6. `transcript`
7. `render_html`
8. `render_text`
9. `write_json`
10. `finalize`

Rules:

- if no video exists, mark media steps as `skipped`
- if transcript generation is disabled, mark transcript step as `skipped`
- if transcript files already exist, transcript step is `completed`
- if files exist but html/txt need to be regenerated under the new renderer, rerender only those outputs

## Atomic Writes

All new writes should use temp files first.

Examples:

- `lesson.html.part` -> `lesson.html`
- `lesson.txt.part` -> `lesson.txt`
- `lesson.json.part` -> `lesson.json`
- `progress.json.part` -> `progress.json`
- `state.json.part` -> `state.json`
- `video-01.mp4.part` -> `video-01.mp4`
- `video-01.transcript.txt.part` -> `video-01.transcript.txt`

This prevents half-written files from being treated as valid progress.

## Resume Logic

On startup:

1. resolve output directory
2. load course `state.json` if it exists
3. if no new state exists but legacy `manifest.json` exists, run one-time recovery
4. scan lesson folders and validate outputs
5. rebuild the work queue from incomplete steps only

Examples:

- video exists, transcript missing -> run transcript + rerender only
- transcript exists, lesson html outdated -> rerender only
- html/json exist, but lesson never finalized -> finalize only
- `.part` file exists -> discard or reprocess that step

## Validation Rules

Before marking a step complete, validate:

- html/txt/json exist and are non-empty
- json parses
- video exists and size is above threshold
- audio exists and size is above threshold
- transcript text exists and is not blank
- transcript json parses

Transcript validation is especially important because those results are paid outputs.

## Retry and Backoff

Retry recoverable failures only:

- timeouts
- connection resets
- transient `5xx`
- `429`

Suggested policy:

- 3 to 5 retries per step
- exponential backoff
- jitter

Important nuance:

- transcript retries must not happen if a valid transcript file already exists
- video retries must not happen if a valid video file already exists

## Failure Handling

Per lesson:

- write `last_error`
- mark current step `failed`
- continue with next queued work item

Per run:

- keep course status `in_progress` until all lessons are either `completed`, `failed`, or intentionally `skipped`
- final summary should clearly show completed vs failed vs remaining

## Locking

Add a course-root lock file:

- `download.lock`

Behavior:

- create at start
- remove on clean exit
- if stale, recover after PID/process validation

This prevents simultaneous runs from corrupting the same progress state.

## Manifest Role After Refactor

Separate human-facing manifest from runtime state.

- `manifest.json`: clean content map for the user
- `state.json`: machine state for resume/recovery
- `progress.json`: per-lesson progress

The manifest should never be the only source for runtime control anymore.

## Logging and Event Journal

Keep both:

- readable log output
- machine-readable event stream

Recommended file:

- `events.jsonl`

Useful event types:

- `lesson_discovered`
- `lesson_recovered`
- `lesson_classified`
- `step_started`
- `step_completed`
- `step_failed`
- `lesson_completed`

## Implementation Order

1. add classification layer
2. add course `state.json` and lesson `progress.json`
3. add one-time legacy recovery from current outputs
4. add atomic file writes
5. add validation helpers
6. add resume scanner
7. add media-first scheduling
8. add retry/backoff
9. add lock file and event journal

## Expected Result

After this refactor:

- existing 8 paid transcripts remain preserved
- existing videos remain preserved
- recovered lessons enter the new system as already completed work
- the downloader resumes only the missing lessons and missing steps
- text lessons finish fast first
- media lessons continue afterward in a controlled sequence

## Refactoring Plan

The current implementation is now a large single-file script and should be refactored before the next round of feature growth.

Current size snapshot:

- main script line count: about `1481`
- top-level functions: `47`

At this size, keeping everything in one file will make resume logic, migration logic, scheduling, and tests harder to maintain.

### Research Notes from Similar Repositories

I reviewed two reference repositories with `gh`:

- `yt-dlp/yt-dlp`
- `rkwyu/scribd-dl`

Key structural lessons:

#### `yt-dlp`

Relevant package layout:

- `yt_dlp/extractor`
- `yt_dlp/downloader`
- `yt_dlp/postprocessor`
- `yt_dlp/networking`
- `yt_dlp/utils`
- `yt_dlp/options.py`
- `test/...`

Useful takeaways:

- responsibilities are separated by concern, not by arbitrary layer names
- extraction, download, post-processing, networking, and utilities are split apart cleanly
- tests mirror important subsystems separately
- there is still a central orchestrator, but subsystems are modular

#### `scribd-dl`

Relevant source layout:

- `src/service`
- `src/utils`
- `src/object`
- `src/const`
- `test/...`

Useful takeaways:

- even a much smaller downloader project benefits from `service` + `utils` separation
- config and object/model concerns are separated from execution logic

### Refactoring Goal

Refactor into a small, practical package layout that keeps the CLI simple but moves domain logic into focused modules.

Important constraint:

- avoid overengineering
- do not create empty abstraction layers just to look enterprise
- split only along real responsibility boundaries already present in the code

## Proposed Project Structure

Recommended target layout:

```text
yapayzekamaster-dl/
  .env
  .env.example
  plan.md
  README.md
  pyproject.toml
  downloads/
  logs/
  tests/
  yzm_dl/
    __init__.py
    __main__.py
    cli.py
    config.py
    logging_utils.py
    models.py
    paths.py
    state/
      __init__.py
      course_state.py
      lesson_progress.py
      recovery.py
      locking.py
    network/
      __init__.py
      http.py
      retry.py
      cookies.py
      groq.py
    parsers/
      __init__.py
      lesson_page.py
      curriculum.py
      materials.py
    media/
      __init__.py
      dailymotion.py
      downloader.py
      audio.py
      transcript.py
    render/
      __init__.py
      lesson_html.py
      lesson_text.py
      manifest.py
    pipeline/
      __init__.py
      classify.py
      scheduler.py
      lesson_runner.py
      course_runner.py
    utils/
      __init__.py
      fs.py
      text.py
      time.py
```

## Module Responsibilities

### `cli.py`

- argparse only
- option normalization
- handoff to `course_runner`

### `config.py`

- env loading
- defaults
- runtime options object
- output root derivation

### `models.py`

- lightweight dataclasses or typed structures for:
  - course metadata
  - section metadata
  - lesson metadata
  - video asset
  - transcript asset
  - lesson classification

### `paths.py`

- section folder naming
- lesson folder naming
- course root naming
- canonical file naming helpers

### `state/*`

- course state read/write
- per-lesson progress read/write
- migration from current legacy output
- lock file handling

### `network/*`

- generic HTTP requester
- retry/backoff wrapper
- cookie file/header support
- Groq transcription client

### `parsers/*`

- current HTML parsing logic
- curriculum extraction
- lesson page parsing
- materials extraction

### `media/*`

- Dailymotion resolution
- video download logic
- audio extraction
- transcript orchestration

This mirrors the `extractor/downloader/postprocessor/networking` separation seen in `yt-dlp`, but scaled down to fit this project.

### `render/*`

- lesson html renderer
- lesson txt renderer
- manifest generation

### `pipeline/*`

- classify lessons into `text`, `video`, `text+video`, `other`, `unknown`
- schedule work in the desired order
- run per-lesson step pipeline
- orchestrate the full course

### `utils/*`

- small shared helpers only
- avoid dumping domain logic here

## What Should Not Be Split Yet

To avoid overengineering, do **not** introduce these yet unless truly needed:

- plugin system
- dependency injection container
- database layer
- queue broker
- multi-process worker framework
- site-specific subpackages beyond current needs

The project needs modularity, not a platform rewrite.

## Recommended Refactoring Sequence

Refactor in safe slices so behavior stays stable.

### Stage 1: Package Bootstrap

- create `yzm_dl/`
- move CLI bootstrap into `cli.py`
- keep behavior unchanged

### Stage 2: Pure Utility Extraction

- move text helpers to `utils/text.py`
- move file helpers to `utils/fs.py`
- move path builders to `paths.py`

Low-risk extraction first.

### Stage 3: Parsing Split

- move current lesson/curriculum/material parsing into `parsers/*`
- keep parser behavior identical

### Stage 4: Media Split

- move Dailymotion, video download, audio extraction, transcript functions into `media/*`
- move Groq HTTP logic into `network/groq.py`

### Stage 5: State Split

- add `state.json` and `progress.json`
- implement one-time recovery module
- move manifest-independent runtime control here

### Stage 6: Pipeline Split

- introduce lesson classification
- add media-first scheduler
- separate text phase from media phase

### Stage 7: Tests

Add tests that mirror the subsystem split.

Suggested test layout:

```text
tests/
  test_paths.py
  test_curriculum_parser.py
  test_lesson_parser.py
  test_media_dailymotion.py
  test_transcript_formatting.py
  test_recovery.py
  test_state_resume.py
  test_scheduler.py
```

## Refactoring Rules

While refactoring:

- keep one public entrypoint
- keep current CLI flags working unless intentionally migrated
- preserve output compatibility where possible
- preserve already-downloaded assets
- prefer moving code before rewriting code
- add regression tests around parsing and recovery before deep pipeline changes

## Architecture Direction After Refactor

The architecture should become:

- `cli` starts the run
- `config` resolves runtime options
- `course_runner` discovers and classifies lessons
- `scheduler` orders text and media work
- `lesson_runner` executes resumable step pipelines
- `state` persists progress and recovery
- `parsers`, `media`, `network`, and `render` remain focused subsystems

This gives the project a cleaner downloader architecture without turning it into an overbuilt framework.
