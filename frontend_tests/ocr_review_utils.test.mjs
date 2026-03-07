import test from "node:test";
import assert from "node:assert/strict";

import {
  computeFloatingControlPlacement,
  hasLocalDraftForLayout,
  isRectOnscreen,
  isReconstructedRestoreDisabled,
  normalizeReconstructedRenderMode,
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
