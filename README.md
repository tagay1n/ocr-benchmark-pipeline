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
  - Pipeline actions with live counters: `Scan(total) -> Review layouts(done/total) -> Review OCR(done/total) -> Export`.
  - `Batch OCR` action to queue/stop global OCR extraction for all eligible pages (`layout_reviewed`/`ocr_failed`) that still have missing layout outputs.
  - `Benchmark` action opens dedicated benchmark page.
  - Live backend activity panel (SSE stream).
  - Duplicate-file warnings.
  - Sortable + paginated indexed-images table (default: `Added time` newest first).
  - Pagination controls with page size `25/50/100`.
  - Per-row actions: open Layout/OCR review and remove an image (with confirmation).
- Layout benchmark (`/static/layout_benchmark.html`):
  - Start/stop benchmark run.
  - `Recalculate score` action to recompute scores from stored benchmark predictions without rerunning detection.
  - Leaderboard + explorer matrix views with current running params highlight and best-so-far config.
  - Hard-case subset reporting per config (`hard_case_score`, page count).
- Layout review (`/static/layouts.html?page_id=<id>`):
  - Editable class, reading order, bbox.
  - Drag-and-drop reading order.
  - Per-page reading-order mode selector: `Auto`, `Single`, `Multi-column`, `Two-page`.
  - `Reorder` action recomputes reading order from the selected mode.
  - Bbox editing from table and by canvas handles.
  - Overlapping bbox borders are highlighted with striped warning segments.
  - Quick source magnifier (`M`, hold `Alt`, or toolbar button) with layout overlays.
  - Caption binding mode from caption bbox (`Bind`), with visible arrows to table/picture/formula targets and explicit unbind controls.
  - `Detect` modal with model params, top-3 benchmark suggestions for `model+imgsz`, and in-flight busy state.
- OCR review (`/static/ocr_review.html?page_id=<id>`):
  - Source + reconstructed preview panels with synchronized scrolling.
  - Review modes: `Two panels` and `Line by line` (slot-style line approval rail).
  - Draft editing and per-layout restore.
  - Quick source magnifier (`M`, hold `Alt`, or toolbar button) with OCR bbox overlays.
  - `Detect` modal with layout selection + generation params.
  - OCR extraction is retried per bbox and then marked failed if still unsuccessful; failed bboxes stay editable and can be re-detected per-layout.
  - Marking OCR reviewed requires resolving failed/missing required bboxes (re-detect or manual text entry).
  - All pipeline steps are manual by reviewer action.

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
- `GET /api/pages` (supports `limit`, `cursor`, `sort`, `dir`)
- `GET /api/pages/summary`
- `DELETE /api/pages/{page_id}`
- `GET /api/pages/{page_id}/layouts`
- `PATCH /api/pages/{page_id}/layout-order-mode`
- `POST /api/pages/{page_id}/layouts/reorder`
- `POST /api/pages/{page_id}/layouts/detect`
- `POST /api/pages/{page_id}/layouts/review-complete`
- `GET /api/pages/{page_id}/ocr-outputs`
- `POST /api/pages/{page_id}/ocr/reextract`
- `POST /api/pages/{page_id}/ocr/review-complete`
- `GET /api/pipeline/activity`
- `GET /api/pipeline/activity/stream`
- `GET /api/layout-benchmark/status`
- `GET /api/layout-benchmark/grid`
- `POST /api/layout-benchmark/run`
- `POST /api/layout-benchmark/stop`
- `GET /api/ocr-batch/status`
- `POST /api/ocr-batch/run`
- `POST /api/ocr-batch/stop`

## OCR Prompt Debug Artifacts

Prompt source-of-truth (editable):

- `app/ocr_prompts.py`
- `tests/fixtures/ocr_prompt_snapshots.json` (golden prompt snapshots used by tests)

Generate prompt reference markdown deterministically:

- `.venv/bin/python scripts/generate_prompt_reference.py`
- Output: `OCR_PROMPTS_REFERENCE.md`

Gemini OCR response contract:

- Gemini must return JSON with exactly one key: `{"content":"..."}`
- Backend validates JSON shape and retries per existing retry policy on invalid responses.

Each OCR extraction run writes resolved text prompts (without image clip bytes) to:

- `_artifacts/ocr_prompts/<timestamp>_page_<page_id>.jsonl`

Each JSONL row includes page/layout identifiers, class, output format, and the exact prompt sent to Gemini.

## Documentation Policy

This repository keeps active project documentation in only two files:

- `README.md` (product + usage)
- `AGENTS.md` (engineering collaboration rules)
