import test from "node:test";
import assert from "node:assert/strict";

import {
  historyNavigationTargets,
  loadReviewHistoryState,
  persistReviewHistoryState,
  registerCurrentPageVisit,
  sanitizeReviewHistoryFromPages,
} from "../app/static/js/review_history_controller.mjs";

test("persistReviewHistoryState writes serialized history and index", () => {
  const writes = [];
  persistReviewHistoryState({
    writeStorage: (key, value) => writes.push([key, value]),
    historyKey: "h",
    historyIndexKey: "i",
    history: [1, 2, 3],
    historyIndex: 2,
  });
  assert.deepEqual(writes, [
    ["h", "[1,2,3]"],
    ["i", "2"],
  ]);
});

test("loadReviewHistoryState parses and normalizes history payload", () => {
  const storage = new Map([
    ["h", "[1,2,3]"],
    ["i", "1"],
  ]);
  const state = loadReviewHistoryState({
    readStorage: (key) => storage.get(key) ?? null,
    historyKey: "h",
    historyIndexKey: "i",
    normalizeReviewHistory: (history, index) => ({ history, index: Number(index) }),
  });
  assert.deepEqual(state, { history: [1, 2, 3], index: 1 });
});

test("sanitizeReviewHistoryFromPages filters by non-missing pages and current page", () => {
  const filtered = sanitizeReviewHistoryFromPages({
    history: [10, 11, 12, 13],
    historyIndex: 2,
    pages: [
      { id: 10, is_missing: false },
      { id: 12, is_missing: true },
      { id: 13, is_missing: false },
    ],
    currentPageId: 12,
    filterReviewHistory: (history, index, validIds) => ({
      history: history.filter((id) => validIds.has(id)),
      index,
    }),
  });
  assert.deepEqual(filtered, { history: [10, 12, 13], index: 2 });
});

test("registerCurrentPageVisit delegates to updateReviewHistoryOnVisit", () => {
  const next = registerCurrentPageVisit({
    history: [1, 2],
    historyIndex: 1,
    currentPageId: 3,
    updateReviewHistoryOnVisit: (history, index, pageId) => ({
      history: history.concat([pageId]),
      index: index + 1,
    }),
  });
  assert.deepEqual(next, { history: [1, 2, 3], index: 2 });
});

test("historyNavigationTargets derives valid positive targets only", () => {
  const targets = historyNavigationTargets({
    history: [1, 2, 3],
    historyIndex: 1,
    nextReviewPageId: "7",
    previousHistoryPageId: () => 1,
    nextHistoryPageId: () => 3,
  });
  assert.deepEqual(targets, {
    backTarget: 1,
    forwardHistoryTarget: 3,
    queueTarget: 7,
  });
});
