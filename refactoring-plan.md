# Refactoring Plan

This plan is based on a local project review plus a GitHub CLI comparison against downloader tools such as `yt-dlp/yt-dlp` and `mikf/gallery-dl`.

## Current Scores

- Architecture: `6.5/10`
- CLI UX: `5.0/10`
- Reliability: `6.0/10`
- Maintainability: `5.5/10`
- Docs: `2.0/10` before `README.md`

## Main Findings

- the core is already modular, but the top-level CLI orchestration should stay thin
- single-course and all-courses behavior were drifting; planning/check behavior should stay shared
- persisted recovery/check/plan files are a strong foundation and should remain first-class
- parser and retry behavior still need careful hardening over time
- docs were missing and needed a proper root `README`
- UI polish should stay secondary; downloader correctness, resumability, and predictability come first

## Overengineering Guardrails

- do not build a framework around one downloader
- prefer small runner/service modules over abstract inheritance trees
- keep persisted plan/check files as plain JSON, not complex internal DSLs
- avoid adding transcript/video behaviors unless they are clearly needed and testable
- optimize for resumable downloads and understandable CLI behavior before cosmetic terminal output

## Phase 1 - CLI Contract Cleanup

- keep current flags working
- make single-course and all-courses flows use the same planning model
- make `--check` behavior consistent everywhere
- reduce surprises around which mode downloads and which mode only plans

Status: mostly completed.

Target files:

- `learnpress_dl/cli.py`
- `README.md`

## Phase 2 - Orchestration Split

- move high-level course/site execution out of `learnpress_dl/cli.py`
- create smaller runner modules for:
  - single-course execution
  - site-wide execution
  - plan/check generation
  - UI event wiring

Status: started with `learnpress_dl/course_runner.py` and `learnpress_dl/site_runner.py`; continue trimming orchestration overlap.

Target direction:

- `learnpress_dl/runner.py`
- `learnpress_dl/site_runner.py`
- `learnpress_dl/course_runner.py`

## Phase 3 - Reliability and Test Depth

- expand tests around:
  - parser drift fixtures
  - retry and failure behavior
  - lock handling
  - transcript/video state transitions
  - CLI integration behavior
- keep transcript API use minimal and test most logic locally with fixtures

Target files:

- `tests/test_cli_integration.py`
- `tests/test_media_state.py`
- existing parser/planner/inventory/ui tests
