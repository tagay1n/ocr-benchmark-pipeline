import test from "node:test";
import assert from "node:assert/strict";

import {
  applyInlineMarkdownWrapper,
  applyLinePrefixMarkdown,
  countTextLines,
  computeFloatingControlPlacement,
  detectEditorValidationIssues,
  findBestTokenOccurrence,
  hasLocalDraftForLayout,
  isRectOnscreen,
  isReconstructedRestoreDisabled,
  lineBandFromLineIndex,
  lineIndexFromTextOffset,
  normalizeReconstructedRenderMode,
  tokenBoundsAtOffset,
  textOffsetForLineIndex,
} from "../app/static/js/ocr_review_utils.mjs";

test("normalizeReconstructedRenderMode defaults to markdown and accepts raw", () => {
  assert.equal(normalizeReconstructedRenderMode(undefined), "markdown");
  assert.equal(normalizeReconstructedRenderMode(null), "markdown");
  assert.equal(normalizeReconstructedRenderMode(""), "markdown");
  assert.equal(normalizeReconstructedRenderMode("raw"), "raw");
  assert.equal(normalizeReconstructedRenderMode(" RAW "), "raw");
  assert.equal(normalizeReconstructedRenderMode("markdown"), "markdown");
  assert.equal(normalizeReconstructedRenderMode("something-else"), "markdown");
});

test("hasLocalDraftForLayout checks layout id normalization and map presence", () => {
  const localEditsByLayoutId = {
    "7": { content: "edited" },
    "11": { content: "edited too" },
  };

  assert.equal(hasLocalDraftForLayout(localEditsByLayoutId, 7), true);
  assert.equal(hasLocalDraftForLayout(localEditsByLayoutId, "11"), true);
  assert.equal(hasLocalDraftForLayout(localEditsByLayoutId, 0), false);
  assert.equal(hasLocalDraftForLayout(localEditsByLayoutId, -1), false);
  assert.equal(hasLocalDraftForLayout(localEditsByLayoutId, "abc"), false);
  assert.equal(hasLocalDraftForLayout(localEditsByLayoutId, 99), false);
  assert.equal(hasLocalDraftForLayout(null, 7), false);
});

test("countTextLines handles empty and multiline text", () => {
  assert.equal(countTextLines(""), 1);
  assert.equal(countTextLines("one"), 1);
  assert.equal(countTextLines("one\ntwo"), 2);
  assert.equal(countTextLines("one\ntwo\n"), 3);
});

test("lineIndexFromTextOffset resolves caret line by newline boundaries", () => {
  const text = "aa\nbbb\ncccc";
  assert.equal(lineIndexFromTextOffset(text, 0), 0);
  assert.equal(lineIndexFromTextOffset(text, 1), 0);
  assert.equal(lineIndexFromTextOffset(text, 3), 1);
  assert.equal(lineIndexFromTextOffset(text, 7), 2);
  assert.equal(lineIndexFromTextOffset(text, 999), 2);
});

test("textOffsetForLineIndex returns start offset of requested line", () => {
  const text = "aa\nbbb\ncccc";
  assert.equal(textOffsetForLineIndex(text, 0), 0);
  assert.equal(textOffsetForLineIndex(text, 1), 3);
  assert.equal(textOffsetForLineIndex(text, 2), 7);
  assert.equal(textOffsetForLineIndex(text, 999), text.length);
});

test("lineBandFromLineIndex clamps line index and returns normalized ratios", () => {
  assert.deepEqual(lineBandFromLineIndex(0, 4), {
    lineIndex: 0,
    topRatio: 0,
    heightRatio: 0.25,
    totalLines: 4,
  });
  assert.deepEqual(lineBandFromLineIndex(3, 4), {
    lineIndex: 3,
    topRatio: 0.75,
    heightRatio: 0.25,
    totalLines: 4,
  });
  assert.deepEqual(lineBandFromLineIndex(99, 4), {
    lineIndex: 3,
    topRatio: 0.75,
    heightRatio: 0.25,
    totalLines: 4,
  });
});

