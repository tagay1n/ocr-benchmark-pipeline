export function formatStatusLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .trim()
    .toUpperCase();
}

export function setToggleButtonActiveState(button, enabled) {
  if (typeof HTMLButtonElement !== "undefined") {
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }
  } else if (!button || typeof button !== "object") {
    return;
  }
  const active = Boolean(enabled);
  button.classList.toggle("active", active);
  button.setAttribute("aria-pressed", active ? "true" : "false");
}

export function resolveViewportBottomLeftDockCorner(
  viewport,
  nearBottomThreshold,
  {
    defaultCorner = "bottom-left",
    nearBottomCorner = "top-left",
  } = {},
) {
  if (
    !viewport ||
    typeof viewport !== "object" ||
    typeof viewport.scrollHeight !== "number" ||
    typeof viewport.clientHeight !== "number" ||
    typeof viewport.scrollTop !== "number"
  ) {
    return String(defaultCorner);
  }
  const maxScrollTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
  if (maxScrollTop <= 0) {
    return String(defaultCorner);
  }
  const distanceToBottom = Math.max(0, maxScrollTop - viewport.scrollTop);
  return distanceToBottom <= Number(nearBottomThreshold)
    ? String(nearBottomCorner)
    : String(defaultCorner);
}

export function isInteractiveShortcutTarget(target) {
  if (typeof Element !== "undefined") {
    if (!(target instanceof Element)) {
      return false;
    }
  } else if (!target || typeof target !== "object") {
    return false;
  }
  if (target.closest("input, textarea, select, button, [contenteditable='true']")) {
    return true;
  }
  if (typeof HTMLElement !== "undefined") {
    return target instanceof HTMLElement && target.isContentEditable;
  }
  return Boolean(target.isContentEditable);
}

function setBadgeTitle(badge, value) {
  if (!badge || typeof badge !== "object") {
    return;
  }
  const title = String(value || "").trim();
  if (title) {
    badge.title = title;
    return;
  }
  if (typeof badge.removeAttribute === "function") {
    badge.removeAttribute("title");
  } else {
    badge.title = "";
  }
}

export function updateReviewStateBadge({
  badge,
  status,
  needsReviewStatus,
  reviewedStatus,
  needsReviewTitle = "",
  reviewedTitle = "",
  unknownTitleFormatter = null,
} = {}) {
  if (!badge || typeof badge !== "object") {
    return "missing";
  }
  if (badge.classList && typeof badge.classList.remove === "function") {
    badge.classList.remove("needs-review", "reviewed", "unknown");
  }
  const normalizedStatus = String(status || "").trim();
  if (!normalizedStatus) {
    badge.hidden = true;
    badge.textContent = "";
    setBadgeTitle(badge, "");
    return "hidden";
  }

  badge.hidden = false;
  if (normalizedStatus === String(needsReviewStatus || "").trim()) {
    badge.textContent = "NEEDS REVIEW";
    if (badge.classList && typeof badge.classList.add === "function") {
      badge.classList.add("needs-review");
    }
    setBadgeTitle(badge, needsReviewTitle);
    return "needs_review";
  }
  if (normalizedStatus === String(reviewedStatus || "").trim()) {
    badge.textContent = "REVIEWED";
    if (badge.classList && typeof badge.classList.add === "function") {
      badge.classList.add("reviewed");
    }
    setBadgeTitle(badge, reviewedTitle);
    return "reviewed";
  }

  badge.textContent = formatStatusLabel(normalizedStatus);
  if (badge.classList && typeof badge.classList.add === "function") {
    badge.classList.add("unknown");
  }
  if (typeof unknownTitleFormatter === "function") {
    setBadgeTitle(badge, unknownTitleFormatter(normalizedStatus));
  } else {
    setBadgeTitle(badge, "");
  }
  return "unknown";
}

export function updateHistoryNavigationButtons({
  historyBackButton,
  historyForwardButton,
  backTarget = null,
  forwardHistoryTarget = null,
  queueTarget = null,
  labels = {},
} = {}) {
  const noBackTitle = String(labels.noBackTitle || "No previous reviewed page in history.");
  const backTitle = String(labels.backTitle || "Open previous reviewed page");
  const forwardHistoryTitle = String(labels.forwardHistoryTitle || "Open next reviewed page in history.");
  const forwardQueueTitle = String(labels.forwardQueueTitle || "Open next page for review.");
  const noForwardTitle = String(labels.noForwardTitle || "No next page for review.");

  const hasBackTarget = Number.isInteger(backTarget) && backTarget > 0;
  if (historyBackButton) {
    historyBackButton.disabled = !hasBackTarget;
    historyBackButton.title = hasBackTarget ? backTitle : noBackTitle;
  }

  const hasForwardHistoryTarget = Number.isInteger(forwardHistoryTarget) && forwardHistoryTarget > 0;
  if (hasForwardHistoryTarget) {
    if (historyForwardButton) {
      historyForwardButton.disabled = false;
      historyForwardButton.title = forwardHistoryTitle;
    }
    return {
      hasBackTarget,
      hasForwardHistoryTarget: true,
      hasQueueTarget: Number.isInteger(queueTarget) && queueTarget > 0,
    };
  }

  const hasQueueTarget = Number.isInteger(queueTarget) && queueTarget > 0;
  if (historyForwardButton) {
    historyForwardButton.disabled = !hasQueueTarget;
    historyForwardButton.title = hasQueueTarget ? forwardQueueTitle : noForwardTitle;
  }
  return {
    hasBackTarget,
    hasForwardHistoryTarget: false,
    hasQueueTarget,
  };
}
