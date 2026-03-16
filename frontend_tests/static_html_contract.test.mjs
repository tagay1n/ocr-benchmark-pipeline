import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

function readHtml(path) {
  return readFileSync(path, "utf8");
}

function readModule(path) {
  return readFileSync(path, "utf8");
}

test("dashboard HTML exposes required pipeline controls and backend routes", () => {
  const html = readHtml("app/static/index.html");
  const pageModule = readModule("app/static/js/dashboard_page.mjs");
  const requiredIds = [
    'id="scan-btn"',
    'id="review-layouts-btn"',
    'id="review-ocr-btn"',
    'id="export-final-btn"',
    'id="batch-ocr-btn"',
    'id="layout-benchmark-btn"',
    'id="wipe-btn"',
    'id="pages-body"',
    'id="pages-size-select"',
    'id="pages-prev-btn"',
    'id="pages-next-btn"',
    'id="pages-meta"',
    'data-pages-sort-key="id"',
    'data-pages-sort-key="rel_path"',
    'data-pages-sort-key="status"',
    'data-pages-sort-key="created_at"',
  ];
  for (const marker of requiredIds) {
    assert.equal(html.includes(marker), true, `missing marker: ${marker}`);
  }
  assert.equal(html.includes('src="/static/js/dashboard_page.mjs"'), true);
  assert.equal(pageModule.includes('"/api/pipeline/activity/stream?limit=30"'), true);
  assert.equal(pageModule.includes('"/api/final/export"'), true);
  assert.equal(pageModule.includes('"/api/ocr-batch/status"'), true);
  assert.equal(pageModule.includes('"/api/ocr-batch/run"'), true);
  assert.equal(pageModule.includes('"/api/ocr-batch/stop"'), true);
  assert.equal(pageModule.includes('"/static/layout_benchmark.html"'), true);
  assert.equal(pageModule.includes('"/api/pages/summary"'), true);
  assert.equal(pageModule.includes('"./dashboard_sorting_utils.mjs"'), true);
  assert.equal(pageModule.includes('"./pipeline_event_constants.mjs"'), true);
  assert.equal(pageModule.includes('"./api_client.mjs"'), true);
  assert.equal(pageModule.includes('"./state_event_utils.mjs"'), true);
});

test("layout benchmark page keeps run/stop/grid integration hooks", () => {
  const html = readHtml("app/static/layout_benchmark.html");
  const pageModule = readModule("app/static/js/layout_benchmark_page.mjs");
  const requiredIds = [
    'id="benchmark-toggle-btn"',
    'id="benchmark-rescore-btn"',
    'id="benchmark-force-rerun-toggle"',
    'id="benchmark-run-status"',
    'id="benchmark-processed-tasks"',
    'id="benchmark-skipped-tasks"',
    'id="benchmark-current-config"',
    'id="benchmark-best-config"',
    'id="benchmark-view-leaderboard-btn"',
    'id="benchmark-view-explorer-btn"',
    'id="benchmark-leaderboard-panel"',
    'id="benchmark-explorer-panel"',
    'id="benchmark-grid-body"',
    'id="benchmark-explorer-caption"',
    'id="benchmark-heatmap-head"',
    'id="benchmark-heatmap-body"',
  ];
  for (const marker of requiredIds) {
    assert.equal(html.includes(marker), true, `missing marker: ${marker}`);
  }
  assert.equal(html.includes('src="/static/js/layout_benchmark_page.mjs"'), true);
  assert.equal(pageModule.includes('"/api/layout-benchmark/status"'), true);
  assert.equal(pageModule.includes('"/api/layout-benchmark/grid"'), true);
  assert.equal(pageModule.includes('"/api/layout-benchmark/run"'), true);
  assert.equal(pageModule.includes('"/api/layout-benchmark/stop"'), true);
  assert.equal(pageModule.includes('"/api/layout-benchmark/rescore"'), true);
  assert.equal(pageModule.includes('"/api/pipeline/activity/stream?limit=60"'), true);
});

test("layout review HTML keeps detection+zoom integration hooks", () => {
  const html = readHtml("app/static/layouts.html");
  const pageModule = readModule("app/static/js/layout_review_page.mjs");
  const apiModule = readModule("app/static/js/layout_review_api.mjs");
  assert.equal(html.includes('id="zoom-percent-input"'), true);
  assert.equal(html.includes('id="zoom-trigger"'), true);
  assert.equal(html.includes('id="zoom-menu"'), true);
  assert.equal(html.includes("layout-bbox-editor"), true);
  assert.equal(html.includes('id="magnifier-toggle-btn"'), true);
  assert.equal(html.includes('id="layout-order-mode"'), true);
  assert.equal(html.includes('id="detect-modal-model"'), true);
  assert.equal(html.includes('id="detect-modal-top-config"'), true);
  assert.equal(html.includes('src="/static/js/layout_review_page.mjs"'), true);
  assert.equal(pageModule.includes('bindingLinesLayer.id = "bind-lines-layer"'), true);
  assert.equal(pageModule.includes("box-bind-btn"), true);
  assert.equal(pageModule.includes("caption-bind-chip-remove"), true);
  assert.equal(pageModule.includes("layout-show-bbox-btn"), true);
  assert.equal(pageModule.includes('event.key === "Insert"'), true);
  assert.equal(pageModule.includes('event.key === "Delete"'), true);
  assert.equal(pageModule.includes('"/static/js/magnifier.mjs"'), true);
  assert.equal(pageModule.includes('"/static/js/layout_class_catalog.mjs"'), true);
  assert.equal(pageModule.includes('"/static/js/layout_review_api.mjs"'), true);
  assert.equal(pageModule.includes('"/static/js/state_event_utils.mjs"'), true);
  assert.equal(pageModule.includes("fetchLayoutDetectionDefaults"), true);
  assert.equal(apiModule.includes("`/api/pages/${pageId}/layouts/detect`"), true);
  assert.equal(apiModule.includes('"/api/layout-detection/defaults"'), true);
  assert.equal(apiModule.includes('"/api/layout-benchmark/grid"'), true);
  assert.equal(apiModule.includes("`/api/layouts/${layoutId}`"), true);
});

