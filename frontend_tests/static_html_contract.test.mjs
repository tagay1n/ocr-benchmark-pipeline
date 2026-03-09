import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

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
});

test("layout review HTML class catalog excludes title class", () => {
  const html = readHtml("app/static/layouts.html");

  const knownClassesMatch = html.match(/const KNOWN_LAYOUT_CLASSES = \[([\s\S]*?)\];/);
  assert.ok(knownClassesMatch, "KNOWN_LAYOUT_CLASSES block is missing");
  assert.equal(knownClassesMatch[1].includes('"title"'), false);
  assert.equal(knownClassesMatch[1].includes('"list_item"'), true);

  const classColorsMatch = html.match(/const CLASS_COLORS = \{([\s\S]*?)\};/);
  assert.ok(classColorsMatch, "CLASS_COLORS block is missing");
  assert.equal(/\btitle\s*:/.test(classColorsMatch[1]), false);
});

test("layout review class dropdown contract maps to known classes without title", () => {
  const html = readHtml("app/static/layouts.html");
  const knownClassesMatch = html.match(/const KNOWN_LAYOUT_CLASSES = \[([\s\S]*?)\];/);
  assert.ok(knownClassesMatch, "KNOWN_LAYOUT_CLASSES block is missing");
  const classNames = Array.from(
    knownClassesMatch[1].matchAll(/"([^"]+)"/g),
    (match) => String(match[1]),
  );
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
});

test("ocr review HTML class colors exclude title class", () => {
  const html = readHtml("app/static/ocr_review.html");
  const classColorsMatch = html.match(/const CLASS_COLORS = \{([\s\S]*?)\};/);
  assert.ok(classColorsMatch, "CLASS_COLORS block is missing");
  assert.equal(/\btitle\s*:/.test(classColorsMatch[1]), false);
});
