# OCR Benchmark Pipeline

FastAPI + SQLite application for building an OCR benchmark dataset from document page images.

## Goal

Prepare high-quality, reviewer-validated OCR data with this workflow:

1. Discover images in `input/` and index them.
2. Detect document layouts (DocLayNet YOLO model).
3. Review and fix layouts manually.
4. Extract OCR content from reviewed layouts (Gemini).
5. Review and fix extracted OCR content manually.

Optionally run non-blocking OCR verification after review. It compares each reviewed Markdown region with outputs from other configured Gemini models, without changing page status or blocking export.

## Current Product Surface

- Dashboard (`/`):
  - Pipeline actions with live counters: `Scan(total) -> Review layouts(done/total) -> Review OCR(done/total) -> QA checks -> Export`.
  - `Verify OCR` in the upper-right utility actions opens the optional verification workspace; verification remains outside pipeline progression.
  - `Batch OCR` action to queue/stop global OCR extraction for all eligible pages (`layout_reviewed`/`ocr_failed`) that still have missing layout outputs.
  - `Benchmark` action opens dedicated benchmark page.
  - Live backend activity panel (SSE stream).
  - Duplicate-file warnings.
  - Sortable + paginated indexed-images table (default: `Added time` newest first).
  - Pagination controls with page size `25/50/100`.
  - Per-row actions: open Layout/OCR/QA review and remove an image (with confirmation).
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
  - The image viewport stays in place while regions are created or review data is refreshed.
  - Overlapping bbox borders are highlighted with striped warning segments.
  - Quick source magnifier (`M`, hold `Alt`, or toolbar button) with layout overlays.
  - Caption binding mode from caption bbox (`Bind`), with visible arrows to table/picture/formula targets and explicit unbind controls.
  - `Detect` modal with model params, top-3 benchmark suggestions for `model+imgsz`, and in-flight busy state.
- OCR review (`/static/ocr_review.html?page_id=<id>`):
  - Source + reconstructed preview panels with synchronized scrolling.
  - Review modes: `Two panels` and `Line by line` (slot-style line approval rail).
  - In line-by-line review, press `Space` to approve the current line and advance, or `Shift+Space` to unapprove; these shortcuts are inactive while typing in an editor.
  - Draft editing and per-layout restore.
  - Quick source magnifier (`M`, hold `Alt`, or toolbar button) with OCR bbox overlays.
  - `Detect` modal with layout selection, model picker, and generation params.
  - OCR extraction is retried per bbox and then marked failed if still unsuccessful; failed bboxes stay editable and can be re-detected per-layout.
  - Manually entered text immediately resolves a failed bbox in the local draft and appears in the reconstructed preview; it is persisted when OCR review is confirmed.
  - Marking OCR reviewed requires resolving failed/missing required bboxes (re-detect or manual text entry).
  - All pipeline steps are manual by reviewer action.
- QA review (`/static/qa_review.html?page_id=<id>&phase=<bbox|class|order|ocr>`):
  - Dedicated 4-phase verification flow: bbox boundaries, class labels, reading order, OCR text.
  - In-place editing through embedded existing review pages (layout/OCR editors).
  - Per-phase QA status is stored independently per page (`pending`/`reviewed`).
  - QA statuses are non-invasive: editing bbox/class/order/OCR does not auto-reset other QA phases.
  - Quick navigation: previous/next page and next pending page for active phase.
- OCR verification (`/static/ocr_verification.html`):
  - Start, stop, and manually resume a dedicated background verification run.
  - Verifies OCR-reviewed Markdown regions only; tables, formulas, and pictures are skipped.
  - Uses the reviewed text as baseline and selects other models while always excluding the region's original `model_name`.
  - Groups identical variants by supporting model, shows inline differences and the original crop, and distinguishes full, reduced, and source-only evidence.
  - Lets the reviewer explicitly keep current text or apply/edit a model variant; verification never changes pipeline or QA status.
  - Reuses completed model outputs for recalculation; bbox, class, orientation, or prompt-version changes require fresh verification extraction.
  - Uses server-filtered pages of 25 compact findings; comparison variants and editor controls load only when a finding is opened.
  - Polls lightweight run status while verification is active and reloads stored findings when a run or background recalculation finishes.
  - Serves bounded region thumbnails with fingerprinted disk/HTTP caching instead of loading full source pages into every finding.
  - Prepares verification tasks in bulk on a background thread; manual finding recalculation is also non-blocking.

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
supported_ocr_models:
  - gemini-3.7-flash
  - gemini-3.6-flash
  - gemini-3.5-flash
  - gemini-3-flash-preview
