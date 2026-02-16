# PROJECT CONTEXT

Last updated: 2026-02-16

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
- Config: `config.json` with optional environment overrides.
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
- Layout Review V1 backend+UI scaffold:
  - `layouts` table and indexes
  - layout CRUD API
  - per-page layout listing
  - page image endpoint
  - redetect endpoint (currently placeholder detector)
  - mark-layout-review-complete endpoint
  - `layouts.html` page to view/edit layouts

### Not Completed Yet

- Real `yolo-doclaynet` inference integration.
- Drag-and-resize bbox handles in UI (current editing is coordinate-input based).
- OCR extraction stage (Gemini) and post-processing.
- OCR review page with markdown raw/rendered dual mode.
- Job queue for long-running tasks.
- Migrations with Alembic.

## API Snapshot (As Of 2026-02-16)

- `POST /api/discovery/scan`
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

- 2026-02-16:
  - Recovered prior session context from local Codex session logs after folder rename.
  - Added persistent project context file (`PROJECT_CONTEXT.md`).
  - Renamed app UI/API title text to language-neutral `OCR Benchmark Pipeline`.
  - Implemented Layout Review V1 scaffold:
    - backend layout schema and endpoints
    - page-image endpoint
    - layout review UI page (`app/static/layouts.html`)
    - dashboard links from page list to layout review screen
  - Added placeholder layout detector endpoint to keep workflow moving until real `yolo-doclaynet` integration is added.
