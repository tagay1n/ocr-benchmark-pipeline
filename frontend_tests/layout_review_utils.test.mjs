import test from "node:test";
import assert from "node:assert/strict";

import {
  clampZoomPercent,
  countStretchableGlyphs,
  countStretchableSpaces,
  compactReadingOrdersAfterDeletion,
  computeApproxLineBand,
  computeApproxLineBandByIndex,
  computeDraggedBBox,
  computeOverlayBadgeScale,
  detectOverlappingBorderSegments,
  filterReviewHistory,
  mergeLayoutsForReview,
  computeViewportCenterPadding,
  computeViewportScrollTargetForLayoutId,
  computeViewportScrollToCenterBBox,
  computeZoomScale,
  findMaxFittingFontSize,
  formatZoomPercent,
  isLayoutNotFoundErrorMessage,
  normalizeReviewHistory,
  normalizeZoomMode,
  nextHistoryPageId,
  nextManualReadingOrder,
  nextLayoutReviewUrl,
  pointHandleForCoordinateKey,
  previousHistoryPageId,
  reconstructionHorizontalScale,
  reconstructionLetterSpacing,
  reconstructionLineHeight,
  reconstructionWordSpacing,
  reorderReadingOrderIds,
  updateReviewHistoryOnVisit,
  ZOOM_PRESET_PERCENTS,
} from "../app/static/js/layout_review_utils.mjs";

test("clampZoomPercent clamps and falls back for invalid values", () => {
  assert.equal(clampZoomPercent("abc"), 100);
  assert.equal(clampZoomPercent(1), 1);
  assert.equal(clampZoomPercent(95), 95);
  assert.equal(clampZoomPercent(999), 400);
});

test("normalizeZoomMode accepts known modes and falls back for invalid values", () => {
  assert.equal(normalizeZoomMode("fit-width"), "fit-width");
  assert.equal(normalizeZoomMode("fit-height"), "fit-height");
  assert.equal(normalizeZoomMode("custom"), "custom");
  assert.equal(normalizeZoomMode("custom", { allowCustom: false }), "automatic");
  assert.equal(normalizeZoomMode("invalid"), "automatic");
  assert.equal(normalizeZoomMode("", { fallback: "fit-page" }), "fit-page");
});

test("formatZoomPercent renders integer and 1-decimal labels", () => {
  assert.equal(formatZoomPercent(100), "100%");
  assert.equal(formatZoomPercent(49.14), "49.1%");
  assert.equal(formatZoomPercent(49.15), "49.2%");
});

test("isLayoutNotFoundErrorMessage matches exact backend not-found detail", () => {
  assert.equal(isLayoutNotFoundErrorMessage("Layout not found."), true);
  assert.equal(isLayoutNotFoundErrorMessage("Layout not found"), true);
  assert.equal(isLayoutNotFoundErrorMessage("layout not found."), true);
  assert.equal(isLayoutNotFoundErrorMessage("Layout not Found."), true);
  assert.equal(isLayoutNotFoundErrorMessage("Page not found."), false);
  assert.equal(isLayoutNotFoundErrorMessage(""), false);
});

test("computeZoomScale supports fit modes and custom percentages", () => {
  const base = {
    naturalWidth: 2000,
    naturalHeight: 1000,
    viewportWidth: 1000,
    viewportHeight: 600,
  };

  assert.equal(computeZoomScale({ ...base, mode: "fit-width", zoomPercent: 100 }), 0.5);
  assert.equal(computeZoomScale({ ...base, mode: "fit-height", zoomPercent: 100 }), 0.6);
  assert.equal(computeZoomScale({ ...base, mode: "fit-page", zoomPercent: 100 }), 0.5);
  assert.equal(computeZoomScale({ ...base, mode: "automatic", zoomPercent: 100 }), 0.5);
  assert.equal(computeZoomScale({ ...base, mode: "custom", zoomPercent: 175 }), 1.75);
});

