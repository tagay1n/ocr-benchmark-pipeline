# OCR Pipeline (Discovery + Layout Review V1)

FastAPI + SQLite app for OCR benchmark dataset preparation.
Current implemented slices are image discovery and first layout-review workflow.

## Defaults

- Source folder: `input`
- DB file: `data/ocr_dataset.db`
- Extensions: `.jpg,.jpeg,.png,.tif,.tiff,.webp`

Change defaults in `config.yaml`:

```yaml
source_dir: input
db_path: data/ocr_dataset.db
allowed_image_extensions:
  - .jpg
  - .jpeg
  - .png
  - .tif
  - .tiff
  - .webp
enable_background_jobs: true
```

Optional env overrides:

- `SOURCE_DIR`
- `DB_PATH`
- `ALLOWED_IMAGE_EXTENSIONS` (comma-separated)
- `APP_CONFIG_PATH` (path to config file)
- `ENABLE_BACKGROUND_JOBS` (`true/false`)

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Tests

Backend unit tests:

```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```

Frontend unit tests:

```bash
node --test frontend_tests/pipeline_stages.test.mjs
```

## Implemented So Far

- Deep recursive scan is enabled.
- One canonical file is indexed per unique file hash.
- Duplicate files are skipped and shown in dashboard warning until removed.
- On backend startup, scan runs automatically.
- On dashboard load, a scan also runs automatically.
- Manual scan is available via dashboard button.
- Wipe DB state is available via dashboard danger button and requires typing `wipe` in a confirmation modal.
- Dashboard has a collapsible left pipeline-stage sidebar with stage tabs and per-stage pending counts.
- Stage tabs turn green when their pending count is `0`.
- Stage tabs remain clickable even with `0` pending items and show stage-specific empty-state content.
- Discovery tab shows all indexed documents, including already processed docs from later stages.
- For each stage tab: the number in parentheses is pending count, while the table shows all historical docs that reached that stage.
- Layout detection is auto-started by backend worker after discovery (no separate detection tab).
- Dashboard includes backend pipeline activity panel (running job, queue, recent events).
- Pipeline activity panel updates via server-sent events (SSE) stream.
- Dashboard rows link to a layout review screen (`/static/layouts.html?page_id=<id>`).
- Layout review API supports listing, manual create/edit/delete, real DocLayNet detection, and review completion.
- Redetect supports configurable confidence/IoU thresholds from the UI.
- Layout class editing in review UI uses a dropdown with known DocLayNet classes.

## Pipeline Activity API

- `GET /api/pipeline/activity`: worker state, queue snapshot, and recent backend events.
- `GET /api/pipeline/activity/stream`: live SSE feed of the same activity snapshot.

## Important Note About Detection

`POST /api/pages/{page_id}/layouts/detect` uses `hantian/yolo-doclaynet` (`yolov10b-doclaynet.pt`) via Ultralytics.
Model inference runs on CPU by default. First detection may take longer because checkpoint download happens once and is then cached.

## Project Context

Persistent context is tracked in `PROJECT_CONTEXT.md` and should be updated as implementation evolves.
