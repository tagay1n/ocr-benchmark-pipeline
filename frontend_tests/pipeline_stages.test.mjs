import test from "node:test";
import assert from "node:assert/strict";

import { STAGES, filterPagesForStage, getStageById, stageCount } from "../app/static/js/pipeline_stages.mjs";

const samplePages = [
  { id: 1, is_missing: false, status: "new" },
  { id: 2, is_missing: false, status: "layout_detected" },
  { id: 3, is_missing: false, status: "layout_reviewed" },
  { id: 4, is_missing: false, status: "ocr_done" },
  { id: 5, is_missing: true, status: "new" },
];

test("discovery stage includes all pages and counts only actionable new items", () => {
  const stage = getStageById("discovery");
  assert.ok(stage);
  assert.equal(stageCount(stage, samplePages), 1);
  assert.equal(filterPagesForStage(stage, samplePages).length, 5);
});

test("layout review stage counts detected pages and keeps forward history", () => {
  const stage = getStageById("layout_review");
  assert.ok(stage);
  assert.equal(stageCount(stage, samplePages), 1);
  assert.deepEqual(
    filterPagesForStage(stage, samplePages).map((page) => page.id),
    [2, 3, 4],
  );
});

test("stage ids are unique and lookup returns null for unknown ids", () => {
  const ids = STAGES.map((stage) => stage.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(getStageById("missing"), null);
  assert.equal(getStageById("layout_detection"), null);
});