test("computeZoomScale accounts for top gutter in fit-page and fit-height", () => {
  const base = {
    naturalWidth: 1000,
    naturalHeight: 1000,
    viewportWidth: 1000,
    viewportHeight: 1000,
    extraVerticalSpace: 24,
  };

  assert.equal(computeZoomScale({ ...base, mode: "fit-height", zoomPercent: 100 }), 0.976);
  assert.equal(computeZoomScale({ ...base, mode: "fit-page", zoomPercent: 100 }), 0.976);
  assert.equal(computeZoomScale({ ...base, mode: "fit-width", zoomPercent: 100 }), 1);
});

test("automatic mode avoids upscaling smaller images", () => {
  const scale = computeZoomScale({
    mode: "automatic",
    zoomPercent: 100,
    naturalWidth: 500,
    naturalHeight: 400,
    viewportWidth: 1000,
    viewportHeight: 600,
  });
  assert.equal(scale, 1);
});

test("computeZoomScale returns null when dimensions are unavailable", () => {
  const scale = computeZoomScale({
    mode: "fit-page",
    zoomPercent: 100,
    naturalWidth: 0,
    naturalHeight: 800,
    viewportWidth: 1200,
    viewportHeight: 700,
  });
  assert.equal(scale, null);
});

test("computeOverlayBadgeScale uses adaptive bounded scaling", () => {
  assert.equal(computeOverlayBadgeScale(1), 0.95);
  assert.equal(computeOverlayBadgeScale(0.25), 0.85);
  assert.equal(computeOverlayBadgeScale(4), 1.35);
  assert.equal(computeOverlayBadgeScale(999), 1.35);
  assert.equal(computeOverlayBadgeScale(0), 0.95);
  assert.equal(computeOverlayBadgeScale(Number.NaN), 0.95);
});

test("shared zoom presets include low-scale shortcuts and remain ordered", () => {
  assert.deepEqual(
    ZOOM_PRESET_PERCENTS,
    [10, 20, 30, 40, 50, 70, 85, 100, 125, 150, 175, 200, 300, 400],
  );
});

test("findMaxFittingFontSize chooses the largest fitting size", () => {
  const threshold = 23.75;
  const result = findMaxFittingFontSize({
    minFontSize: 6,
    maxFontSize: 40,
    iterations: 16,
    fitsAtFontSize(fontSize) {
      return fontSize <= threshold;
    },
  });
  assert.ok(result > 23.0 && result < 24.0);
});

test("findMaxFittingFontSize falls back to min when even min does not fit", () => {
  const result = findMaxFittingFontSize({
    minFontSize: 6,
    maxFontSize: 40,
    iterations: 16,
    fitsAtFontSize() {
      return false;
    },
  });
  assert.equal(result, 6);
});

test("reconstructionLineHeight returns tighter defaults by format", () => {
  assert.equal(reconstructionLineHeight("markdown"), 1.1);
  assert.equal(reconstructionLineHeight("html"), 1.08);
  assert.equal(reconstructionLineHeight("latex"), 1.02);
});

test("reconstructionHorizontalScale expands width in a controlled range", () => {
  assert.equal(
    reconstructionHorizontalScale({
      measuredContentWidth: 200,
      availableWidth: 220,
      maxScale: 1.3,
      minGainRatio: 0.02,
    }),
    1.1,
  );
  assert.equal(
    reconstructionHorizontalScale({
      measuredContentWidth: 200,
      availableWidth: 202,
      maxScale: 1.3,
      minGainRatio: 0.02,
    }),
    1,
  );
  assert.equal(
    reconstructionHorizontalScale({
      measuredContentWidth: 200,
      availableWidth: 500,
      maxScale: 1.18,
      minGainRatio: 0,
    }),
    1.18,
  );
});

test("countStretchableSpaces counts plain spaces only", () => {
  assert.equal(countStretchableSpaces("a b  c"), 3);
  assert.equal(countStretchableSpaces("a\tb\nc"), 0);
  assert.equal(countStretchableSpaces(""), 0);
});

test("countStretchableGlyphs ignores whitespace characters", () => {
  assert.equal(countStretchableGlyphs("ab c"), 3);
  assert.equal(countStretchableGlyphs("a\tb\nc\r d"), 4);
  assert.equal(countStretchableGlyphs("   "), 0);
});

