# Tatar OCR Dataset Tool (Discovery V1)

Minimal FastAPI + SQLite app for image discovery and duplicate tracking.

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

## Notes

- Deep recursive scan is enabled.
- One canonical file is indexed per unique file hash.
- Duplicate files are skipped and shown in dashboard warning until removed.
- On backend startup, scan runs automatically.
- On dashboard load, a scan also runs automatically.
- Manual scan is available via dashboard button.
