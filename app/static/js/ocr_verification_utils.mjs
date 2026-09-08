export const ATTENTION_STATES = new Set([
  "disagreement_full",
  "disagreement_reduced",
  "manual_check",
]);

export function evidenceLabel(finding) {
  const state = String(finding?.state || "");
  if (state.endsWith("_full")) return "Full evidence";
  if (state.endsWith("_reduced")) return "Reduced evidence";
  if (state === "manual_check") return "Source-only check";
  if (state === "waiting") return "Waiting for models";
  return state.replaceAll("_", " ");
}

export function visibleForFilter(finding, filter) {
  if (filter === "all") return true;
  if (filter === "resolved") return Boolean(finding?.resolved);
  if (finding?.resolved) return false;
  if (filter === "attention") return ATTENTION_STATES.has(String(finding?.state || ""));
  if (filter === "agreement") return String(finding?.state || "").startsWith("agreed_");
  return String(finding?.state || "") === filter;
}

export function verificationControlState({
  isRunning = false,
  stopRequested = false,
  runStatus = "",
  actionInFlight = "",
  recalculateBusy = false,
} = {}) {
  const running = Boolean(isRunning);
  const pendingAction = String(actionInFlight || "");
  const stopping = running && (
    Boolean(stopRequested)
    || runStatus === "stop_requested"
    || pendingAction === "stop"
  );
  const anotherActionBusy = Boolean(pendingAction) || Boolean(recalculateBusy);
  const recalculateDisabled = running || anotherActionBusy;
  const recalculateTitle = running
    ? "Stop verification before recalculating findings."
    : "Recalculate findings from stored verification outputs.";

  if (stopping) {
    return {
      actionLabel: "Stopping…",
      actionDanger: true,
      actionDisabled: true,
      actionTitle: "Stopping verification after the current model request.",
      recalculateDisabled,
      recalculateTitle,
    };
  }
  if (running) {
    return {
      actionLabel: "Stop verification",
      actionDanger: true,
      actionDisabled: Boolean(recalculateBusy),
      actionTitle: "Stop verification after the current model request.",
      recalculateDisabled,
      recalculateTitle,
    };
  }
  const resumable = runStatus === "stopped" || runStatus === "quota_exhausted";
  return {
    actionLabel: resumable ? "Resume verification" : "Start verification",
    actionDanger: false,
    actionDisabled: anotherActionBusy,
    actionTitle: resumable
      ? "Resume verification using stored progress."
      : "Start OCR verification.",
    recalculateDisabled,
    recalculateTitle,
  };
}

export function compactDiff(baseline, candidate) {
  const left = String(baseline ?? "");
  const right = String(candidate ?? "");
  if (left === right) return { prefix: right, removed: "", changed: "", suffix: "" };
  let prefixLength = 0;
  while (
    prefixLength < left.length &&
    prefixLength < right.length &&
    left[prefixLength] === right[prefixLength]
  ) prefixLength += 1;
  let suffixLength = 0;
  while (
    suffixLength < left.length - prefixLength &&
    suffixLength < right.length - prefixLength &&
    left[left.length - 1 - suffixLength] === right[right.length - 1 - suffixLength]
  ) suffixLength += 1;
  return {
    prefix: right.slice(0, prefixLength),
    removed: left.slice(prefixLength, suffixLength ? left.length - suffixLength : left.length),
    changed: right.slice(prefixLength, suffixLength ? right.length - suffixLength : right.length),
    suffix: suffixLength ? right.slice(right.length - suffixLength) : "",
  };
}
