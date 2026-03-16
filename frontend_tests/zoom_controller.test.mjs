import test from "node:test";
import assert from "node:assert/strict";

import {
  closeZoomMenu,
  loadStoredZoomSettings,
  openZoomMenu,
  rebuildZoomPresetOptions,
  setZoomInputFromApplied,
  updateZoomMenuSelection,
} from "../app/static/js/zoom_controller.mjs";

test("close/open zoom menu update hidden state and aria-expanded", () => {
  const zoomMenu = { hidden: false };
  const zoomTrigger = {
    attrs: {},
    setAttribute(name, value) {
      this.attrs[name] = value;
    },
  };

  closeZoomMenu(zoomMenu, zoomTrigger);
  assert.equal(zoomMenu.hidden, true);
  assert.equal(zoomTrigger.attrs["aria-expanded"], "false");

  openZoomMenu(zoomMenu, zoomTrigger);
  assert.equal(zoomMenu.hidden, false);
  assert.equal(zoomTrigger.attrs["aria-expanded"], "true");
});

test("updateZoomMenuSelection activates matching mode and custom percent option", () => {
  function makeOption(mode, percent) {
    return {
      dataset: {
        zoomMode: mode ?? "",
        zoomPercent: percent ?? "",
      },
      classList: {
        state: new Set(),
        toggle(name, enabled) {
          if (enabled) {
            this.state.add(name);
          } else {
            this.state.delete(name);
          }
        },
      },
    };
  }

  const fitWidthOption = makeOption("fit-width", "");
  const custom100Option = makeOption("", "100");
  const custom125Option = makeOption("", "125");
  const options = [fitWidthOption, custom100Option, custom125Option];

  updateZoomMenuSelection(options, { zoomMode: "fit-width", zoomPercent: 100 });
  assert.equal(fitWidthOption.classList.state.has("active"), true);
  assert.equal(custom100Option.classList.state.has("active"), false);

  updateZoomMenuSelection(options, { zoomMode: "custom", zoomPercent: 124.6 });
  assert.equal(fitWidthOption.classList.state.has("active"), false);
  assert.equal(custom100Option.classList.state.has("active"), false);
  assert.equal(custom125Option.classList.state.has("active"), true);
});

test("setZoomInputFromApplied rounds and writes zoom input value", () => {
  const input = { value: "" };
  setZoomInputFromApplied(input, 88.7);
  assert.equal(input.value, "89");
});

test("loadStoredZoomSettings normalizes mode and applies clamped stored percent", () => {
  const storage = new Map([
    ["zoom.mode", " fit-width "],
    ["zoom.percent", "999"],
  ]);
  const payload = loadStoredZoomSettings({
    readStorage: (key) => (storage.has(key) ? storage.get(key) : null),
    zoomModeKey: "zoom.mode",
    zoomPercentKey: "zoom.percent",
    normalizeZoomMode: (value, { fallback }) => {
      const normalized = String(value || "").trim().toLowerCase();
      return normalized || fallback;
    },
    clampZoomPercent: (value) => Math.min(400, Math.max(1, Number(value))),
    fallbackMode: "automatic",
  });

  assert.deepEqual(payload, {
    zoomMode: "fit-width",
    zoomPercent: 400,
    zoomAppliedPercent: 100,
  });
});

test("rebuildZoomPresetOptions safely falls back without DOM document support", () => {
  const baseOption = { dataset: { zoomMode: "fit-width" } };
  const removableA = { removeCalled: false, remove() { this.removeCalled = true; } };
  const removableB = { removeCalled: false, remove() { this.removeCalled = true; } };
  const zoomMenu = {
    querySelector(selector) {
      if (selector === ".zoom-separator") {
        return { after() {} };
      }
      return null;
    },
    querySelectorAll(selector) {
      if (selector === ".zoom-option[data-zoom-percent]") {
        return [removableA, removableB];
      }
      if (selector === ".zoom-option") {
        return [baseOption];
      }
      return [];
    },
  };

  const options = rebuildZoomPresetOptions(zoomMenu, [10, 20, 30]);
  assert.deepEqual(options, [baseOption]);
  assert.equal(removableA.removeCalled, true);
  assert.equal(removableB.removeCalled, true);
});
