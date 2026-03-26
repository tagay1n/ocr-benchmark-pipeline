import test from "node:test";
import assert from "node:assert/strict";

import {
  applyInlineMarkdownWrapper,
  applyLinePrefixMarkdown,
  computeLineReviewDisplayGeometry,
  computeReconstructedImageCropStyle,
  computeViewportAutoCenterTarget,
  computeEditorToolbarState,
  countTextLines,
  computeFloatingControlPlacement,
  detectEditorValidationIssues,
  findBestTokenOccurrence,
  hasLocalDraftForLayout,
  isRectOnscreen,
  isLineReviewRequiredOutput,
  isReconstructedRestoreDisabled,
  isLineSyncEnabledOutputFormat,
  lineBandFromLineIndex,
  lineIndexFromPointerOffset,
  lineIndexFromTextOffset,
  normalizeLayoutOrientationValue,
  normalizeReviewViewMode,
  normalizeReconstructedRenderMode,
  reconstructedLayerRankForOutputClass,
  resolveLineMatchingOrientation,
  resolveLineMatchingBandCount,
  resolveReconstructedLineFlow,
  resolveLineBandAxisRect,
  resolveOutputEffectiveOrientation,
  resolveViewportScrollSyncUpdate,
  resolveEditorDrawerLayout,
  tokenBoundsAtOffset,
  textOffsetForLineIndex,
} from "../app/static/js/ocr_review_utils.mjs";

test("computeReconstructedImageCropStyle converts bbox to scalable crop percentages", () => {
  assert.deepEqual(
    computeReconstructedImageCropStyle({
      x1: 0.1,
      y1: 0.2,
      x2: 0.6,
      y2: 0.7,
    }),
    {
      widthPercent: 200,
      heightPercent: 200,
      leftPercent: -20,
      topPercent: -40,
    },
  );
});

test("computeReconstructedImageCropStyle clamps malformed inputs and rejects empty boxes", () => {
  assert.deepEqual(
    computeReconstructedImageCropStyle({
      x1: -0.5,
      y1: "0.25",
      x2: 2,
      y2: 0.75,
    }),
    {
      widthPercent: 100,
      heightPercent: 200,
      leftPercent: 0,
      topPercent: -50,
    },
  );
  assert.equal(
    computeReconstructedImageCropStyle({
      x1: 0.3,
      y1: 0.4,
      x2: 0.3,
      y2: 0.9,
    }),
    null,
  );
});

test("computeLineReviewDisplayGeometry uses bbox width fallback when no crop metrics are provided", () => {
  const geometry = computeLineReviewDisplayGeometry({
    bbox: { x1: 0.3, y1: 0.1, x2: 0.7, y2: 0.2 },
  });
  assert.ok(Math.abs(geometry.widthRatio - 0.4) < 1e-9);
  assert.ok(Math.abs(geometry.leftRatio - 0.3) < 1e-9);
  assert.equal(geometry.heightPx, 44);
});

test("computeLineReviewDisplayGeometry adapts width by crop aspect and clamps to configured bounds", () => {
  const geometry = computeLineReviewDisplayGeometry({
    bbox: { x1: 0.1, y1: 0.1, x2: 0.2, y2: 0.9 },
    crop: { cropWidth: 0.1, cropHeight: 0.8 },
    reelWidth: 1000,
    imageWidth: 1000,
    imageHeight: 2000,
    targetHeightPx: 44,
    minHeightPx: 30,
    maxHeightPx: 62,
    minWidthPx: 120,
    minWidthRatioFallback: 0.08,
    maxWidthRatio: 0.94,
  });
  assert.equal(geometry.heightPx, 62);
  assert.equal(geometry.widthRatio, 0.12);
  assert.equal(geometry.leftRatio, 0.44);
});

