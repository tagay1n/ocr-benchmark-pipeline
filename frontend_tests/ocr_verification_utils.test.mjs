import assert from "node:assert/strict";
import test from "node:test";

import {
  compactDiff,
  evidenceLabel,
  verificationControlState,
  visibleForFilter,
} from "../app/static/js/ocr_verification_utils.mjs";

test("verification evidence labels distinguish reduced and source-only checks", () => {
  assert.equal(evidenceLabel({ state: "agreed_full" }), "Full evidence");
  assert.equal(evidenceLabel({ state: "disagreement_reduced" }), "Reduced evidence");
  assert.equal(evidenceLabel({ state: "manual_check" }), "Source-only check");
});

test("attention filter includes disagreements and manual checks but not agreements", () => {
  assert.equal(visibleForFilter({ state: "disagreement_full", resolved: false }, "attention"), true);
  assert.equal(visibleForFilter({ state: "manual_check", resolved: false }, "attention"), true);
  assert.equal(visibleForFilter({ state: "agreed_reduced", resolved: false }, "attention"), false);
  assert.equal(visibleForFilter({ state: "manual_check", resolved: true }, "attention"), false);
});

test("compact diff isolates a fabricated suffix", () => {
  assert.deepEqual(compactDiff("Текст", "Текст уйдырма"), {
    prefix: "Текст",
    removed: "",
    changed: " уйдырма",
    suffix: "",
  });
  assert.deepEqual(compactDiff("a", "ba"), {
    prefix: "",
    removed: "",
    changed: "b",
    suffix: "a",
  });
  assert.deepEqual(compactDiff("Текст уйдырма", "Текст"), {
    prefix: "Текст",
    removed: " уйдырма",
    changed: "",
    suffix: "",
  });
});

test("verification controls expose a stoppable running state", () => {
  assert.deepEqual(
    verificationControlState({ isRunning: true }),
    {
      actionLabel: "Stop verification",
      actionDanger: true,
      actionDisabled: false,
      actionTitle: "Stop verification after the current model request.",
      recalculateDisabled: true,
      recalculateTitle: "Stop verification before recalculating findings.",
    },
  );
});

test("verification controls lock duplicate stops while shutdown completes", () => {
  assert.deepEqual(
    verificationControlState({ isRunning: true, stopRequested: true }),
    {
      actionLabel: "Stopping…",
      actionDanger: true,
      actionDisabled: true,
      actionTitle: "Stopping verification after the current model request.",
      recalculateDisabled: true,
      recalculateTitle: "Stop verification before recalculating findings.",
    },
  );
});

test("verification controls allow stopping while the start request is still preparing tasks", () => {
  const preparing = verificationControlState({
    isRunning: true,
    actionInFlight: "start",
  });
  assert.equal(preparing.actionLabel, "Stop verification");
  assert.equal(preparing.actionDisabled, false);

  const stopping = verificationControlState({
    isRunning: true,
    actionInFlight: "stop",
  });
  assert.equal(stopping.actionLabel, "Stopping…");
  assert.equal(stopping.actionDisabled, true);
});

test("verification controls keep duplicate starts locked before running status arrives", () => {
  const starting = verificationControlState({ actionInFlight: "start" });
  assert.equal(starting.actionLabel, "Start verification");
  assert.equal(starting.actionDisabled, true);
});

test("verification controls distinguish start and resume and lock concurrent actions", () => {
  assert.equal(verificationControlState({}).actionLabel, "Start verification");
  assert.equal(
    verificationControlState({ runStatus: "stopped" }).actionLabel,
    "Resume verification",
  );
  assert.equal(
    verificationControlState({ runStatus: "quota_exhausted" }).actionLabel,
    "Resume verification",
  );
  const busy = verificationControlState({ actionInFlight: "start" });
  assert.equal(busy.actionDisabled, true);
  assert.equal(busy.recalculateDisabled, true);
});
