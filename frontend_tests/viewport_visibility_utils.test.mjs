import test from "node:test";
import assert from "node:assert/strict";

import {
  ensureNormalizedBBoxVisible,
  isNormalizedBBoxVisible,
  normalizeBBoxRect,
} from "../app/static/js/viewport_visibility_utils.mjs";

test("normalizeBBoxRect clamps and normalizes coordinate order", () => {
  assert.deepEqual(
    normalizeBBoxRect({
      x1: 0.9,
      y1: -1,
      x2: 0.1,
      y2: 2,
    }),
    {
      x1: 0.1,
      y1: 0,
      x2: 0.9,
      y2: 1,
    },
  );
  assert.equal(normalizeBBoxRect({ x1: 0.5, y1: 0.4, x2: 0.5, y2: 0.7 }), null);
});

test("isNormalizedBBoxVisible checks bbox visibility within padded viewport", () => {
  const viewport = {
    clientWidth: 200,
    clientHeight: 200,
    scrollLeft: 100,
    scrollTop: 100,
  };
  const content = {
    clientWidth: 1000,
    clientHeight: 1000,
  };
  assert.equal(
    isNormalizedBBoxVisible(
      { x1: 0.13, y1: 0.13, x2: 0.27, y2: 0.27 },
      viewport,
      content,
      { paddingPx: 20 },
    ),
    true,
  );
  assert.equal(
    isNormalizedBBoxVisible(
      { x1: 0.08, y1: 0.13, x2: 0.22, y2: 0.27 },
      viewport,
      content,
      { paddingPx: 20 },
    ),
    false,
  );
});

test("ensureNormalizedBBoxVisible adjusts viewport when bbox is outside", () => {
  const viewport = {
    clientWidth: 200,
    clientHeight: 200,
    scrollLeft: 0,
    scrollTop: 0,
  };
  const content = {
    clientWidth: 1000,
    clientHeight: 1000,
  };
  const changed = ensureNormalizedBBoxVisible(
    { x1: 0.9, y1: 0.9, x2: 0.95, y2: 0.96 },
    viewport,
    content,
    { paddingPx: 20 },
  );
  assert.equal(changed, true);
  assert.equal(viewport.scrollLeft, 770);
  assert.equal(viewport.scrollTop, 780);
});

test("ensureNormalizedBBoxVisible does not move when bbox is already visible", () => {
  const viewport = {
    clientWidth: 200,
    clientHeight: 200,
    scrollLeft: 100,
    scrollTop: 100,
  };
  const content = {
    clientWidth: 1000,
    clientHeight: 1000,
  };
  const changed = ensureNormalizedBBoxVisible(
    { x1: 0.13, y1: 0.13, x2: 0.27, y2: 0.27 },
    viewport,
    content,
    { paddingPx: 20 },
  );
  assert.equal(changed, false);
  assert.equal(viewport.scrollLeft, 100);
  assert.equal(viewport.scrollTop, 100);
});
