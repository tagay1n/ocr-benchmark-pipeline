import test from "node:test";
import assert from "node:assert/strict";

import {
  clampMagnifierZoom,
  computeMagnifierLensPosition,
  computeMagnifierSampleRect,
} from "../app/static/js/magnifier.mjs";

test("clampMagnifierZoom keeps value in allowed range", () => {
  assert.equal(clampMagnifierZoom(4), 4);
  assert.equal(clampMagnifierZoom(0.5), 2);
  assert.equal(clampMagnifierZoom(20), 8);
  assert.equal(clampMagnifierZoom("bad"), 4);
});

test("computeMagnifierSampleRect returns centered crop in natural coordinates", () => {
  const rect = computeMagnifierSampleRect({
    naturalWidth: 1200,
    naturalHeight: 1600,
    displayWidth: 600,
    displayHeight: 800,
    pointerNaturalX: 600,
    pointerNaturalY: 800,
    lensSize: 180,
    zoom: 4,
  });
  assert.ok(rect);
  assert.equal(Math.round(rect.width), 90);
  assert.equal(Math.round(rect.height), 90);
  assert.equal(Math.round(rect.left), 555);
  assert.equal(Math.round(rect.top), 755);
});

test("computeMagnifierSampleRect clamps crop near borders", () => {
  const rect = computeMagnifierSampleRect({
    naturalWidth: 1000,
    naturalHeight: 1000,
    displayWidth: 500,
    displayHeight: 500,
    pointerNaturalX: 12,
    pointerNaturalY: 20,
    lensSize: 200,
    zoom: 4,
  });
  assert.ok(rect);
  assert.equal(rect.left, 0);
  assert.equal(rect.top, 0);
});

test("computeMagnifierLensPosition keeps lens inside viewport", () => {
  const nearBottomRight = computeMagnifierLensPosition({
    clientX: 790,
    clientY: 590,
    lensSize: 180,
    viewportWidth: 800,
    viewportHeight: 600,
  });
  assert.deepEqual(nearBottomRight, { left: 612, top: 412 });

  const nearTopLeft = computeMagnifierLensPosition({
    clientX: 1,
    clientY: 1,
    lensSize: 180,
    viewportWidth: 800,
    viewportHeight: 600,
  });
  assert.deepEqual(nearTopLeft, { left: 21, top: 21 });
});