test("reconstructionWordSpacing computes bounded spacing from width gap", () => {
  assert.equal(
    reconstructionWordSpacing({
      measuredContentWidth: 180,
      availableWidth: 210,
      spacesCount: 15,
      maxWordSpacing: 3,
      minGainRatio: 0.01,
    }),
    2,
  );
  assert.equal(
    reconstructionWordSpacing({
      measuredContentWidth: 198,
      availableWidth: 200,
      spacesCount: 10,
      maxWordSpacing: 3,
      minGainRatio: 0.02,
    }),
    0,
  );
  assert.equal(
    reconstructionWordSpacing({
      measuredContentWidth: 100,
      availableWidth: 200,
      spacesCount: 2,
      maxWordSpacing: 1.5,
      minGainRatio: 0,
    }),
    1.5,
  );
});

test("reconstructionLetterSpacing computes bounded spacing from width gap", () => {
  assert.equal(
    reconstructionLetterSpacing({
      measuredContentWidth: 180,
      availableWidth: 210,
      glyphsCount: 31,
      maxLetterSpacing: 1,
      minGainRatio: 0.005,
    }),
    1,
  );
  assert.equal(
    reconstructionLetterSpacing({
      measuredContentWidth: 198,
      availableWidth: 200,
      glyphsCount: 20,
      maxLetterSpacing: 1,
      minGainRatio: 0.02,
    }),
    0,
  );
  assert.equal(
    reconstructionLetterSpacing({
      measuredContentWidth: 198,
      availableWidth: 200,
      glyphsCount: 1,
      maxLetterSpacing: 1,
      minGainRatio: 0,
    }),
    0,
  );
});

test("pointHandleForCoordinateKey maps bbox coordinates to corner handles", () => {
  assert.equal(pointHandleForCoordinateKey("x1"), "nw");
  assert.equal(pointHandleForCoordinateKey("y1"), "nw");
  assert.equal(pointHandleForCoordinateKey("x2"), "se");
  assert.equal(pointHandleForCoordinateKey("y2"), "se");
  assert.equal(pointHandleForCoordinateKey("unknown"), null);
});

test("compactReadingOrdersAfterDeletion shifts all orders after deleted position", () => {
  const layouts = [
    { id: 11, reading_order: 1, class_name: "text" },
    { id: 12, reading_order: 2, class_name: "text" },
    { id: 13, reading_order: 3, class_name: "text" },
    { id: 14, reading_order: null, class_name: "text" },
  ];

  const { layouts: compacted, shiftedIds } = compactReadingOrdersAfterDeletion(layouts.slice(1), 1);
  assert.deepEqual(
    compacted.map((item) => ({ id: item.id, order: item.reading_order })),
    [
      { id: 12, order: 1 },
      { id: 13, order: 2 },
      { id: 14, order: null },
    ],
  );
  assert.deepEqual(shiftedIds, [12, 13]);
});

test("compactReadingOrdersAfterDeletion is no-op when deleted order is invalid", () => {
  const layouts = [
    { id: 21, reading_order: 2 },
    { id: 22, reading_order: 5 },
  ];
  const { layouts: compacted, shiftedIds } = compactReadingOrdersAfterDeletion(layouts, null);
  assert.deepEqual(compacted, layouts);
  assert.deepEqual(shiftedIds, []);
});

test("nextManualReadingOrder appends after visible draft rows", () => {
  assert.equal(nextManualReadingOrder([]), 1);
  assert.equal(nextManualReadingOrder(null), 1);
  assert.equal(
    nextManualReadingOrder([
      { id: 101, reading_order: 4 },
      { id: 102, reading_order: 9 },
      { id: null, reading_order: 10 },
    ]),
    3,
  );
});

test("reorderReadingOrderIds reorders ids before and after target", () => {
  assert.deepEqual(
    reorderReadingOrderIds({
      orderedIds: [10, 20, 30, 40],
      draggedId: 30,
      targetId: 10,
      position: "before",
    }),
    [30, 10, 20, 40],
  );

  assert.deepEqual(
    reorderReadingOrderIds({
      orderedIds: [10, 20, 30, 40],
      draggedId: 20,
      targetId: 40,
      position: "after",
    }),
    [10, 30, 40, 20],
  );
});