test("layout class catalog module exports stable class policy", async () => {
  const moduleUrl = pathToFileURL(`${process.cwd()}/app/static/js/layout_class_catalog.mjs`).href;
  const catalog = await import(moduleUrl);
  const classNames = Array.from(catalog.KNOWN_LAYOUT_CLASSES || []);
  assert.equal(classNames.includes("title"), false);
  assert.equal(classNames.includes("list_item"), true);
  assert.deepEqual(
    classNames,
    [
      "section_header",
      "text",
      "list_item",
      "table",
      "picture",
      "picture_text",
      "caption",
      "footnote",
      "formula",
      "page_header",
      "page_footer",
    ],
  );
  assert.equal(catalog.CAPTION_LAYOUT_CLASS, "caption");
  assert.deepEqual(Array.from(catalog.CAPTION_TARGET_CLASSES || []), ["table", "picture", "formula"]);
  assert.equal(typeof catalog.colorForClass, "function");
  assert.equal(catalog.colorForClass("section_header"), "#355fa8");
  assert.equal(catalog.normalizeClassName(" List Item "), "list_item");
  assert.equal(catalog.formatClassLabel("section_header"), "Section header");
});

test("ocr review HTML keeps extraction/editor integration hooks", () => {
  const html = readHtml("app/static/ocr_review.html");
  const pageModule = readModule("app/static/js/ocr_review_page.mjs");
  const apiModule = readModule("app/static/js/ocr_review_api.mjs");
  const requiredIds = [
    'id="zoom-percent-input"',
    'id="zoom-trigger"',
    'id="zoom-menu"',
    'id="reextract-btn"',
    'id="line-review-panel"',
    'id="line-review-approve-btn"',
    'id="line-review-prev-btn"',
    'id="line-review-next-btn"',
    'id="line-review-baseline-text"',
    'id="line-review-approve-bbox-btn"',
    'id="line-review-reset-bbox-btn"',
    'id="source-strip-overlay"',
    'id="reconstructed-strip-overlay"',
    'id="editor-action-bold"',
    'id="editor-action-italic"',
    'id="editor-action-inline-formula"',
    'id="editor-action-list-item"',
    'id="editor-action-ordered-list-item"',
    'id="magnifier-toggle-btn"',
    'id="source-bind-lines-layer"',
    'id="view-two-panels-btn"',
    'id="view-line-by-line-btn"',
  ];
  for (const marker of requiredIds) {
    assert.equal(html.includes(marker), true, `missing marker: ${marker}`);
  }
  assert.equal(html.includes('src="/static/js/ocr_review_page.mjs"'), true);
  assert.equal(pageModule.includes("renderSourceCaptionBindingLines"), true);
  assert.equal(pageModule.includes('"./magnifier.mjs"'), true);
  assert.equal(pageModule.includes('"./layout_class_catalog.mjs"'), true);
  assert.equal(pageModule.includes('"./ocr_review_api.mjs"'), true);
  assert.equal(pageModule.includes('"./state_event_utils.mjs"'), true);
  assert.equal(apiModule.includes("`/api/pages/${pageId}/ocr/reextract`"), true);
  assert.equal(apiModule.includes("`/api/ocr-outputs/${layoutId}`"), true);
});

test("ocr review HTML no longer hardcodes class color map", () => {
  const moduleCode = readModule("app/static/js/ocr_review_page.mjs");
  assert.equal(moduleCode.includes("const CLASS_COLORS = {"), false);
});

test("state/event utils expose storage helpers", async () => {
  const moduleUrl = pathToFileURL(`${process.cwd()}/app/static/js/state_event_utils.mjs`).href;
  const utils = await import(moduleUrl);
  assert.equal(typeof utils.readStorage, "function");
  assert.equal(typeof utils.writeStorage, "function");
  assert.equal(typeof utils.removeStorage, "function");
  assert.equal(typeof utils.readStorageBool, "function");
});

test("pipeline event constants module exposes stable stage/event keys", async () => {
  const moduleUrl = pathToFileURL(`${process.cwd()}/app/static/js/pipeline_event_constants.mjs`).href;
  const constants = await import(moduleUrl);
  assert.equal(constants.PIPELINE_STAGE.DISCOVERY, "discovery");
  assert.equal(constants.PIPELINE_STAGE.OCR_EXTRACT, "ocr_extract");
  assert.equal(constants.PIPELINE_EVENT.JOB_STARTED, "job_started");
  assert.equal(constants.PIPELINE_EVENT.MANUAL_REVIEW_COMPLETED, "manual_review_completed");
  assert.equal(typeof constants.stageDisplayName, "function");
  assert.equal(typeof constants.inferPageStatusFromPipelineEvent, "function");
  assert.equal(
    constants.inferPageStatusFromPipelineEvent({
      stage: "ocr_extract",
      event_type: "job_completed",
      data: { result: { skipped: false } },
    }),
    "ocr_done",
  );
});
