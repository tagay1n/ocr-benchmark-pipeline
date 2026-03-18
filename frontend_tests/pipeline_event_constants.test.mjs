import test from "node:test";
import assert from "node:assert/strict";

import {
  PIPELINE_EVENT,
  PIPELINE_STAGE,
  inferPageStatusFromPipelineEvent,
  stageDisplayName,
} from "../app/static/js/pipeline_event_constants.mjs";

test("stageDisplayName maps known stages and falls back with custom formatter", () => {
  assert.equal(stageDisplayName(PIPELINE_STAGE.LAYOUT_DETECT), "Layout detection");
  assert.equal(stageDisplayName(PIPELINE_STAGE.LAYOUT_BENCHMARK), "Layout benchmark");
  assert.equal(stageDisplayName(PIPELINE_STAGE.OCR_EXTRACT), "OCR extraction");
  assert.equal(stageDisplayName(PIPELINE_STAGE.OCR_REVIEW), "OCR review");
  assert.equal(stageDisplayName("layout_review"), "layout review");
  assert.equal(
    stageDisplayName("layout_review", (value) => `x:${value}`),
    "x:layout_review",
  );
  assert.equal(stageDisplayName(""), "Pipeline");
});

test("inferPageStatusFromPipelineEvent maps layout stage transitions", () => {
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.LAYOUT_DETECT,
      event_type: PIPELINE_EVENT.JOB_STARTED,
    }),
    "layout_detecting",
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.LAYOUT_DETECT,
      event_type: PIPELINE_EVENT.JOB_COMPLETED,
      data: { result: { skipped: true } },
    }),
    null,
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.LAYOUT_DETECT,
      event_type: PIPELINE_EVENT.JOB_COMPLETED,
      data: { result: { created: 2 } },
    }),
    "layout_detected",
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.LAYOUT_DETECT,
      event_type: PIPELINE_EVENT.MANUAL_DETECT_COMPLETED,
    }),
    "layout_detected",
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.LAYOUT_DETECT,
      event_type: PIPELINE_EVENT.JOB_FAILED,
    }),
    "new",
  );
});

test("inferPageStatusFromPipelineEvent maps OCR extraction/review transitions", () => {
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.OCR_EXTRACT,
      event_type: PIPELINE_EVENT.JOB_STARTED,
    }),
    "ocr_extracting",
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.OCR_EXTRACT,
      event_type: PIPELINE_EVENT.JOB_COMPLETED,
      data: { result: { skipped: true } },
    }),
    null,
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.OCR_EXTRACT,
      event_type: PIPELINE_EVENT.JOB_COMPLETED,
      data: { result: { extracted_count: 1 } },
    }),
    "ocr_done",
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.OCR_EXTRACT,
      event_type: PIPELINE_EVENT.JOB_FAILED,
    }),
    "ocr_failed",
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.OCR_REVIEW,
      event_type: PIPELINE_EVENT.MANUAL_REVIEW_COMPLETED,
    }),
    "ocr_reviewed",
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.LAYOUT_REVIEW,
      event_type: PIPELINE_EVENT.MANUAL_REVIEW_COMPLETED,
      data: { status: "OCR_DONE" },
    }),
    "ocr_done",
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.LAYOUT_BENCHMARK,
      event_type: PIPELINE_EVENT.JOB_PROGRESS,
    }),
    null,
  );
  assert.equal(
    inferPageStatusFromPipelineEvent({
      stage: PIPELINE_STAGE.FINALIZATION,
      event_type: PIPELINE_EVENT.EXPORT_COMPLETED,
    }),
    null,
  );
});