test("reorderReadingOrderIds supports drop to end and rejects invalid payload", () => {
  assert.deepEqual(
    reorderReadingOrderIds({
      orderedIds: [1, 2, 3],
      draggedId: 1,
      targetId: null,
    }),
    [2, 3, 1],
  );

  assert.equal(
    reorderReadingOrderIds({
      orderedIds: [1, 2, 3],
      draggedId: 99,
      targetId: 2,
    }),
    null,
  );
});

test("mergeLayoutsForReview keeps editable layouts isolated from server baseline", () => {
  const sourceLayouts = [
    {
      id: 101,
      class_name: "text",
      reading_order: 1,
      bbox: { x1: 0.1, y1: 0.2, x2: 0.8, y2: 0.6 },
      bound_target_ids: [],
    },
  ];

  const { serverLayoutsById, mergedLayouts } = mergeLayoutsForReview({
    layouts: sourceLayouts,
    localEditsById: {},
    deletedLayoutIds: [],
  });

  mergedLayouts[0].bbox.x1 = 0.3333;
  assert.equal(serverLayoutsById["101"].bbox.x1, 0.1);
});

test("computeViewportScrollToCenterBBox centers target and clamps at edges", () => {
  const centered = computeViewportScrollToCenterBBox({
    bbox: { x1: 0.45, y1: 0.45, x2: 0.55, y2: 0.55 },
    contentWidth: 2000,
    contentHeight: 1000,
    viewportWidth: 1000,
    viewportHeight: 500,
  });
  assert.deepEqual(centered, { left: 500, top: 250 });

  const nearTopLeft = computeViewportScrollToCenterBBox({
    bbox: { x1: 0.01, y1: 0.01, x2: 0.05, y2: 0.05 },
    contentWidth: 2000,
    contentHeight: 1000,
    viewportWidth: 1000,
    viewportHeight: 500,
  });
  assert.deepEqual(nearTopLeft, { left: 0, top: 0 });

  const nearBottomRight = computeViewportScrollToCenterBBox({
    bbox: { x1: 0.92, y1: 0.92, x2: 0.99, y2: 0.99 },
    contentWidth: 2000,
    contentHeight: 1000,
    viewportWidth: 1000,
    viewportHeight: 500,
  });
  assert.deepEqual(nearBottomRight, { left: 1000, top: 500 });
});

test("computeViewportScrollTargetForLayoutId resolves scroll target for selected layout", () => {
  const target = computeViewportScrollTargetForLayoutId({
    layoutId: 7,
    layouts: [
      { id: 6, bbox: { x1: 0.05, y1: 0.05, x2: 0.1, y2: 0.1 } },
      { id: 7, bbox: { x1: 0.45, y1: 0.45, x2: 0.55, y2: 0.55 } },
    ],
    contentWidth: 2000,
    contentHeight: 1000,
    viewportWidth: 1000,
    viewportHeight: 500,
  });
  assert.deepEqual(target, { left: 500, top: 250 });
});

test("computeViewportScrollTargetForLayoutId returns null for missing/invalid selection", () => {
  assert.equal(
    computeViewportScrollTargetForLayoutId({
      layoutId: "x",
      layouts: [{ id: 1, bbox: { x1: 0.1, y1: 0.1, x2: 0.2, y2: 0.2 } }],
      contentWidth: 1000,
      contentHeight: 800,
      viewportWidth: 500,
      viewportHeight: 400,
    }),
    null,
  );
  assert.equal(
    computeViewportScrollTargetForLayoutId({
      layoutId: 2,
      layouts: [{ id: 1, bbox: { x1: 0.1, y1: 0.1, x2: 0.2, y2: 0.2 } }],
      contentWidth: 1000,
      contentHeight: 800,
      viewportWidth: 500,
      viewportHeight: 400,
    }),
    null,
  );
});

test("computeDraggedBBox normalizes drag rectangle and clamps to bounds", () => {
  const bbox = computeDraggedBBox({
    startX: -20,
    startY: 40,
    endX: 210,
    endY: 160,
    contentWidth: 200,
    contentHeight: 100,
    minPixels: 5,
  });
  assert.deepEqual(bbox, {
    x1: 0,
    y1: 0.4,
    x2: 1,
    y2: 1,
  });
});

