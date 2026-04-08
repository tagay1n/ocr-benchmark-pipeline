from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import config, db, discovery, final_export, layouts, main, ocr_extract, runtime_options
from app.config import DEFAULT_EXTENSIONS, Settings


class QaReviewApiTests(unittest.TestCase):
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

    def _write_image(self, rel_path: str, content: bytes = b"img") -> None:
        path = self.test_settings.source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _scan_and_page_ids(self) -> list[int]:
        main.scan_images()
        pages = sorted(main.list_pages()["pages"], key=lambda row: int(row["id"]))
        return [int(page["id"]) for page in pages]

    def test_pages_payload_includes_default_qa_statuses(self) -> None:
        self._write_image("qa/defaults.png")
        page_ids = self._scan_and_page_ids()
        self.assertEqual(page_ids, [1])

        page_row = main.list_pages()["pages"][0]
        self.assertEqual(
            page_row["qa_statuses"],
            {
                "bbox": "pending",
                "class": "pending",
                "order": "pending",
                "ocr": "pending",
            },
        )

        details = main.page_details(page_ids[0])
        self.assertEqual(
            details["page"]["qa_statuses"],
            {
                "bbox": "pending",
                "class": "pending",
                "order": "pending",
                "ocr": "pending",
            },
        )

    def test_patch_page_qa_status_updates_only_requested_phase(self) -> None:
        self._write_image("qa/patch-status.png")
        page_id = self._scan_and_page_ids()[0]

        response = main.patch_page_qa_status(
            page_id,
            main.UpdatePageQaStatusRequest(phase="bbox", status="reviewed"),
        )
        self.assertEqual(response["phase"], "bbox")
        self.assertEqual(response["status"], "reviewed")
        self.assertEqual(
            response["qa_statuses"],
            {
                "bbox": "reviewed",
                "class": "pending",
                "order": "pending",
                "ocr": "pending",
            },
        )

        response2 = main.patch_page_qa_status(
            page_id,
            main.UpdatePageQaStatusRequest(phase="ocr", status="reviewed"),
        )
        self.assertEqual(
            response2["qa_statuses"],
            {
                "bbox": "reviewed",
                "class": "pending",
                "order": "pending",
                "ocr": "reviewed",
            },
        )

    def test_next_qa_review_page_respects_phase_statuses(self) -> None:
        for idx in range(1, 4):
            self._write_image(f"qa/next-{idx}.png", f"img-{idx}".encode("utf-8"))
        page_ids = self._scan_and_page_ids()
        self.assertEqual(page_ids, [1, 2, 3])

        main.patch_page_qa_status(
            page_ids[0],
            main.UpdatePageQaStatusRequest(phase="bbox", status="reviewed"),
        )
        main.patch_page_qa_status(
            page_ids[1],
            main.UpdatePageQaStatusRequest(phase="bbox", status="reviewed"),
        )
        main.patch_page_qa_status(
            page_ids[0],
            main.UpdatePageQaStatusRequest(phase="class", status="reviewed"),
        )

        next_bbox = main.next_qa_review_page_global("bbox")
        self.assertTrue(next_bbox["has_next"])
        self.assertEqual(int(next_bbox["next_page_id"]), page_ids[2])

        next_bbox_after_first = main.next_qa_review_page(page_ids[0], "bbox")
        self.assertTrue(next_bbox_after_first["has_next"])
        self.assertEqual(int(next_bbox_after_first["next_page_id"]), page_ids[2])

        no_next_bbox = main.next_qa_review_page(page_ids[2], "bbox")
        self.assertFalse(no_next_bbox["has_next"])
        self.assertIsNone(no_next_bbox["next_page_id"])

        next_class = main.next_qa_review_page_global("class")
        self.assertTrue(next_class["has_next"])
        self.assertEqual(int(next_class["next_page_id"]), page_ids[1])

    def test_layout_edits_do_not_reset_qa_statuses(self) -> None:
        self._write_image("qa/non-invasive.png")
        page_id = self._scan_and_page_ids()[0]

        layout_1 = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.10, y1=0.10, x2=0.50, y2=0.30),
            ),
        )["layout"]
        layout_2 = main.create_page_layout(
            page_id,
            main.CreateLayoutRequest(
                class_name="text",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.55, y1=0.10, x2=0.90, y2=0.30),
            ),
        )["layout"]

        for phase in ("bbox", "class", "order", "ocr"):
            main.patch_page_qa_status(
                page_id,
                main.UpdatePageQaStatusRequest(phase=phase, status="reviewed"),
            )

        main.patch_layout(
            int(layout_1["id"]),
            main.UpdateLayoutRequest(
                class_name="section_header",
                reading_order=1,
                bbox=main.BBoxPayload(x1=0.12, y1=0.10, x2=0.52, y2=0.30),
            ),
        )
        main.patch_layout(
            int(layout_2["id"]),
            main.UpdateLayoutRequest(
                class_name="text",
                reading_order=2,
                bbox=main.BBoxPayload(x1=0.53, y1=0.10, x2=0.88, y2=0.30),
            ),
        )
        main.reorder_layouts(page_id, main.ReorderLayoutsRequest(mode="single"))

        qa_statuses = main.page_details(page_id)["page"]["qa_statuses"]
        self.assertEqual(
            qa_statuses,
            {
                "bbox": "reviewed",
                "class": "reviewed",
                "order": "reviewed",
                "ocr": "reviewed",
            },
        )


if __name__ == "__main__":
    unittest.main()
