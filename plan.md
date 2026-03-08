# Multi-Course Discovery, Check, and Progress UI Plan

## Goal

Extend the current single-course downloader into a resilient multi-course system for `yapayzekamaster.com` that:

- discovers all accessible courses from `/kurslar`
- enters each course page and resolves the `Devam Et` lesson URL
- reuses the current lesson/course pipeline instead of rewriting it
- performs a fast inventory/check pass before heavy downloading begins
- preserves existing downloaded videos, lesson files, and paid transcripts
- can report progress in a course -> category -> lesson tree view with meaningful statuses when useful

## Constraints

- avoid overengineering
- keep current CLI behavior working where practical
- do not regenerate valid transcript outputs
- do not redownload valid videos or lesson outputs
- keep recovery compatible with current `state.json`, `progress.json`, and migrated legacy outputs
- keep site pressure moderate and handle transient site-side `500` failures cleanly
- prioritize downloader correctness and resume behavior over terminal cosmetics

## Confirmed Inputs and Site Behavior

Current discovery assumptions are based on observed site behavior:

- base site URL: `https://www.yapayzekamaster.com`
- course index page: `https://www.yapayzekamaster.com/kurslar/`
- `/kurslar/` exposes the set of accessible course pages for the authenticated user
- each course page exposes a `Devam Et` button that links to a lesson URL inside that course
- the `Devam Et` lesson page can be used as the course start URL for the existing curriculum/lesson pipeline

This means the new multi-course flow can be built as a thin orchestration layer over the current downloader core.

## Desired User Experience

The main run should feel like this:

1. load config and cookies
2. discover accessible courses from `/kurslar`
3. run a fast check phase across all discovered courses
4. print a compact inventory of what is already complete vs missing
5. start download work only for courses/lessons that still need work
6. show live progress in a tree-like terminal view instead of only a linear progress bar

## Proposed Command Model

Keep current single-course entrypoints working, but add multi-course-aware modes.

Suggested direction:

- existing single-course mode remains supported when the input URL points directly to a lesson or course
- `BASE_URL` enables multi-course discovery by default when no explicit course URL is provided
- add a check-only mode
- add a download-all mode that runs discovery + check + download

Suggested CLI shape:

```text
python3 -m yzm_dl --check
python3 -m yzm_dl --all-courses
python3 -m yzm_dl --all-courses --check-only
python3 -m yzm_dl --url <course-or-lesson-url>
```

Exact flag names can be adjusted to fit current conventions, but the capability split should stay.

## Architecture Direction

Add orchestration around the current course runner instead of replacing it.

Recommended new layers:

- `site discovery`: discover courses from `/kurslar`
- `course bootstrap`: fetch a course page and resolve `Devam Et`
- `check/inventory`: inspect current local state and compare against remote course metadata
- `multi-course scheduler`: decide what to skip, check, resume, or download
- `terminal ui`: render current global state and active lesson statuses

The existing lesson parsing, media handling, rendering, and state logic should remain the execution core.

## Discovery Phase

### Step 1: Base URL Resolution

Use `BASE_URL` from env as the root for discovery.

Rules:

- normalize trailing slash handling
- derive `/kurslar/` from `BASE_URL`
- fail clearly if `BASE_URL` is missing in multi-course mode

### Step 2: Course Listing Discovery

Fetch `/kurslar/` with the authenticated session and parse all unique course links.

For each course listing entry, capture:

- course title
- course page URL
- slug
- optional summary metadata if available

Persist discovery results in a site-level cache file so check/download phases can reuse them.

Suggested file:

- `downloads/site-inventory.json`

### Step 3: Course Bootstrap via `Devam Et`

For each discovered course page:

1. fetch course page
2. parse the `Devam Et` button
3. extract the lesson URL
4. use that lesson URL as the effective course start URL

Also capture lightweight course metadata from the page when available:

- course title
- section count
- lesson count
- page URL
- continue URL

If `Devam Et` is missing but the course page is accessible, mark the course as `bootstrap_failed` and continue with the next course.

## New Check Phase

The check phase should be fast and much cheaper than a full download.

## Purpose

Before downloading, answer these questions:

- which courses are new locally?
- which known courses changed remotely?
- which categories or lessons are missing locally?
- which lessons are partially complete?
- which lessons are complete and can be skipped?

## Check Strategy

For each discovered course:

1. resolve course root folder
2. load local `state.json` if it exists
3. fetch enough remote data to rebuild the latest course outline
4. compare remote outline against local manifest/state/progress files
5. produce a normalized check result

The check phase should avoid expensive operations:

- no video downloads
- no audio extraction
- no transcript generation
- no full lesson rendering unless needed for repair mode

It may fetch course pages and lesson pages only when necessary to detect structure accurately.

## Check Output Model

Each course should produce a structured result such as:

```json
{
  "course_title": "...",
  "course_url": "...",
  "continue_url": "...",
  "status": "ready",
  "remote": {
    "section_count": 7,
    "lesson_count": 37
  },
  "local": {
    "section_count": 7,
    "lesson_count": 34,
    "completed_lessons": 30,
    "partial_lessons": 4,
    "missing_lessons": 3
  },
  "diff": {
    "new_sections": 0,
    "new_lessons": 3,
    "missing_video": 2,
    "missing_transcript": 1,
    "missing_render": 1
  }
}
```

