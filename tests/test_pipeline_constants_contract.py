from __future__ import annotations

import unittest

from app import pipeline_constants


class PipelineConstantsContractTest(unittest.TestCase):
    def test_stage_constants_are_stable(self) -> None:
        self.assertEqual(pipeline_constants.STAGE_DISCOVERY, "discovery")
        self.assertEqual(pipeline_constants.STAGE_LAYOUT_DETECT, "layout_detect")
        self.assertEqual(pipeline_constants.STAGE_LAYOUT_REVIEW, "layout_review")
        self.assertEqual(pipeline_constants.STAGE_OCR_EXTRACT, "ocr_extract")
        self.assertEqual(pipeline_constants.STAGE_OCR_REVIEW, "ocr_review")
        self.assertEqual(pipeline_constants.STAGE_FINALIZATION, "finalization")
        self.assertEqual(pipeline_constants.STAGE_PIPELINE, "pipeline")
        self.assertEqual(len(set(pipeline_constants.PIPELINE_STAGES)), len(pipeline_constants.PIPELINE_STAGES))

    def test_event_constants_include_core_job_flow(self) -> None:
        self.assertEqual(pipeline_constants.EVENT_JOB_QUEUED, "job_queued")
        self.assertEqual(pipeline_constants.EVENT_JOB_STARTED, "job_started")
        self.assertEqual(pipeline_constants.EVENT_JOB_COMPLETED, "job_completed")
        self.assertEqual(pipeline_constants.EVENT_JOB_FAILED, "job_failed")
        self.assertEqual(pipeline_constants.EVENT_SCAN_STARTED, "scan_started")
        self.assertEqual(pipeline_constants.EVENT_SCAN_FINISHED, "scan_finished")

    def test_stage_display_name_contract(self) -> None:
        self.assertEqual(pipeline_constants.stage_display_name(None), "pipeline")
        self.assertEqual(pipeline_constants.stage_display_name("layout_detect"), "layout detection")
        self.assertEqual(pipeline_constants.stage_display_name("ocr_extract"), "OCR extraction")
        self.assertEqual(pipeline_constants.stage_display_name("layout_review"), "layout review")


if __name__ == "__main__":
    unittest.main()
