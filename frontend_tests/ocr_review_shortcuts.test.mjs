import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync("app/static/js/ocr_review_page.mjs", "utf8");
const start = source.indexOf('document.addEventListener("keydown", (event) => {');
const end = source.indexOf('document.addEventListener("keyup",', start);

function press(overrides = {}, hidden = false) {
  let handler;
  const actions = [];
  runInNewContext(source.slice(start, end), {
    document: { addEventListener: (_, callback) => { handler = callback; } },
    state: { panelVisibility: { reconstructed: false }, viewMode: "line_by_line" },
    lineReviewPanel: { hidden },
    isInteractiveTextTarget: (target) => target === "editor",
    approveCurrentLineAndAdvance: () => actions.push("approve"),
    unapproveCurrentLine: () => actions.push("unapprove"),
  });
  handler({ key: " ", preventDefault: () => actions.push("preventDefault"), ...overrides });
  return actions;
}

test("Space approves one OCR line and prevents default page scrolling", () => {
  assert.deepEqual(press(), ["preventDefault", "approve"]);
  assert.deepEqual(press({ shiftKey: true }), ["preventDefault", "unapprove"]);
});

test("OCR approval shortcut ignores typing, held keys, modifiers and hidden review", () => {
  for (const event of [
    { key: "c" }, { key: "C" }, { target: "editor" }, { repeat: true },
    { ctrlKey: true }, { metaKey: true }, { altKey: true },
  ]) {
    assert.deepEqual(press(event), []);
  }
  assert.deepEqual(press({}, true), []);
});
