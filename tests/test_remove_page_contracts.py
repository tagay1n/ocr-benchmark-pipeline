from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlalchemy import select

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class RemovePageContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.project_root = Path(self.temp_dir.name)
        self.test_settings = Settings(
            project_root=self.project_root,
            source_dir=self.project_root / "input",
            db_path=self.project_root / "data" / "test.db",
            result_dir=self.project_root / "result",
            allowed_extensions=DEFAULT_EXTENSIONS,
            enable_background_jobs=False,
        )
        self.test_settings.source_dir.mkdir(parents=True, exist_ok=True)

        self.stack = ExitStack()
        self.stack.enter_context(patch.object(config, "settings", self.test_settings))
        self.stack.enter_context(patch.object(db, "settings", self.test_settings))
        self.stack.enter_context(patch.object(discovery, "settings", self.test_settings))
        self.stack.enter_context(patch.object(final_export, "settings", self.test_settings))
        self.stack.enter_context(patch.object(layouts, "settings", self.test_settings))
        self.stack.enter_context(patch.object(main, "settings", self.test_settings))
        self.stack.enter_context(patch.object(ocr_extract, "settings", self.test_settings))
        self.stack.enter_context(patch.object(runtime_options, "settings", self.test_settings))
        db.init_db()
        runtime_options.reset_runtime_options_from_settings()

    def tearDown(self) -> None:
        self.stack.close()
        self.temp_dir.cleanup()

    def _write_image(self, rel_path: str, content: bytes = b"img") -> Path:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _single_page_id(self) -> int:
        pages = main.list_pages()["pages"]
        self.assertEqual(len(pages), 1)
        return int(pages[0]["id"])

    def test_remove_page_when_file_already_missing_keeps_response_and_event_consistent(self) -> None:
        file_path = self._write_image("remove/missing.png")
        main.scan_images()
        page_id = self._single_page_id()
        file_path.unlink()

        payload = main.remove_page(page_id)

        self.assertTrue(payload["deleted"])
        self.assertEqual(payload["page_id"], page_id)
        self.assertFalse(payload["file_existed"])
        self.assertFalse(payload["file_deleted"])
        self.assertEqual(main.list_pages()["count"], 0)

        with db.get_session() as session:
            event = session.execute(
                select(main.PipelineEvent)
                .where(main.PipelineEvent.event_type == "page_removed")
                .order_by(main.PipelineEvent.id.desc())
                .limit(1)
            ).scalar_one()
        data = json.loads(str(event.data_json or "{}"))
        self.assertEqual(data["page_id"], page_id)
        self.assertEqual(data["file_existed"], False)
        self.assertEqual(data["file_deleted"], False)

    def test_remove_page_rejects_directory_path_and_keeps_db_row(self) -> None:
        file_path = self._write_image("remove/not-a-file.png")
        main.scan_images()
        page_id = self._single_page_id()

        file_path.unlink()
        file_path.mkdir(parents=False, exist_ok=False)

        with self.assertRaises(main.HTTPException) as error:
            main.remove_page(page_id)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("not a file", str(error.exception.detail).lower())

        pages = main.list_pages()["pages"]
        self.assertEqual(len(pages), 1)
        self.assertEqual(int(pages[0]["id"]), page_id)

    def test_remove_page_rejects_rel_path_outside_source_dir(self) -> None:
        now = main._utc_now()
        with db.get_session() as session:
            row = main.Page(
                rel_path="../outside.png",
                file_hash="hash-outside-remove",
                status="new",
                created_at=now,
                updated_at=now,
                last_seen_at=now,
                is_missing=False,
            )
            session.add(row)
            session.flush()
            page_id = int(row.id)

        with self.assertRaises(main.HTTPException) as error:
            main.remove_page(page_id)
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn("invalid page image path", str(error.exception.detail).lower())

        with db.get_session() as session:
            kept = session.get(main.Page, page_id)
            self.assertIsNotNone(kept)


if __name__ == "__main__":
    unittest.main()