test("normalizeReconstructedRenderMode defaults to markdown and accepts raw", () => {
  assert.equal(normalizeReconstructedRenderMode(undefined), "markdown");
  assert.equal(normalizeReconstructedRenderMode(null), "markdown");
  assert.equal(normalizeReconstructedRenderMode(""), "markdown");
  assert.equal(normalizeReconstructedRenderMode("raw"), "raw");
  assert.equal(normalizeReconstructedRenderMode(" RAW "), "raw");
  assert.equal(normalizeReconstructedRenderMode("markdown"), "markdown");
  assert.equal(normalizeReconstructedRenderMode("something-else"), "markdown");
});

test("normalizeReviewViewMode defaults to two_panels and accepts only two supported modes", () => {
  assert.equal(normalizeReviewViewMode(undefined), "two_panels");
  assert.equal(normalizeReviewViewMode(null), "two_panels");
  assert.equal(normalizeReviewViewMode(""), "two_panels");
  assert.equal(normalizeReviewViewMode("line_by_line"), "line_by_line");
  assert.equal(normalizeReviewViewMode(" line-by-line "), "line_by_line");
  assert.equal(normalizeReviewViewMode("focused_strip"), "line_by_line");
  assert.equal(normalizeReviewViewMode("two_panels"), "two_panels");
  assert.equal(normalizeReviewViewMode("two-panels"), "two_panels");
  assert.equal(normalizeReviewViewMode("side_by_side"), "two_panels");
  assert.equal(normalizeReviewViewMode("anything-else"), "two_panels");
});

test("isLineSyncEnabledOutputFormat enables line sync only for markdown outputs", () => {
  assert.equal(isLineSyncEnabledOutputFormat("markdown"), true);
  assert.equal(isLineSyncEnabledOutputFormat(" MARKDOWN "), true);
  assert.equal(isLineSyncEnabledOutputFormat("html"), false);
  assert.equal(isLineSyncEnabledOutputFormat("latex"), false);
  assert.equal(isLineSyncEnabledOutputFormat("skip"), false);
  assert.equal(isLineSyncEnabledOutputFormat(""), false);
});

test("isLineReviewRequiredOutput includes formula/latex and text-like classes", () => {
  assert.equal(
    isLineReviewRequiredOutput({ className: "formula", outputFormat: "latex" }),
    true,
  );
  assert.equal(
    isLineReviewRequiredOutput({ className: "formula", outputFormat: "markdown" }),
    false,
  );
  assert.equal(
    isLineReviewRequiredOutput({ className: "picture_text", outputFormat: "markdown" }),
    true,
  );
  assert.equal(
    isLineReviewRequiredOutput({ className: "picture", outputFormat: "skip" }),
    false,
  );
  assert.equal(
    isLineReviewRequiredOutput({ className: "table", outputFormat: "html" }),
    false,
  );
});

test("reconstructedLayerRankForOutputClass keeps picture below picture_text and text-like content", () => {
  assert.equal(reconstructedLayerRankForOutputClass("picture"), 1);
  assert.equal(reconstructedLayerRankForOutputClass("Picture Text"), 3);
  assert.equal(reconstructedLayerRankForOutputClass("text"), 2);
  assert.equal(reconstructedLayerRankForOutputClass("table"), 2);
});

test("resolveViewportScrollSyncUpdate returns null for already synced scroll and next values otherwise", () => {
  assert.equal(
    resolveViewportScrollSyncUpdate({
      sourceLeft: 120,
      sourceTop: 45,
      targetLeft: 120,
      targetTop: 45,
    }),
    null,
  );
  assert.deepEqual(
    resolveViewportScrollSyncUpdate({
      sourceLeft: "80",
      sourceTop: 30.5,
      targetLeft: 79,
      targetTop: 30.5,
    }),
    { left: 80, top: 30.5 },
  );
  assert.deepEqual(
    resolveViewportScrollSyncUpdate({
      sourceLeft: NaN,
      sourceTop: Infinity,
      targetLeft: 1,
      targetTop: 2,
    }),
    { left: 0, top: 0 },
  );
});