ocr_verification:
  models:
    - gemini-3.6-flash
    - gemini-3.5-flash
    - gemini-3-flash-preview
  total_models_per_region: 3
  attempts_per_model: 2
  prompt_version: 1
gemini_keys: []
```

The ordered `supported_ocr_models` list in `config.yaml` is the source of truth for OCR models. Its first entry is used as the default for batch and manual OCR; `SUPPORTED_OCR_MODELS` can override the complete list.

The ordered `ocr_verification.models` pool is independent from the default OCR model order. Verification selects `total_models_per_region - 1` distinct models from this pool and excludes the model stored on the canonical OCR output. The default pool intentionally excludes `gemini-3.7-flash`. Increment `prompt_version` when verification prompt behavior changes; stored outputs with an older prompt version are not reused.

Each verification model gets `attempts_per_model` counted attempts. Invalid/empty responses and ordinary failures consume an attempt. Quota responses rotate keys without consuming an attempt. If every usable key is temporarily rate-limited, only the current task is deferred. If one model has exhausted its daily quota, that model's tasks share a cooldown while verification continues processing other models. HTTP `503`, overloaded service, retryable `5xx`, and transient transport failures are likewise deferred with capped exponential backoff and do not consume an attempt. Deferred work continues until it succeeds or the reviewer stops the run. Successful variants are persisted immediately, so partial evidence remains usable and resumable.

Gemini key selection skips keys recorded as daily-quota exhausted for the selected model, shuffles the remaining available keys, then uses the first shuffled key. Daily exhaustion is merged and atomically persisted to `_artifacts/gemini_usage.json` immediately after each response, grouped by model and Pacific-time quota day. The file stores SHA-256 key fingerprints rather than API-key values and automatically migrates legacy raw-key entries when read. Per-minute rate limits are request-local and are not recorded as daily exhaustion.

Verification scheduling processes untouched model checks before any retries, including after a restart/resume. A check is untouched while both its counted failures and transient deferrals are zero; shared quota cooldowns do not make sibling checks retries. If all remaining untouched checks are quota-blocked, verification waits rather than retrying older failures. After the first pass, eligible retries run in order of fewest failures/deferrals, then oldest update time and task ID. Resume preserves cooldown deadlines and retry counters; terminal unavailable checks are not automatically retried.

Environment overrides:

- `SOURCE_DIR`
- `DB_PATH`
- `RESULT_DIR`
- `ALLOWED_IMAGE_EXTENSIONS` (comma-separated)
- `APP_CONFIG_PATH`
- `ENABLE_BACKGROUND_JOBS`
- `SUPPORTED_OCR_MODELS` (comma-separated)
- `GEMINI_KEYS` (comma-separated)
- `GEMINI_USAGE_PATH`
- `OCR_VERIFICATION_MODELS` (comma-separated)
- `OCR_VERIFICATION_TOTAL_MODELS`
- `OCR_VERIFICATION_ATTEMPTS_PER_MODEL`
- `OCR_VERIFICATION_PROMPT_VERSION`

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
- `GET /api/qa/{phase}/next`
- `GET /api/pages/{page_id}/qa-next?phase=<bbox|class|order|ocr>`
- `PATCH /api/pages/{page_id}/qa-status` (`{"phase":"...","status":"pending|reviewed"}`)
- `GET /api/pipeline/activity`
- `GET /api/pipeline/activity/stream`
- `GET /api/layout-benchmark/status`
- `GET /api/layout-benchmark/grid`
- `POST /api/layout-benchmark/run`
- `POST /api/layout-benchmark/stop`
- `GET /api/ocr-batch/status`
- `POST /api/ocr-batch/run`
- `POST /api/ocr-batch/stop`
- `GET /api/ocr-verification/status`
- `POST /api/ocr-verification/run`
- `POST /api/ocr-verification/stop`
- `POST /api/ocr-verification/recalculate` (starts non-blocking recalculation)
- `GET /api/ocr-verification/findings` (`category`, `limit`, `offset`; compact summaries)
- `GET /api/ocr-verification/findings/{layout_id}`
- `GET /api/ocr-verification/layouts/{layout_id}/crop`
- `POST /api/ocr-verification/layouts/{layout_id}/resolve`
- `POST /api/ocr-verification/layouts/{layout_id}/recheck`

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

## OCR Formatting Decisions Log

This section is a living log of OCR normalization decisions for dataset consistency. Add new items as rules are agreed.

- Multiline emphasis in source text:
  - If text is visually italic, bold, or bold+italic across multiple lines, apply Markdown markers per line (not once for the full block).
  - Use `*line*` for italic, `**line**` for bold, and `***line***` for bold+italic.
  - Start and end every affected line with its corresponding marker.

- Diacritics policy (strict):
  - Preserve diacritics exactly as visible in source text; do not simplify.
  - Ground-truth text keeps stressed/diacritic forms (not stripped variants).
  - Treat script lookalikes as different characters (Cyrillic vs Latin are not interchangeable).
  - Store text in NFC form for consistency, but keep diacritic meaning unchanged.

- Diacritics examples:
  - Keep `А́` (`U+0410` + `U+0301`, Cyrillic `А` + combining stress), not plain `А` (`U+0410`).
  - Keep `ё` (`U+0451`), not `е` (`U+0435`).
  - Keep `ә` (`U+04D9`), not Latin `a` (`U+0061`).
  - Do not replace Cyrillic `А́` (`U+0410` + `U+0301`) with Latin `Á` (`U+00C1`) or Latin `Á` (`U+0041` + `U+0301`).

- Header hierarchy policy:
  - Default all extracted headers to level 4 (`#### `).
  - If page structure clearly shows hierarchy, adjust header levels.
  - Use fewer `#` for higher-level headers: `###` for higher, `##` for top-level on the page.
  - Keep `####` for lower/subordinate headers when they are visually less prominent.
  - Keep header levels consistent within the same page/document section.

