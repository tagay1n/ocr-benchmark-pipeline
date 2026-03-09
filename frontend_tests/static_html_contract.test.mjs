import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

function readHtml(path) {
  return readFileSync(path, "utf8");
}

test("dashboard HTML exposes required pipeline controls and backend routes", () => {
  const html = readHtml("app/static/index.html");
  const requiredIds = [
    'id="scan-btn"',
    'id="review-layouts-btn"',
    'id="review-ocr-btn"',
    'id="export-final-btn"',
    'id="wipe-btn"',
    'id="pages-body"',
    'id="auto-detect-layouts-toggle"',
    'id="auto-extract-text-toggle"',
    'data-pages-sort-key="id"',
    'data-pages-sort-key="rel_path"',
    'data-pages-sort-key="status"',
    'data-pages-sort-key="created_at"',
  ];
  for (const marker of requiredIds) {
    assert.equal(html.includes(marker), true, `missing marker: ${marker}`);
  }
  assert.equal(html.includes('"/api/pipeline/activity/stream?limit=30"'), true);
  assert.equal(html.includes('"/api/final/export"'), true);
  assert.equal(html.includes('"/api/runtime-options"'), true);
  assert.equal(html.includes('"/static/js/dashboard_sorting_utils.mjs"'), true);
});

test("layout review HTML keeps detection+zoom integration hooks", () => {
  const html = readHtml("app/static/layouts.html");
  assert.equal(html.includes('id="zoom-percent-input"'), true);
  assert.equal(html.includes('id="zoom-trigger"'), true);
  assert.equal(html.includes('id="zoom-menu"'), true);
  assert.equal(html.includes("layout-bbox-editor"), true);
  assert.equal(html.includes("`/api/pages/${pageId}/layouts/detect`"), true);
  assert.equal(html.includes('bindingLinesLayer.id = "bind-lines-layer"'), true);
  assert.equal(html.includes("box-bind-btn"), true);
  assert.equal(html.includes("caption-bind-chip-remove"), true);
  assert.equal(html.includes("layout-show-bbox-btn"), true);
  assert.equal(html.includes('id="magnifier-toggle-btn"'), true);
  assert.equal(html.includes('"/static/js/magnifier.mjs"'), true);
  assert.equal(html.includes('"/static/js/layout_class_catalog.mjs"'), true);
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
  const requiredIds = [
    'id="zoom-percent-input"',
    'id="zoom-trigger"',
    'id="zoom-menu"',
    'id="reextract-btn"',
    'id="editor-action-bold"',
    'id="editor-action-italic"',
    'id="editor-action-inline-formula"',
    'id="editor-action-list-item"',
    'id="editor-action-ordered-list-item"',
    'id="magnifier-toggle-btn"',
    'id="source-bind-lines-layer"',
  ];
  for (const marker of requiredIds) {
    assert.equal(html.includes(marker), true, `missing marker: ${marker}`);
  }
  assert.equal(html.includes("`/api/pages/${state.pageId}/ocr/reextract`"), true);
  assert.equal(html.includes("renderSourceCaptionBindingLines"), true);
  assert.equal(html.includes('"./js/magnifier.mjs"'), true);
  assert.equal(html.includes('"./js/layout_class_catalog.mjs"'), true);
});

test("ocr review HTML no longer hardcodes class color map", () => {
  const html = readHtml("app/static/ocr_review.html");
  assert.equal(html.includes("const CLASS_COLORS = {"), false);
});
