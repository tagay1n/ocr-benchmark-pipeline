# PROJECT CONTEXT

Last updated: 2026-02-19

## Mission

Build a practical OCR benchmark pipeline for document images.
Initial target is Tatar, but repository design must stay language-neutral so volunteers can reuse it for other languages.

## Core Pipeline

1. Discover images from a source folder and index them in SQLite.
2. Detect layout regions (target model: `hantian/yolo-doclaynet`).
3. Manually review/edit layout boxes, classes, and reading order.
4. Extract text for text-capable regions (Gemini) into markdown/html/latex.
5. Manually validate extracted text against source image regions.

## Confirmed Product Requirements

- Friendly web UI for annotators/reviewers.
- Dashboard with pipeline state for all pages.
- Layout review should support:
  - visible boxes on original image
  - bbox editing
  - class editing
  - reading-order editing
  - remove layout
  - redetect action with parameters
- OCR review should support:
  - image panel + extracted markdown panel
  - raw markdown and rendered markdown views
  - manual correction before final state

## Stack Decisions (Current)

- Backend: FastAPI (Python monolith).
- DB: SQLite by default.
- Frontend: server-hosted static pages (incrementally evolving UI).
- Config: `config.yaml` with optional environment overrides.
- Discovery defaults:
  - source folder: `input`
  - deep recursive scan: enabled
  - allowed image formats: `.jpg .jpeg .png .tif .tiff .webp`

## Current Implementation Status

### Completed

- Discovery V1:
  - deep scan from configurable source directory
  - SHA-256 dedupe with canonical path tracking
  - missing-file marking
  - auto-scan on app startup
  - auto-scan on dashboard load
  - manual scan endpoint/button
- Dashboard V1:
  - indexed pages list
  - stats (total, missing, duplicates)
  - duplicate warnings that persist until duplicates are removed
  - wipe DB state action with typed confirmation (`wipe`) in modal
  - collapsible left sidebar with pipeline-stage tabs
  - includes explicit `Discovery` tab as full indexed-documents overview
  - each stage tab shows pending count in parentheses
  - stage tables show all historical docs that have reached the selected stage
  - stage tabs become green when pending count is `0`
  - zero-pending tabs remain clickable and show stage empty-state content
  - page table is filtered by selected pipeline stage
- Layout Review V1 backend+UI scaffold:
  - `layouts` table and indexes
  - layout CRUD API
  - per-page layout listing
  - page image endpoint
  - redetect endpoint (DocLayNet integration on CPU)
  - mark-layout-review-complete endpoint
  - `layouts.html` page to view/edit layouts
  - redetect thresholds (confidence/IoU) editable in UI

### Not Completed Yet

- Drag-and-resize bbox handles in UI (current editing is coordinate-input based).
- OCR extraction stage (Gemini) and post-processing.
- OCR review page with markdown raw/rendered dual mode.
- Job queue for long-running tasks.
- Migrations with Alembic.

## API Snapshot (As Of 2026-02-16)

- `POST /api/discovery/scan`
- `POST /api/state/wipe`
- `GET /api/pages`
- `GET /api/pages/{page_id}`
- `GET /api/pages/{page_id}/image`
- `GET /api/pages/{page_id}/layouts`
- `POST /api/pages/{page_id}/layouts/detect`
- `POST /api/pages/{page_id}/layouts`
- `PATCH /api/layouts/{layout_id}`
- `DELETE /api/layouts/{layout_id}`
- `POST /api/pages/{page_id}/layouts/review-complete`
- `GET /api/duplicates`
- `GET /api/stats`

## Data Snapshot (Current Tables)

- `pages`: discovered source images and pipeline status.
- `duplicate_files`: duplicate source-path tracking by content hash.
- `layouts`: region boxes/classes/order per page.

## Conventions For Future Updates

- Update this file on every meaningful product/architecture/code change.
- Add a short dated log entry in `## Change Log`.
- Keep this document factual and implementation-oriented.

## Change Log

