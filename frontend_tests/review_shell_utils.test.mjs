import test from "node:test";
import assert from "node:assert/strict";

import {
  formatStatusLabel,
  updateHistoryNavigationButtons,
  updateReviewStateBadge,
} from "../app/static/js/review_shell_utils.mjs";

function makeBadge() {
  const classes = new Set();
  return {
    hidden: false,
    textContent: "",
    title: "",
    classList: {
      add(name) {
        classes.add(name);
      },
      remove(...names) {
        for (const name of names) {
          classes.delete(name);
        }
      },
      has(name) {
        return classes.has(name);
      },
    },
    removeAttribute(name) {
      if (name === "title") {
        this.title = "";
      }
    },
  };
}

test("formatStatusLabel renders uppercase with spaces", () => {
  assert.equal(formatStatusLabel("ocr_reviewed"), "OCR REVIEWED");
  assert.equal(formatStatusLabel(" layout_detected "), "LAYOUT DETECTED");
});

test("updateReviewStateBadge handles needs-review and reviewed statuses", () => {
  const badge = makeBadge();
  const needsResult = updateReviewStateBadge({
    badge,
    status: "layout_detected",
    needsReviewStatus: "layout_detected",
    reviewedStatus: "layout_reviewed",
    needsReviewTitle: "waiting",
    reviewedTitle: "done",
  });
  assert.equal(needsResult, "needs_review");
  assert.equal(badge.hidden, false);
  assert.equal(badge.textContent, "NEEDS REVIEW");
  assert.equal(badge.classList.has("needs-review"), true);
  assert.equal(badge.title, "waiting");

  const reviewedResult = updateReviewStateBadge({
    badge,
    status: "layout_reviewed",
    needsReviewStatus: "layout_detected",
    reviewedStatus: "layout_reviewed",
    needsReviewTitle: "waiting",
    reviewedTitle: "done",
  });
  assert.equal(reviewedResult, "reviewed");
  assert.equal(badge.textContent, "REVIEWED");
  assert.equal(badge.classList.has("reviewed"), true);
  assert.equal(badge.title, "done");
});

test("updateReviewStateBadge handles unknown and empty status", () => {
  const badge = makeBadge();
  const unknownResult = updateReviewStateBadge({
    badge,
    status: "ocr_failed",
    needsReviewStatus: "ocr_done",
    reviewedStatus: "ocr_reviewed",
    unknownTitleFormatter: (status) => `current: ${status}`,
  });
  assert.equal(unknownResult, "unknown");
  assert.equal(badge.textContent, "OCR FAILED");
  assert.equal(badge.classList.has("unknown"), true);
  assert.equal(badge.title, "current: ocr_failed");

  const hiddenResult = updateReviewStateBadge({
    badge,
    status: "",
    needsReviewStatus: "ocr_done",
    reviewedStatus: "ocr_reviewed",
  });
  assert.equal(hiddenResult, "hidden");
  assert.equal(badge.hidden, true);
  assert.equal(badge.textContent, "");
});

test("updateHistoryNavigationButtons prefers forward history over queue target", () => {
  const back = { disabled: false, title: "" };
  const forward = { disabled: false, title: "" };

  const result = updateHistoryNavigationButtons({
    historyBackButton: back,
    historyForwardButton: forward,
    backTarget: 3,
    forwardHistoryTarget: 5,
    queueTarget: 7,
    labels: {
      backTitle: "back",
      noBackTitle: "noback",
      forwardHistoryTitle: "fh",
      forwardQueueTitle: "fq",
      noForwardTitle: "nof",
    },
  });

  assert.deepEqual(result, {
    hasBackTarget: true,
    hasForwardHistoryTarget: true,
    hasQueueTarget: true,
  });
  assert.equal(back.disabled, false);
  assert.equal(back.title, "back");
  assert.equal(forward.disabled, false);
  assert.equal(forward.title, "fh");
});

test("updateHistoryNavigationButtons uses queue fallback and disables when no targets", () => {
  const back = { disabled: false, title: "" };
  const forward = { disabled: false, title: "" };
  updateHistoryNavigationButtons({
    historyBackButton: back,
    historyForwardButton: forward,
    backTarget: null,
    forwardHistoryTarget: null,
    queueTarget: null,
    labels: {
      backTitle: "back",
      noBackTitle: "noback",
      forwardHistoryTitle: "fh",
      forwardQueueTitle: "fq",
      noForwardTitle: "nof",
    },
  });
  assert.equal(back.disabled, true);
  assert.equal(back.title, "noback");
  assert.equal(forward.disabled, true);
  assert.equal(forward.title, "nof");
});