test("computeDraggedBBox rejects tiny drags and invalid inputs", () => {
  assert.equal(
    computeDraggedBBox({
      startX: 10,
      startY: 10,
      endX: 12,
      endY: 40,
      contentWidth: 500,
      contentHeight: 500,
      minPixels: 5,
    }),
    null,
  );

  assert.equal(
    computeDraggedBBox({
      startX: 10,
      startY: 10,
      endX: 50,
      endY: 50,
      contentWidth: 0,
      contentHeight: 500,
      minPixels: 5,
    }),
    null,
  );
});

test("computeApproxLineBand maps y offset to normalized line band", () => {
  const band = computeApproxLineBand({
    offsetY: 23,
    contentHeight: 100,
    lineHeight: 10,
  });
  assert.deepEqual(band, {
    lineIndex: 2,
    topRatio: 0.2,
    heightRatio: 0.1,
    totalLines: 10,
  });
});

test("computeApproxLineBand clamps to content bounds", () => {
  const band = computeApproxLineBand({
    offsetY: 999,
    contentHeight: 95,
    lineHeight: 12,
  });
  assert.equal(band?.lineIndex, 7);
  assert.equal(band?.topRatio, (7 * 12) / 95);
  assert.equal(band?.heightRatio, 11 / 95);
  assert.equal(band?.totalLines, 8);
});

test("computeApproxLineBand returns null for invalid input", () => {
  assert.equal(
    computeApproxLineBand({
      offsetY: 10,
      contentHeight: 0,
      lineHeight: 12,
    }),
    null,
  );
  assert.equal(
    computeApproxLineBand({
      offsetY: Number.NaN,
      contentHeight: 100,
      lineHeight: 12,
    }),
    null,
  );
});

test("computeApproxLineBandByIndex clamps and reports total line count", () => {
  const band = computeApproxLineBandByIndex({
    lineIndex: 999,
    contentHeight: 50,
    lineHeight: 12,
  });
  assert.deepEqual(band, {
    lineIndex: 4,
    topRatio: 48 / 50,
    heightRatio: 2 / 50,
    totalLines: 5,
  });
});

test("computeViewportCenterPadding centers only when content is smaller than viewport", () => {
  const padded = computeViewportCenterPadding({
    contentWidth: 600,
    contentHeight: 300,
    viewportWidth: 1000,
    viewportHeight: 700,
  });
  assert.deepEqual(padded, { x: 200, y: 200 });

  const none = computeViewportCenterPadding({
    contentWidth: 1600,
    contentHeight: 900,
    viewportWidth: 1000,
    viewportHeight: 700,
  });
  assert.deepEqual(none, { x: 0, y: 0 });
});

test("nextLayoutReviewUrl resolves only valid next-page payloads", () => {
  assert.equal(nextLayoutReviewUrl(null), null);
  assert.equal(nextLayoutReviewUrl({ has_next: false, next_page_id: null }), null);
  assert.equal(nextLayoutReviewUrl({ has_next: true, next_page_id: 0 }), null);
  assert.equal(nextLayoutReviewUrl({ has_next: true, next_page_id: "x" }), null);
  assert.equal(
    nextLayoutReviewUrl({ has_next: true, next_page_id: 42 }),
    "/static/layouts.html?page_id=42",
  );
});

test("review history visit appends current page and trims forward branch", () => {
  const state = updateReviewHistoryOnVisit([10, 11, 12], 1, 20, 10);
  assert.deepEqual(state, { history: [10, 11, 20], index: 2 });
});

test("review history visit keeps current page without duplicate push", () => {
  const state = updateReviewHistoryOnVisit([31, 32], 1, 32, 10);
  assert.deepEqual(state, { history: [31, 32], index: 1 });
});

test("normalizeReviewHistory sanitizes invalid payload", () => {
  const state = normalizeReviewHistory(["x", 7, -1, 8], 99);
  assert.deepEqual(state, { history: [7, 8], index: 1 });
});

test("previousHistoryPageId returns previous page only when available", () => {
  assert.equal(previousHistoryPageId([100, 101, 102], 2), 101);
  assert.equal(previousHistoryPageId([100], 0), null);
  assert.equal(previousHistoryPageId([], -1), null);
});