- Header hierarchy example:
  - Top header: `## Chapter title`
  - Subheader: `### Section title`
  - Lower subheader: `#### Subsection title`

- Multiline headers policy:
  - Do not split one semantic header across multiple Markdown lines with only the first line marked as `#`.
  - Do not encode continuation lines as bold paragraphs to imitate header continuation.
  - Keep one semantic header as one Markdown header line by joining wrapped source lines into a single heading text.
  - If visual line break must be preserved inside a heading, use an explicit HTML break inside the same header (for example: `## First line<br>Second line`).

- Error preservation policy:
  - Dataset policy is to keep source text as printed, including typos, spelling mistakes, and grammar irregularities.
  - OCR/review normalization does not correct linguistic errors automatically.
  - When intended wording seems obvious, the original printed form is still retained.
  - Punctuation or casing anomalies are retained when they are part of the source.
  - Corrections are limited to clear OCR character misreads, without changing wording/style.

- Quote mark normalization policy:
  - Normalize quotation-mark typography to reduce benchmark noise from visually similar quote glyphs.
  - Single quote/apostrophe variants are stored as ASCII apostrophe (`'`, `U+0027`).
  - Curly double quote variants are stored as ASCII quotation mark (`"`, `U+0022`).
  - Guillemets (`«`, `U+00AB`; `»`, `U+00BB`) are preserved because they are distinct punctuation, not double-quote lookalikes.
  - Examples: `‘text’`, `ʼtextʼ`, and `′text′` become `'text'`; `“text”` and `„text“` become `"text"`; `«text»` stays `«text»`.
  - Preserve formula/LaTeX prime notation, for example `f′(x)` remains `f′(x)` inside formula output and Markdown math spans.

## Documentation Policy

This repository keeps active project documentation in only two files:

- `README.md` (product + usage)
- `AGENTS.md` (engineering collaboration rules)