- 2026-02-19:
  - Added reusable backend pipeline runtime (`app/pipeline_runtime.py`) for long-running stage jobs:
    - generic queued/running/completed/failed job model (`pipeline_jobs` table)
    - stage-agnostic event stream (`pipeline_events` table)
    - handler registry for future stages (prepared for later Gemini/OCR integration, not implemented yet)
  - Enabled automatic layout detection enqueue after discovery scans/startup/wipe rescan:
    - pages move through `new -> layout_detecting -> layout_detected`
    - failures roll back page status to `new` for later retry
  - Added backend activity visibility endpoint: `GET /api/pipeline/activity`.
  - Added live backend activity SSE endpoint: `GET /api/pipeline/activity/stream`.
  - Dashboard now shows live backend pipeline activity panel:
    - active job
    - queue counts
    - recent events across discovery/layout/review/pipeline actions
    - data pushed by SSE stream with automatic reconnect
    - panel is expandable/collapsible with collapsed-by-default behavior
  - Dashboard stats summary panel (`Total Indexed Pages`, `Missing Pages`, duplicates stat) is now shown only in `Discovery` stage view.
  - `Scan Input Folder` action moved into Discovery stats panel, so scan action appears only in Discovery view.
  - UI state persistence added across refresh:
    - dashboard remembers selected stage, sidebar collapsed state, and activity-panel expanded state
    - layout review remembers sidebar collapsed state and redetect threshold inputs (confidence/IoU)
  - Removed separate `Layout Detection` sidebar stage (layout detection is now automatic).
  - Sidebar is now present on both dashboard and layout review pages with consistent collapse/expand behavior.
  - Added config flag `enable_background_jobs` (`ENABLE_BACKGROUND_JOBS`) to control worker execution.
  - Sidebar toggle icon now uses deterministic glyph chevrons (`‹` / `›`) on dashboard/layout pages for reliable rendering.
  - Added automated tests for pipeline stages:
    - backend unit tests (`tests/test_pipeline_stages.py`) for discovery scan, layout detection, and layout review completion flows
    - frontend unit tests (`frontend_tests/pipeline_stages.test.mjs`) for stage filtering and pending-count logic
  - Extracted shared stage logic into `app/static/js/pipeline_stages.mjs` for reuse and testability.
  - Updated UI titles to remove `OCR Benchmark Pipeline` wording from dashboard page title/header.
  - Made left pipeline sidebar visible on layout review page (`app/static/layouts.html`) with:
    - collapsible state
    - deterministic glyph chevron toggle (`‹` / `›`)
    - stage tabs and pending counts shared with dashboard
  - Layout review class field now uses a known-classes dropdown for edits (instead of free text).
  - Class dropdown styling now updates immediately on selection change to match class color.
- 2026-02-16:
  - Recovered prior session context from local Codex session logs after folder rename.
  - Added persistent project context file (`PROJECT_CONTEXT.md`).
  - Switched project config format from JSON to YAML (`config.yaml`) and updated loader/docs.
  - Renamed app UI/API title text to language-neutral `OCR Benchmark Pipeline`.
  - Added confirmed wipe-state flow:
    - backend endpoint `POST /api/state/wipe`
    - dashboard danger button with modal requiring typed `wipe`
    - optional immediate rescan after wipe
    - fixed modal visibility bug by enforcing `.modal-backdrop[hidden] { display: none; }`
  - Replaced placeholder layout detector with real DocLayNet integration:
    - `hantian/yolo-doclaynet` checkpoint (`yolov10b-doclaynet.pt`) via Ultralytics
    - normalized bbox + class/confidence persistence in `layouts`
    - threshold controls (confidence/IoU) wired from layout review UI
    - class-based muted color rendering for layout bbox + labels on review canvas
    - class color legend on layout review page
    - class edit field switched to known-class dropdown for reviewer edits
  - Fixed stale-image issue in layout review:
    - page image URLs now include file mtime cache-busting token
    - `/api/pages/{id}/image` responses set no-cache headers
  - Implemented dashboard pipeline-stage tab navigation:
    - collapsible left sidebar
    - stage-level pending counts in tab labels
    - green state for completed stages (`0` pending)
    - zero-pending tabs stay interactive and open stage content/empty state
    - stage-based table filtering
  - Implemented Layout Review V1 scaffold:
    - backend layout schema and endpoints
    - page-image endpoint
    - layout review UI page (`app/static/layouts.html`)
    - dashboard links from page list to layout review screen
