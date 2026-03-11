import test from "node:test";
import assert from "node:assert/strict";

import {
  clampMagnifierZoom,
  computeDockedMagnifierPosition,
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
  assert.deepEqual(nearTopLeft, { left: 8, top: 8 });
});

test("computeDockedMagnifierPosition prefers placing lens outside viewport on the left", () => {
  const position = computeDockedMagnifierPosition({
    lensSize: 180,
    viewportRect: { left: 320, top: 16, right: 840, bottom: 700 },
    viewportGap: 10,
    edgeInset: 8,
    windowWidth: 1280,
    windowHeight: 800,
  });
  assert.deepEqual(position, { left: 130, top: 510 });
});

test("computeDockedMagnifierPosition falls back to bottom-left viewport corner when no outside space exists", () => {
  const position = computeDockedMagnifierPosition({
    lensSize: 180,
    viewportRect: { left: 20, top: 12, right: 780, bottom: 580 },
    viewportGap: 10,
    edgeInset: 8,
    windowWidth: 800,
    windowHeight: 600,
  });
  assert.deepEqual(position, { left: 8, top: 412 });
});

test("computeDockedMagnifierPosition can anchor inside viewport bottom-left corner", () => {
  const position = computeDockedMagnifierPosition({
    lensSize: 180,
    viewportRect: { left: 200, top: 40, right: 920, bottom: 700 },
    viewportGap: 10,
    edgeInset: 8,
    windowWidth: 1280,
    windowHeight: 800,
    dockInsideViewport: true,
    dockCorner: "bottom-left",
  });
  assert.deepEqual(position, { left: 210, top: 510 });
});

test("computeDockedMagnifierPosition can anchor inside viewport top-left corner", () => {
  const position = computeDockedMagnifierPosition({
    lensSize: 180,
    viewportRect: { left: 200, top: 40, right: 920, bottom: 700 },
    viewportGap: 10,
    edgeInset: 8,
    windowWidth: 1280,
    windowHeight: 800,
    dockInsideViewport: true,
    dockCorner: "top-left",
  });
  assert.deepEqual(position, { left: 210, top: 50 });
});
