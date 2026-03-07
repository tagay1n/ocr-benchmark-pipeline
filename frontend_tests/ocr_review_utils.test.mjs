import test from "node:test";
import assert from "node:assert/strict";

import {
  hasLocalDraftForLayout,
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
