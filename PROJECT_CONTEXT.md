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
  - dashboard refresh does not auto-scan; scanning is manual via `Scan` button
  - manual scan endpoint/button
- Dashboard V1:
  - single dashboard view with all indexed pages (no stage sidebar/tabs)
  - removed standalone stats panel (`Total Indexed Pages`, `Missing Pages`, `Active Duplicate Files`)
  - duplicate warnings that persist until duplicates are removed
  - header actions: `Scan`, `Review layouts`, `Wipe DB State`
  - header actions are rendered under title; pipeline flow is shown as `Scan > Review layouts`
  - source folder and allowed formats are included in discovery `scan_started` backend event messages/data in pipeline logs
  - total/missing/active-duplicate stats are included in discovery `scan_finished` backend event messages/data
  - scan button success no longer prints verbose summary label; scan details are shown in backend activity logs
  - `Review layouts` button auto-disables when no page is ready
  - wipe DB state action with typed confirmation (`wipe`) in modal
  - live pipeline activity panel is collapsed by default and persisted in local storage
  - activity rows render as plain log lines (no numeric indexes)
  - dashboard timestamps use 24-hour format with day/month date order (non-US)
- Layout Review V1 backend+UI scaffold:
  - `layouts` table and indexes
  - layout CRUD API
  - per-page layout listing
  - page image endpoint
  - redetect endpoint (DocLayNet integration on CPU)
  - mark-layout-review-complete endpoint
  - `layouts.html` page to view/edit layouts
  - redetect thresholds (confidence/IoU) editable in UI
  - layout row edits are stored as local drafts (persisted across refresh)
  - local drafts are applied to backend only when reviewer clicks `Mark Reviewed`
  - per-row restore button (`↺`) reverts class/order/bbox to backend baseline
  - per-row delete uses trash icon button
  - layout ID column hidden in review table UI
  - page-level `Review` button to jump to the next pending review page
  - stage sidebar removed from layout review page for a consistent no-bar UX
  - bbox can be adjusted directly on canvas by dragging box corners/edges
  - `Layouts` panel stays visible while scrolling image content (desktop sticky panel)
  - selecting a bbox on canvas highlights its row in `Layouts`, and selecting a row highlights its bbox on canvas

### Not Completed Yet

- OCR extraction stage (Gemini) and post-processing.
- OCR review page with markdown raw/rendered dual mode.
- Job queue for long-running tasks.
- Migrations with Alembic.

## API Snapshot (As Of 2026-02-16)