test("detectEditorValidationIssues detects markdown table and fence problems", () => {
  const markdownTable = "| a | b |\n|---|---|\n| 1 | 2 |";
  assert.deepEqual(detectEditorValidationIssues({ content: markdownTable, format: "markdown" }), [
    {
      code: "markdown_table",
      severity: "warn",
      label: "Markdown table detected",
    },
  ]);

  const unbalancedFence = "Text\n```js\nconst x = 1;\n";
  assert.deepEqual(detectEditorValidationIssues({ content: unbalancedFence, format: "markdown" }), [
    {
      code: "markdown_fence",
      severity: "warn",
      label: "Unbalanced code fences",
    },
  ]);
});

test("detectEditorValidationIssues detects latex brace mismatches", () => {
  const brokenLatex = "\\frac{a}{b";
  assert.deepEqual(detectEditorValidationIssues({ content: brokenLatex, format: "latex" }), [
    {
      code: "latex_braces",
      severity: "warn",
      label: "Unbalanced braces",
    },
  ]);

  assert.deepEqual(detectEditorValidationIssues({ content: "\\frac{a}{b}", format: "latex" }), []);
});

test("applyInlineMarkdownWrapper wraps selected text and preserves inner selection", () => {
  const result = applyInlineMarkdownWrapper({
    content: "alpha beta",
    selectionStart: 6,
    selectionEnd: 10,
    left: "**",
    right: "**",
  });
  assert.deepEqual(result, {
    content: "alpha **beta**",
    selectionStart: 8,
    selectionEnd: 12,
  });
});

test("applyInlineMarkdownWrapper inserts placeholder when selection is empty", () => {
  const result = applyInlineMarkdownWrapper({
    content: "alpha",
    selectionStart: 5,
    selectionEnd: 5,
    left: "$",
    right: "$",
    placeholder: "formula",
  });
  assert.deepEqual(result, {
    content: "alpha$formula$",
    selectionStart: 6,
    selectionEnd: 13,
  });
});

test("applyLinePrefixMarkdown prefixes current line for unordered list", () => {
  const result = applyLinePrefixMarkdown({
    content: "alpha\nbeta",
    selectionStart: 1,
    selectionEnd: 1,
    kind: "unordered",
  });
  assert.deepEqual(result, {
    content: "- alpha\nbeta",
    selectionStart: 3,
    selectionEnd: 3,
  });
});

test("applyLinePrefixMarkdown prefixes selected lines for ordered list", () => {
  const result = applyLinePrefixMarkdown({
    content: "alpha\nbeta\ngamma",
    selectionStart: 0,
    selectionEnd: 10,
    kind: "ordered",
  });
  assert.deepEqual(result, {
    content: "1. alpha\n2. beta\ngamma",
    selectionStart: 3,
    selectionEnd: 16,
  });
});

test("tokenBoundsAtOffset detects words and punctuation runs", () => {
  const text = "Hello, world!!";
  assert.deepEqual(tokenBoundsAtOffset(text, 1), {
    start: 0,
    end: 5,
    token: "Hello",
    kind: "word",
  });
  assert.deepEqual(tokenBoundsAtOffset(text, 5), {
    start: 5,
    end: 6,
    token: ",",
    kind: "punct",
  });
  assert.deepEqual(tokenBoundsAtOffset(text, 12), {
    start: 12,
    end: 14,
    token: "!!",
    kind: "punct",
  });
});

test("tokenBoundsAtOffset skips whitespace when selecting token", () => {
  const text = "alpha  beta";
  assert.deepEqual(tokenBoundsAtOffset(text, 5), {
    start: 0,
    end: 5,
    token: "alpha",
    kind: "word",
  });
  assert.deepEqual(tokenBoundsAtOffset(text, 6), {
    start: 7,
    end: 11,
    token: "beta",
    kind: "word",
  });
});

