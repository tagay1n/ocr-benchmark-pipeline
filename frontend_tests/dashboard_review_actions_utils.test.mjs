import test from "node:test";
import assert from "node:assert/strict";

import {
  findNextPageForStatus,
  normalizeNextPagePayload,
  pipelineProgressFromSummary,
} from "../app/static/js/dashboard_review_actions_utils.mjs";

test("normalizeNextPagePayload accepts valid payload and rejects invalid shape", () => {
  assert.deepEqual(
    normalizeNextPagePayload({ has_next: true, next_page_id: 12, next_page_rel_path: "books/p12.png" }),
    { nextPageId: 12, nextPageRelPath: "books/p12.png" },
  );

  assert.deepEqual(
    normalizeNextPagePayload({ has_next: true, next_page_id: 0, next_page_rel_path: "x" }),
    { nextPageId: null, nextPageRelPath: null },
  );

  assert.deepEqual(
    normalizeNextPagePayload({ has_next: false, next_page_id: 44 }),
    { nextPageId: null, nextPageRelPath: null },
  );
});

test("findNextPageForStatus picks smallest pending id and ignores missing rows", () => {
  const pages = [
    { id: 9, status: "layout_detected", is_missing: false, rel_path: "b/9.png" },
    { id: 3, status: "layout_detected", is_missing: false, rel_path: "a/3.png" },
    { id: 1, status: "layout_detected", is_missing: true, rel_path: "a/1.png" },
    { id: 7, status: "ocr_done", is_missing: false, rel_path: "o/7.png" },
  ];

  assert.deepEqual(findNextPageForStatus(pages, "layout_detected"), {
    nextPageId: 3,
    nextPageRelPath: "a/3.png",
  });

  assert.deepEqual(findNextPageForStatus(pages, "ocr_done"), {
    nextPageId: 7,
    nextPageRelPath: "o/7.png",
  });

  assert.deepEqual(findNextPageForStatus(pages, "ocr_reviewed"), {
    nextPageId: null,
    nextPageRelPath: null,
  });
});

test("findNextPageForStatus tolerates malformed pages payload", () => {
  const pages = [
    null,
    {},
    { id: "7", status: "layout_detected", is_missing: false, rel_path: "x/7.png" },
    { id: "bad", status: "layout_detected", is_missing: false, rel_path: "x/bad.png" },
  ];

  assert.deepEqual(findNextPageForStatus(pages, "layout_detected"), {
    nextPageId: 7,
    nextPageRelPath: "x/7.png",
  });
  assert.deepEqual(findNextPageForStatus(null, "layout_detected"), {
    nextPageId: null,
    nextPageRelPath: null,
  });
});

test("pipelineProgressFromSummary computes stage counters across mixed status key styles", () => {
  const progress = pipelineProgressFromSummary({
    total_pages: 100,
    by_status: {
      LAYOUT_REVIEWED: 40,
      ocr_extracting: 3,
      OCR_DONE: 20,
      "ocr-failed": 2,
      ocr_reviewed: 27,
      new: 8,
    },
  });

  assert.deepEqual(progress, {
    total: 100,
    layoutReviewed: 92,
    ocrReady: 47,
    ocrReviewed: 27,
  });
});

test("pipelineProgressFromSummary clamps malformed values to safe non-negative counts", () => {
  const progress = pipelineProgressFromSummary({
    total_pages: "bad",
    by_status: {
      ocr_reviewed: "6.9",
      layout_reviewed: -10,
    },
  });
  assert.deepEqual(progress, {
    total: 0,
    layoutReviewed: 0,
    ocrReady: 0,
    ocrReviewed: 0,
  });
});