- `POST /api/discovery/scan`
- `POST /api/state/wipe`
- `GET /api/pages`
- `GET /api/pages/{page_id}`
- `GET /api/layout-review/next`
- `GET /api/pages/{page_id}/layout-review-next`
- `GET /api/pages/{page_id}/image`
- `GET /api/pages/{page_id}/layouts`
- `POST /api/pages/{page_id}/layouts/detect`
- `POST /api/pages/{page_id}/layouts`
- `PATCH /api/layouts/{layout_id}`
- `DELETE /api/layouts/{layout_id}`
- `POST /api/pages/{page_id}/layouts/review-complete`
- `GET /api/pipeline/activity`
- `GET /api/pipeline/activity/stream`
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
  - Layout review selection is now synchronized both ways:
    - interacting with/clicking a bbox highlights the matching `Layouts` row
    - interacting with/clicking a `Layouts` row highlights the matching bbox on canvas
  - Layout review right-side `Layouts` panel made sticky on desktop so it remains visible while scrolling the page image.
  - Mobile layout keeps non-sticky behavior for single-column usability.
  - Disabled dragging whole bbox body on canvas; only edge/corner handles can be dragged for adjustment.
  - Layout overlay now supports direct bbox manipulation on canvas:
    - drag corners/edges to resize region
    - updates are stored in local drafts and applied on `Mark Reviewed`
  - Layout review `Order` edits now swap positions when target order is already occupied:
    - setting layout A to layout B's order moves layout B to layout A's previous order
  - Layout review table now reorders rows immediately when `Order` is changed (ascending reading order).
  - Layout review bbox spinner step adjusted to `0.001` (arrow up/down increments by thousandths).
  - Layout review draft workflow updated:
    - class/order/bbox edits now persist in browser local storage per page
    - backend updates are deferred until `Mark Reviewed` (PATCH/DELETE batch before review-complete)
    - restore icon updated to conventional `↺` and now reliably reverts class/order/bbox to server baseline
  - Tightened spacing between bbox coordinate labels and inputs for denser row layout.
  - Layout review `Class` column width aligned to longest expected class label (`Section Header`) for stable table sizing.
  - Layout review actions column updated:
    - restore/delete icon buttons are stacked vertically
    - each action button is square-sized to match the `Actions` column width
  - BBox editor precision constrained to 4 decimal places, with narrower bbox input width for compact editing.
  - Layout review bbox editor UI updated:
    - renamed table column from `BBox (0-1)` to `BBox`
    - bbox controls are now stacked vertically with coordinate labels (`x1`, `y1`, `x2`, `y2`)
  - Layout review `Order` column width tightened to header-sized width for compact numeric editing.
  - Removed class color legend block from layout review panel UI.
    - bbox overlays remain color-coded by class
  - Refined layout-review table column sizing:
    - compact fixed-width `Order` input column
    - compact 2x2 grid sizing for bbox inputs
    - right panel now tracks actual control widths more tightly
  - Layout review split-panel sizing updated:
    - right `Layouts` panel now uses fit-content sizing and no longer stretches excessively wide
    - mobile fallback remains single-column
  - Dashboard and layout review pages now use full-width viewport layout (removed fixed max-width container).
  - Layout review table UX updated:
    - removed layout `ID` column from UI
    - removed `Save` button in favor of local drafts
    - added restore button (`↺`)
    - delete action kept and switched to trash icon button
  - `Discovery scan finished` log messages now include full scan counters and totals:
    - scanned/new/updated/missing-marked/duplicates
    - total indexed/missing/active-duplicates
  - Removed verbose scan-success text from dashboard status label; details are shown in activity logs instead.
  - Disabled dashboard auto-scan on page load/refresh.
    - dashboard now loads existing state only; discovery scan runs only on explicit `Scan` button click
  - Dashboard date rendering now uses day/month order (non-US locale) while keeping 24-hour time.
  - Removed dashboard stats panel from UI.
    - `Total Indexed Pages`, `Missing Pages`, `Active Duplicate Files` are now emitted in `scan_finished` backend events
    - same stats are included in scan API responses (`/api/discovery/scan`, wipe rescan summary)
  - Discovery `scan_started` backend events now include source folder and allowed extensions in message/data:
    - applies to startup discovery, manual scan, and wipe-rescan flows
    - replaces prior synthetic standalone source-config log entry approach
  - Removed source/folder formats text from dashboard header.
    - source path and allowed extensions are now printed in pipeline activity log entries
  - Restored `Wipe DB State` button to the previous top-right header position on dashboard.
    - `Scan > Review layouts` remains under the dashboard title
  - Updated dashboard header actions layout:
    - moved actions under `Dashboard` title
    - visualized flow as `Scan > Review layouts`
    - kept `Wipe DB State` as separate danger action
  - Replaced stage-tab navigation with a single dashboard model:
    - removed stage bars/sidebars from dashboard and layout review pages
    - dashboard now always shows one `All Indexed Images` table
    - `Scan` and `Review layouts` actions moved to dashboard header
  - Added global next-review API endpoint `GET /api/layout-review/next`:
    - dashboard uses it to enable/disable `Review layouts`
    - `Review layouts` opens the next `layout_detected` page directly
  - Pipeline activity panel log rows now render without numeric indexes.
  - Dashboard date/time rendering now uses 24-hour format consistently.
  - Supersedes earlier same-day notes that described stage sidebar/tab UX.
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
  - Superseded later on 2026-02-19 by single-dashboard/no-stats-panel UX.
  - UI state persistence added across refresh:
    - dashboard remembers selected stage, sidebar collapsed state, and activity-panel expanded state
    - layout review remembers sidebar collapsed state and redetect threshold inputs (confidence/IoU)
  - Layout review page now includes `Review` action button to jump to next pending layout-review page:
    - resolved by new endpoint `GET /api/pages/{page_id}/layout-review-next`
    - button disables automatically when there is no next `layout_detected` page
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