test("nextHistoryPageId returns next page only when available", () => {
  assert.equal(nextHistoryPageId([100, 101, 102], 1), 102);
  assert.equal(nextHistoryPageId([100], 0), null);
  assert.equal(nextHistoryPageId([], -1), null);
});

test("filterReviewHistory drops disallowed ids and remaps active index", () => {
  assert.deepEqual(
    filterReviewHistory([10, 11, 12, 13], 2, [10, 12, 13]),
    { history: [10, 12, 13], index: 1 },
  );
  assert.deepEqual(
    filterReviewHistory([10, 11, 12], 1, [12]),
    { history: [12], index: 0 },
  );
  assert.deepEqual(
    filterReviewHistory([10, 11, 12], 2, []),
    { history: [], index: -1 },
  );
});

test("filtered history keeps consistent back/forward targets", () => {
  const filteredWithForward = filterReviewHistory([5, 6, 7], 1, [5, 7]);
  assert.deepEqual(filteredWithForward, { history: [5, 7], index: 0 });
  assert.equal(previousHistoryPageId(filteredWithForward.history, filteredWithForward.index), null);
  assert.equal(nextHistoryPageId(filteredWithForward.history, filteredWithForward.index), 7);

  const filteredWithoutForward = filterReviewHistory([5, 6, 7], 2, [5, 6]);
  assert.deepEqual(filteredWithoutForward, { history: [5, 6], index: 1 });
  assert.equal(previousHistoryPageId(filteredWithoutForward.history, filteredWithoutForward.index), 5);
  assert.equal(nextHistoryPageId(filteredWithoutForward.history, filteredWithoutForward.index), null);
});

test("reorderReadingOrderIds preserves id set across randomized moves", () => {
  const seed = 1337;
  let state = seed;
  function rand(max) {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state % max;
  }

  const original = Array.from({ length: 20 }, (_, index) => index + 1);
  let ordered = original.slice();
  for (let iteration = 0; iteration < 200; iteration += 1) {
    const draggedId = ordered[rand(ordered.length)];
    const maybeTarget = rand(10) < 2 ? null : ordered[rand(ordered.length)];
    const position = rand(2) === 0 ? "before" : "after";
    const next = reorderReadingOrderIds({
      orderedIds: ordered,
      draggedId,
      targetId: maybeTarget,
      position,
    });
    assert.ok(Array.isArray(next));
    assert.equal(next.length, ordered.length);
    assert.deepEqual([...next].sort((a, b) => a - b), original);
    ordered = next;
  }
});

test("computeDraggedBBox randomized invariants", () => {
  const seed = 20260307;
  let state = seed;
  function rand(max) {
    state = (state * 1103515245 + 12345) >>> 0;
    return state % max;
  }

  for (let iteration = 0; iteration < 200; iteration += 1) {
    const width = 300 + rand(1700);
    const height = 300 + rand(1500);
    const startX = rand(width + 200) - 100;
    const startY = rand(height + 200) - 100;
    const endX = rand(width + 200) - 100;
    const endY = rand(height + 200) - 100;
    const bbox = computeDraggedBBox({
      startX,
      startY,
      endX,
      endY,
      contentWidth: width,
      contentHeight: height,
      minPixels: 5,
    });
    if (bbox === null) {
      continue;
    }
    assert.ok(bbox.x1 >= 0 && bbox.x1 <= 1);
    assert.ok(bbox.y1 >= 0 && bbox.y1 <= 1);
    assert.ok(bbox.x2 >= 0 && bbox.x2 <= 1);
    assert.ok(bbox.y2 >= 0 && bbox.y2 <= 1);
    assert.ok(bbox.x2 > bbox.x1);
    assert.ok(bbox.y2 > bbox.y1);
  }
});

test("detectOverlappingBorderSegments finds shared vertical and horizontal edges", () => {
  const overlaps = detectOverlappingBorderSegments({
    layouts: [
      { id: 1, bbox: { x1: 0.1, y1: 0.1, x2: 0.4, y2: 0.5 } },
      { id: 2, bbox: { x1: 0.05, y1: 0.1, x2: 0.4, y2: 0.8 } },
    ],
    contentWidth: 1000,
    contentHeight: 1000,
    minOverlapPx: 8,
  });

  const vertical = overlaps.find((item) => item.orientation === "vertical");
  const horizontal = overlaps.find((item) => item.orientation === "horizontal");
  assert.ok(vertical);
  assert.ok(horizontal);
  assert.equal(Math.round(vertical.coordPx), 400);
  assert.equal(Math.round(vertical.startPx), 100);
  assert.equal(Math.round(vertical.endPx), 500);
  assert.equal(Math.round(horizontal.coordPx), 100);
  assert.equal(Math.round(horizontal.startPx), 100);
  assert.equal(Math.round(horizontal.endPx), 400);
});