test("computeViewportAutoCenterTarget keeps viewport when box stays within context window", () => {
  const target = computeViewportAutoCenterTarget({
    bbox: { x1: 0.2, y1: 0.3, x2: 0.3, y2: 0.4 },
    contentWidth: 1000,
    contentHeight: 2000,
    viewportWidth: 500,
    viewportHeight: 600,
    currentLeft: 100,
    currentTop: 400,
    horizontalMarginRatio: 0.1,
    verticalMarginRatio: 0.1,
  });
  assert.equal(target, null);
});

test("computeViewportAutoCenterTarget nudges when target escapes context margins", () => {
  const target = computeViewportAutoCenterTarget({
    bbox: { x1: 0.7, y1: 0.8, x2: 0.82, y2: 0.9 },
    contentWidth: 1000,
    contentHeight: 2000,
    viewportWidth: 500,
    viewportHeight: 600,
    currentLeft: 100,
    currentTop: 400,
    horizontalMarginRatio: 0.2,
    verticalMarginRatio: 0.2,
  });
  assert.deepEqual(target, { left: 420, top: 1320 });
});

test("computeViewportAutoCenterTarget supports preferred vertical centering mode", () => {
  const target = computeViewportAutoCenterTarget({
    bbox: { x1: 0.15, y1: 0.55, x2: 0.35, y2: 0.62 },
    contentWidth: 1200,
    contentHeight: 2400,
    viewportWidth: 600,
    viewportHeight: 800,
    currentLeft: 0,
    currentTop: 200,
    preferVerticalCenter: true,
    centerThresholdPx: 4,
  });
  assert.deepEqual(target, { left: 0, top: 1004 });
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

test("normalizeLayoutOrientationValue supports compact aliases and fallback", () => {
  assert.equal(normalizeLayoutOrientationValue("vertical"), "vertical");
  assert.equal(normalizeLayoutOrientationValue("v"), "vertical");
  assert.equal(normalizeLayoutOrientationValue("horizontal"), "horizontal");
  assert.equal(normalizeLayoutOrientationValue("h"), "horizontal");
  assert.equal(normalizeLayoutOrientationValue("unknown"), "horizontal");
  assert.equal(normalizeLayoutOrientationValue("unknown", { fallback: "vertical" }), "vertical");
});

test("resolveOutputEffectiveOrientation prefers explicit effective orientation then declared orientation", () => {
  assert.equal(
    resolveOutputEffectiveOrientation({
      orientation: "horizontal",
      effectiveOrientation: "vertical",
      bbox: { x1: 0.1, y1: 0.1, x2: 0.4, y2: 0.9 },
    }),
    "vertical",
  );
  assert.equal(
    resolveOutputEffectiveOrientation({
      orientation: "v",
      effectiveOrientation: "",
      bbox: { x1: 0.1, y1: 0.1, x2: 0.4, y2: 0.9 },
    }),
    "vertical",
  );
  assert.equal(
    resolveOutputEffectiveOrientation({
      orientation: "",
      effectiveOrientation: "",
      bbox: { x1: 0.2, y1: 0.1, x2: 0.3, y2: 0.8 },
    }),
    "vertical",
  );
  assert.equal(
    resolveOutputEffectiveOrientation({
      orientation: "",
      effectiveOrientation: "",
      bbox: { x1: 0.1, y1: 0.2, x2: 0.8, y2: 0.3 },
    }),
    "horizontal",
  );
});

test("lineIndexFromPointerOffset maps pointer offset to clamped line index", () => {
  assert.equal(lineIndexFromPointerOffset({ offset: 0, axisSize: 100, totalLines: 4 }), 0);
  assert.equal(lineIndexFromPointerOffset({ offset: 24.9, axisSize: 100, totalLines: 4 }), 0);
  assert.equal(lineIndexFromPointerOffset({ offset: 25, axisSize: 100, totalLines: 4 }), 1);
  assert.equal(lineIndexFromPointerOffset({ offset: 99.9, axisSize: 100, totalLines: 4 }), 3);
  assert.equal(lineIndexFromPointerOffset({ offset: 1000, axisSize: 100, totalLines: 4 }), 3);
  assert.equal(lineIndexFromPointerOffset({ offset: -10, axisSize: 100, totalLines: 4 }), 0);
});

test("resolveLineBandAxisRect maps line bands to row or column geometry", () => {
  const band = { topRatio: 0.25, heightRatio: 0.2 };
  assert.deepEqual(resolveLineBandAxisRect(band, "horizontal"), {
    leftRatio: 0,
    topRatio: 0.25,
    widthRatio: 1,
    heightRatio: 0.2,
  });
  assert.deepEqual(resolveLineBandAxisRect(band, "vertical"), {
    leftRatio: 0.25,
    topRatio: 0,
    widthRatio: 0.2,
    heightRatio: 1,
  });
});

test("resolveReconstructedLineFlow enables vertical flow only for vertical text-like markdown outputs", () => {
  assert.equal(
    resolveReconstructedLineFlow({
      className: "page_footer",
      outputFormat: "markdown",
      orientation: "vertical",
      effectiveOrientation: "vertical",
      bbox: { x1: 0.92, y1: 0.71, x2: 0.94, y2: 0.92 },
    }),
    "vertical",
  );
  assert.equal(
    resolveReconstructedLineFlow({
      className: "page_footer",
      outputFormat: "latex",
      orientation: "vertical",
      effectiveOrientation: "vertical",
      bbox: { x1: 0.92, y1: 0.71, x2: 0.94, y2: 0.92 },
    }),
    "horizontal",
  );
  assert.equal(
    resolveReconstructedLineFlow({
      className: "picture",
      outputFormat: "markdown",
      orientation: "vertical",
      effectiveOrientation: "vertical",
      bbox: { x1: 0.92, y1: 0.71, x2: 0.94, y2: 0.92 },
    }),
    "horizontal",
  );
});

test("resolveLineMatchingOrientation keeps vertical axis for vertical text-like outputs", () => {
  const base = {
    className: "page_footer",
    outputFormat: "markdown",
    orientation: "vertical",
    effectiveOrientation: "vertical",
    bbox: { x1: 0.92, y1: 0.71, x2: 0.94, y2: 0.92 },
  };
  assert.equal(resolveLineMatchingOrientation({ ...base, totalLines: 1 }), "vertical");
  assert.equal(resolveLineMatchingOrientation({ ...base, totalLines: 3 }), "vertical");
  assert.equal(
    resolveLineMatchingOrientation({
      className: "picture",
      outputFormat: "markdown",
      orientation: "vertical",
      effectiveOrientation: "vertical",
      bbox: base.bbox,
      totalLines: 2,
    }),
    "horizontal",
  );
  assert.equal(
    resolveLineMatchingOrientation({
      className: "text",
      outputFormat: "markdown",
      orientation: "horizontal",
      effectiveOrientation: "horizontal",
      bbox: { x1: 0.1, y1: 0.1, x2: 0.9, y2: 0.2 },
      totalLines: 2,
    }),
    "horizontal",
  );
});

test("vertical matching with a single line maps to full bbox", () => {
  const orientation = resolveLineMatchingOrientation({
    className: "page_footer",
    outputFormat: "markdown",
    orientation: "vertical",
    effectiveOrientation: "vertical",
    bbox: { x1: 0.92, y1: 0.71, x2: 0.94, y2: 0.92 },
    totalLines: 1,
  });
  const fullBand = lineBandFromLineIndex(0, 1);
  assert.deepEqual(resolveLineBandAxisRect(fullBand, orientation), {
    leftRatio: 0,
    topRatio: 0,
    widthRatio: 1,
    heightRatio: 1,
  });
});

test("resolveLineMatchingBandCount collapses tall narrow vertical boxes to single matching band", () => {
  const base = {
    className: "page_footer",
    outputFormat: "markdown",
    orientation: "vertical",
    effectiveOrientation: "vertical",
  };
  assert.equal(
    resolveLineMatchingBandCount({
      ...base,
      bbox: { x1: 0.9234, y1: 0.7155, x2: 0.941, y2: 0.9204 },
      totalLines: 3,
    }),
    1,
  );
  assert.equal(
    resolveLineMatchingBandCount({
      ...base,
      bbox: { x1: 0.7, y1: 0.3, x2: 0.95, y2: 0.95 },
      totalLines: 3,
    }),
    3,
  );
  assert.equal(
    resolveLineMatchingBandCount({
      className: "text",
      outputFormat: "markdown",
      orientation: "horizontal",
      effectiveOrientation: "horizontal",
      bbox: { x1: 0.1, y1: 0.4, x2: 0.9, y2: 0.8 },
      totalLines: 5,
    }),
    5,
  );
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

test("findBestTokenOccurrence returns null when token is missing or empty", () => {
  assert.equal(findBestTokenOccurrence("abc def", "xyz", { preferredOffset: 0 }), null);
  assert.equal(findBestTokenOccurrence("abc def", "", { preferredOffset: 0 }), null);
});

test("computeEditorToolbarState toggles visibility and markdown action availability", () => {
  assert.deepEqual(computeEditorToolbarState({ editorHidden: true, outputFormat: "markdown" }), {
    toolbarHidden: true,
    markdownActionsEnabled: false,
  });
  assert.deepEqual(computeEditorToolbarState({ editorHidden: false, outputFormat: "markdown" }), {
    toolbarHidden: false,
    markdownActionsEnabled: true,
  });
  assert.deepEqual(computeEditorToolbarState({ editorHidden: false, outputFormat: "latex" }), {
    toolbarHidden: false,
    markdownActionsEnabled: false,
  });
});

test("resolveEditorDrawerLayout disables resizing under breakpoint", () => {
  assert.deepEqual(
    resolveEditorDrawerLayout({
      requestedWidth: 700,
      viewportWidth: 1100,
      minWidth: 420,
      maxRatio: 0.9,
      responsiveBreakpoint: 1120,
    }),
    { resizable: false, width: null },
  );
});

test("resolveEditorDrawerLayout clamps width to min and max bounds", () => {
  assert.deepEqual(
    resolveEditorDrawerLayout({
      requestedWidth: 200,
      viewportWidth: 1400,
      minWidth: 420,
      maxRatio: 0.9,
      responsiveBreakpoint: 1120,
    }),
    { resizable: true, width: 420 },
  );
  assert.deepEqual(
    resolveEditorDrawerLayout({
      requestedWidth: 2000,
      viewportWidth: 1400,
      minWidth: 420,
      maxRatio: 0.9,
      responsiveBreakpoint: 1120,
    }),
    { resizable: true, width: 1260 },
  );
});

test("resolveEditorDrawerLayout keeps resizable state with null width for invalid input", () => {
  assert.deepEqual(
    resolveEditorDrawerLayout({
      requestedWidth: null,
      viewportWidth: 1400,
      minWidth: 420,
      maxRatio: 0.9,
      responsiveBreakpoint: 1120,
    }),
    { resizable: true, width: null },
  );
});

test("resolveEditorDrawerLayout returns non-resizable for invalid viewport", () => {
  assert.deepEqual(
    resolveEditorDrawerLayout({
      requestedWidth: 600,
      viewportWidth: 0,
      minWidth: 420,
      maxRatio: 0.9,
      responsiveBreakpoint: 1120,
    }),
    { resizable: false, width: null },
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
