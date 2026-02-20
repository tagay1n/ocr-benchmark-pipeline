import test from "node:test";
import assert from "node:assert/strict";

import {
  clampZoomPercent,
  compactReadingOrdersAfterDeletion,
  computeViewportCenterPadding,
  computeViewportScrollTargetForLayoutId,
  computeViewportScrollToCenterBBox,
  computeZoomScale,
  formatZoomPercent,
  normalizeReviewHistory,
  nextLayoutReviewUrl,
  pointHandleForCoordinateKey,
  previousHistoryPageId,
  updateReviewHistoryOnVisit,
} from "../app/static/js/layout_review_utils.mjs";

test("clampZoomPercent clamps and falls back for invalid values", () => {
  assert.equal(clampZoomPercent("abc"), 100);
  assert.equal(clampZoomPercent(1), 1);
  assert.equal(clampZoomPercent(95), 95);
  assert.equal(clampZoomPercent(999), 400);
});

test("formatZoomPercent renders integer and 1-decimal labels", () => {
  assert.equal(formatZoomPercent(100), "100%");
  assert.equal(formatZoomPercent(49.14), "49.1%");
  assert.equal(formatZoomPercent(49.15), "49.2%");
});

test("computeZoomScale supports fit modes and custom percentages", () => {
  const base = {
    naturalWidth: 2000,
    naturalHeight: 1000,
    viewportWidth: 1000,
    viewportHeight: 600,
  };

  assert.equal(computeZoomScale({ ...base, mode: "fit-width", zoomPercent: 100 }), 0.5);
  assert.equal(computeZoomScale({ ...base, mode: "fit-page", zoomPercent: 100 }), 0.5);
  assert.equal(computeZoomScale({ ...base, mode: "automatic", zoomPercent: 100 }), 0.5);
  assert.equal(computeZoomScale({ ...base, mode: "custom", zoomPercent: 175 }), 1.75);
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