test("detectOverlappingBorderSegments requires true overlap (not merely close)", () => {
  const farDifferent = detectOverlappingBorderSegments({
    layouts: [
      { id: 1, bbox: { x1: 0.2, y1: 0.1, x2: 0.4, y2: 0.6 } },
      { id: 2, bbox: { x1: 0.402, y1: 0.2, x2: 0.7, y2: 0.7 } },
    ],
    contentWidth: 1000,
    contentHeight: 1000,
    minOverlapPx: 1,
  });
  assert.equal(farDifferent.length, 0);

  const onePixelCloseNoMatch = detectOverlappingBorderSegments({
    layouts: [
      { id: 1, bbox: { x1: 0.2, y1: 0.1, x2: 0.4, y2: 0.6 } },
      { id: 2, bbox: { x1: 0.401, y1: 0.2, x2: 0.7, y2: 0.7 } },
    ],
    contentWidth: 1000,
    contentHeight: 1000,
    minOverlapPx: 1,
  });
  assert.equal(onePixelCloseNoMatch.length, 0);

  const exactMatch = detectOverlappingBorderSegments({
    layouts: [
      { id: 1, bbox: { x1: 0.2, y1: 0.1, x2: 0.4, y2: 0.6 } },
      { id: 2, bbox: { x1: 0.4, y1: 0.2, x2: 0.7, y2: 0.7 } },
    ],
    contentWidth: 1000,
    contentHeight: 1000,
    minOverlapPx: 1,
  });
  assert.ok(exactMatch.some((item) => item.orientation === "vertical"));

  const uiPrecisionMatch = detectOverlappingBorderSegments({
    layouts: [
      { id: 1, bbox: { x1: 0.2, y1: 0.1, x2: 0.4, y2: 0.6 } },
      { id: 2, bbox: { x1: 0.4000004, y1: 0.2, x2: 0.7, y2: 0.7 } },
    ],
    contentWidth: 1000,
    contentHeight: 1000,
    minOverlapPx: 1,
  });
  assert.ok(uiPrecisionMatch.some((item) => item.orientation === "vertical"));

  const touchingPointOnly = detectOverlappingBorderSegments({
    layouts: [
      { id: 1, bbox: { x1: 0.2, y1: 0.1, x2: 0.4, y2: 0.6 } },
      { id: 2, bbox: { x1: 0.4, y1: 0.6, x2: 0.7, y2: 0.9 } },
    ],
    contentWidth: 1000,
    contentHeight: 1000,
  });
  assert.equal(touchingPointOnly.length, 0);

  const minOverlapFiltered = detectOverlappingBorderSegments({
    layouts: [
      { id: 1, bbox: { x1: 0.2, y1: 0.1, x2: 0.4, y2: 0.6 } },
      { id: 2, bbox: { x1: 0.4, y1: 0.595, x2: 0.7, y2: 0.9 } },
    ],
    contentWidth: 1000,
    contentHeight: 1000,
    minOverlapPx: 8,
  });
  assert.equal(minOverlapFiltered.length, 0);

  const deepInteriorOverlap = detectOverlappingBorderSegments({
    layouts: [
      { id: 1, bbox: { x1: 0.1, y1: 0.1, x2: 0.8, y2: 0.8 } },
      { id: 2, bbox: { x1: 0.3, y1: 0.3, x2: 0.9, y2: 0.9 } },
    ],
    contentWidth: 1000,
    contentHeight: 1000,
    minOverlapPx: 1,
  });
  assert.ok(deepInteriorOverlap.some((item) => item.orientation === "vertical"));
  assert.ok(deepInteriorOverlap.some((item) => item.orientation === "horizontal"));
});
