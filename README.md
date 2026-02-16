# OCR Benchmark Pipeline (Discovery + Layout Review V1)

FastAPI + SQLite app for OCR benchmark dataset preparation.
Current implemented slices are image discovery and first layout-review workflow.

## Defaults

- Source folder: `input`
- DB file: `data/ocr_dataset.db`
- Extensions: `.jpg,.jpeg,.png,.tif,.tiff,.webp`

Change defaults in `config.json`:

```json
{
  "source_dir": "input",
  "db_path": "data/ocr_dataset.db",
  "allowed_image_extensions": [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"]
}
```

Optional env overrides:

- `SOURCE_DIR`
- `DB_PATH`
- `ALLOWED_IMAGE_EXTENSIONS` (comma-separated)
- `APP_CONFIG_PATH` (path to config file)

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Implemented So Far

- Deep recursive scan is enabled.
- One canonical file is indexed per unique file hash.
- Duplicate files are skipped and shown in dashboard warning until removed.
- On backend startup, scan runs automatically.
- On dashboard load, a scan also runs automatically.
- Manual scan is available via dashboard button.
- Dashboard rows link to a layout review screen (`/static/layouts.html?page_id=<id>`).
- Layout review API supports listing, manual create/edit/delete, detect (placeholder), and review completion.

## Important Note About Detection

`POST /api/pages/{page_id}/layouts/detect` currently uses a placeholder detector that creates one full-page layout block.
This is temporary scaffolding until `hantian/yolo-doclaynet` integration is added.

## Project Context

Persistent context is tracked in `PROJECT_CONTEXT.md` and should be updated as implementation evolves.