Suggested persisted outputs:

- site-level: `downloads/site-check.json`
- course-level: `course-check.json`

## Download Decision Rules

Use check results to decide work.

Per course:

- `complete`: skip unless forced
- `partial`: enqueue only missing/incomplete lessons and steps
- `new`: enqueue full course
- `bootstrap_failed`: report clearly, skip for now
- `check_failed`: retry later or leave for manual review

Per lesson:

- if lesson outputs and valid transcript already exist, skip transcript generation
- if video exists and transcript is missing, enqueue transcript only
- if text outputs are missing, enqueue render/content steps only
- if lesson is new remotely, enqueue full lesson pipeline

## State Model Additions

Keep current course and lesson state, but add a site/global layer.

### Site-Level State

Suggested file:

- `downloads/site-state.json`

Suggested fields:

```json
{
  "schema_version": 1,
  "base_url": "https://www.yapayzekamaster.com",
  "discovered_courses": 9,
  "last_discovery_at": "...",
  "last_check_at": "...",
  "courses": [
    {
      "slug": "...",
      "title": "...",
      "course_url": "...",
      "continue_url": "...",
      "status": "partial"
    }
  ]
}
```

### Course-Level State Extensions

Add fields such as:

- `course_url`
- `continue_url`
- `check_status`
- `last_checked_at`
- `remote_section_count`
- `remote_lesson_count`
- `missing_lessons`
- `partial_lessons`

## Output Layout

Keep the current per-course output structure, but make it work cleanly for many courses.

Recommended direction:

- one stable root per course
- deterministic folder name derived from the course URL or slug
- site-level files stored once in `downloads/`

Example:

```text
downloads/
  site-state.json
  site-inventory.json
  site-check.json
  <course-a>/
    state.json
    course-check.json
    manifest.json
    ...
  <course-b>/
    state.json
    course-check.json
    manifest.json
    ...
```

## Terminal UI Plan

Replace or wrap the simple progress display with a global tree/status view.

## UI Goals

- show many courses at once without flooding the terminal
- reflect real execution states instead of only counts
- adapt to terminal height
- keep active work visible even when many lessons exist
- preserve a readable summary for completed and failed work

## Display Shape

Target hierarchy:

```text
Course A                         partial
  Category 1                     5/8
    Lesson 1                     finished
    Lesson 2                     fetching-content
    Lesson 3                     transcription
  Category 2                     2/6

Course B                         checking
  Category 1                     0/4
```

Recommended lesson statuses:

- `pending`
- `checking`
- `fetching-content`
- `fetching-materials`
- `fetching-video`
- `extracting-audio`
- `transcription`
- `rendering`
- `finished`
- `failed`
- `skipped`

## UI Rendering Rules

- reserve lines for global summary and active work
- fill remaining height with the most relevant tree slice
- prioritize currently active courses/categories/lessons
- keep recently completed items visible briefly when space allows
- collapse quiet/completed branches when the terminal is small
- redraw at a controlled interval to avoid flicker

## UI Data Source

Do not make the renderer scrape stdout text.

Instead, emit structured runtime events from the pipeline:

- `course_check_started`
- `course_check_completed`
- `course_download_started`
- `lesson_status_changed`
- `lesson_progress_changed`
- `lesson_completed`
- `lesson_failed`

The UI should render from an in-memory state model updated by these events.

## Reliability and Retry Rules

Because the site previously returned transient `500` errors, the multi-course system must stay conservative.

Rules:

- retry transient fetch/bootstrap/check failures with backoff and jitter
- separate course bootstrap retries from media retries
- do not block all courses because one course fails
- record failures in site-level and course-level state
- allow later reruns to resume from check results and existing progress

## Migration and Compatibility

Current single-course outputs must remain usable.

Rules:

- existing course directories remain valid
- existing `manifest.json`, `state.json`, and `progress.json` remain inputs to the new check logic
- old single-course runs should appear as already-known local courses when the corresponding course is discovered from `/kurslar`
- current wrapper and package entrypoint should keep working

## Implementation Order

1. add config support for `BASE_URL` and multi-course mode selection
2. implement `/kurslar` course discovery parser
3. implement course bootstrap parsing for `Devam Et`
4. add site-level state and inventory persistence
5. implement fast check/inventory phase
6. wire course-level decisions into the existing resumable pipeline
7. add structured runtime events for course and lesson status changes
8. build adaptive terminal tree renderer
9. add smoke tests for discovery, bootstrap, check diffing, and UI state reduction

## Test Plan

Add tests for the new behavior without requiring full downloads.

Suggested test coverage:

- parse course links from a saved `/kurslar` HTML fixture
- parse `Devam Et` link from a saved course page fixture
- map discovered course URLs to deterministic local folders
- compare remote/local lesson inventories accurately
- preserve completed transcript/video steps during check
- reduce a large runtime tree into a terminal-height-limited view
- keep single-course mode behavior intact

## Expected Result

After this phase:

- the downloader can discover all accessible courses automatically
- each course can bootstrap from its `Devam Et` lesson URL
- a fast check phase reports what is new, missing, partial, and complete
- download work resumes only where needed
- existing paid transcripts and downloaded videos remain untouched
- progress becomes understandable at a glance across all courses
