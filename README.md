# OCR Benchmark Pipeline

FastAPI + SQLite application for building an OCR benchmark dataset from document page images.

## Goal

Prepare high-quality, reviewer-validated OCR data with this workflow:

1. Discover images in `input/` and index them.
2. Detect document layouts (DocLayNet YOLO model).
3. Review and fix layouts manually.
4. Extract OCR content from reviewed layouts (Gemini).
5. Review and fix extracted OCR content manually.

## Current Product Surface

- Dashboard (`/`):
  - Pipeline actions: `Scan -> Review layouts -> Review OCR -> Export`.
  - Live backend activity panel (SSE stream).
  - Duplicate-file warnings.
  - Per-row actions: open Layout/OCR review and remove an image (with confirmation).
- Layout review (`/static/layouts.html?page_id=<id>`):
  - Editable class, reading order, bbox.
  - Drag-and-drop reading order.
  - Bbox editing from table and by canvas handles.
  - Caption binding mode from caption bbox (`Bind`), with visible arrows to table/picture/formula targets and explicit unbind controls.
  - `Detect again` modal with model params and in-flight busy state.
- OCR review (`/static/ocr_review.html?page_id=<id>`):
  - Source + reconstructed + extracted-content panels.
  - Draft editing and restore per OCR item.
  - `Detect again` modal with editable prompt template + generation params.
  - Manual detect is always allowed regardless of auto-mode toggles.

## Configuration

Defaults are loaded from `config.yaml` (or `APP_CONFIG_PATH`).

```yaml
source_dir: input
db_path: data/ocr_dataset.db
result_dir: result
allowed_image_extensions:
  - .jpg
  - .jpeg
  - .png
  - .tif
  - .tiff
  - .webp
enable_background_jobs: true
auto_detect_layouts_after_discovery: false
auto_extract_text_after_layout_review: false
gemini_keys: []
```

Environment overrides:

- `SOURCE_DIR`
- `DB_PATH`
- `RESULT_DIR`
- `ALLOWED_IMAGE_EXTENSIONS` (comma-separated)
- `APP_CONFIG_PATH`
- `ENABLE_BACKGROUND_JOBS`
- `GEMINI_KEYS` (comma-separated)
- `GEMINI_USAGE_PATH`

Runtime toggles in dashboard are process-local:

- `Auto-detect layouts after discovery`
- `Auto-extract text after layout review`

They do not rewrite `config.yaml`.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Tests

Backend:

```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

Frontend:

```bash
node --test frontend_tests/*.test.mjs
```

## API Quick Reference

- `POST /api/discovery/scan`
- `POST /api/state/wipe`
- `GET /api/pages`
- `DELETE /api/pages/{page_id}`
- `GET /api/pages/{page_id}/layouts`
- `POST /api/pages/{page_id}/layouts/detect`
- `POST /api/pages/{page_id}/layouts/review-complete`
- `GET /api/pages/{page_id}/ocr-outputs`
- `POST /api/pages/{page_id}/ocr/reextract`
- `POST /api/pages/{page_id}/ocr/review-complete`
- `GET /api/pipeline/activity`
- `GET /api/pipeline/activity/stream`

## OCR Prompt Debug Artifacts

Each OCR extraction run writes resolved text prompts (without image clip bytes) to:

- `_artifacts/ocr_prompts/<timestamp>_page_<page_id>.jsonl`

Each JSONL row includes page/layout identifiers, class, output format, caption targets, and the exact prompt sent to Gemini.

## Documentation Policy

This repository keeps active project documentation in only two files:

- `README.md` (product + usage)
- `AGENTS.md` (engineering collaboration rules)