test("findBestTokenOccurrence chooses nearest whole-word token", () => {
  const text = "abc abcd abc";
  assert.deepEqual(
    findBestTokenOccurrence(text, "abc", { preferredOffset: 10, wholeWord: true }),
    { start: 9, end: 12 },
  );
  assert.deepEqual(
    findBestTokenOccurrence(text, "abc", { preferredOffset: 2, wholeWord: true }),
    { start: 0, end: 3 },
  );
});

test("findBestTokenOccurrence supports punctuation and non-word matches", () => {
  const text = "a, b, c";
  assert.deepEqual(
    findBestTokenOccurrence(text, ",", { preferredOffset: 4, wholeWord: false }),
    { start: 4, end: 5 },
  );
});

test("isReconstructedRestoreDisabled disables for busy states and skip format", () => {
  assert.equal(
    isReconstructedRestoreDisabled({
      reviewSubmitInProgress: true,
      reextractInProgress: false,
      outputFormat: "markdown",
    }),
    true,
  );
  assert.equal(
    isReconstructedRestoreDisabled({
      reviewSubmitInProgress: false,
      reextractInProgress: true,
      outputFormat: "markdown",
    }),
    true,
  );
  assert.equal(
    isReconstructedRestoreDisabled({
      reviewSubmitInProgress: false,
      reextractInProgress: false,
      outputFormat: "SKIP",
    }),
    true,
  );
  assert.equal(
    isReconstructedRestoreDisabled({
      reviewSubmitInProgress: false,
      reextractInProgress: false,
      outputFormat: "markdown",
    }),
    false,
  );
});

test("isRectOnscreen validates intersection with viewport", () => {
  const viewport = { windowWidth: 1200, windowHeight: 800 };
  assert.equal(
    isRectOnscreen({ top: 100, bottom: 300, left: 200, right: 600, width: 400, height: 200 }, viewport),
    true,
  );
  assert.equal(
    isRectOnscreen({ top: -250, bottom: -5, left: 100, right: 500, width: 400, height: 245 }, viewport),
    false,
  );
  assert.equal(
    isRectOnscreen({ top: 10, bottom: 200, left: 1300, right: 1500, width: 200, height: 190 }, viewport),
    false,
  );
});

test("computeFloatingControlPlacement hides when anchor is offscreen", () => {
  const placement = computeFloatingControlPlacement({
    anchorRect: { top: 900, bottom: 1100, left: 100, right: 500, width: 400, height: 200 },
    controlHeight: 30,
    windowWidth: 1200,
    windowHeight: 800,
  });
  assert.deepEqual(placement, { visible: false, top: null, right: null });
});

test("computeFloatingControlPlacement clamps top within anchor bounds", () => {
  const placement = computeFloatingControlPlacement({
    anchorRect: { top: 120, bottom: 620, left: 300, right: 1000, width: 700, height: 500 },
    controlHeight: 32,
    windowWidth: 1280,
    windowHeight: 900,
    desiredTop: 10,
    edgeInset: 6,
  });
  assert.equal(placement.visible, true);
  assert.equal(placement.top, 126);
  assert.equal(placement.right, 286);
});

test("computeFloatingControlPlacement sticks to desired top while panel stays around it", () => {
  const placement = computeFloatingControlPlacement({
    anchorRect: { top: -120, bottom: 520, left: 280, right: 980, width: 700, height: 640 },
    controlHeight: 28,
    windowWidth: 1280,
    windowHeight: 900,
    desiredTop: 10,
    edgeInset: 6,
  });
  assert.equal(placement.visible, true);
  assert.equal(placement.top, 10);
  assert.equal(placement.right, 306);
});

test("computeFloatingControlPlacement clamps to panel bottom when needed", () => {
  const placement = computeFloatingControlPlacement({
    anchorRect: { top: -500, bottom: 24, left: 280, right: 980, width: 700, height: 524 },
    controlHeight: 22,
    windowWidth: 1280,
    windowHeight: 900,
    desiredTop: 10,
    edgeInset: 6,
  });
  assert.equal(placement.visible, true);
  assert.equal(placement.top, -4);
  assert.equal(placement.right, 306);
});
