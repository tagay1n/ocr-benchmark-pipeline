import test from "node:test";
import assert from "node:assert/strict";

import {
  readStorage,
  readStorageBool,
  removeStorage,
  writeStorage,
} from "../app/static/js/state_event_utils.mjs";

test("state_event_utils read/write/remove and boolean parsing", () => {
  const store = new Map();
  const originalWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem(key) {
        return store.has(key) ? String(store.get(key)) : null;
      },
      setItem(key, value) {
        store.set(key, String(value));
      },
      removeItem(key) {
        store.delete(key);
      },
    },
  };

  try {
    assert.equal(readStorage("missing"), null);
    writeStorage("a", "1");
    assert.equal(readStorage("a"), "1");
    assert.equal(readStorageBool("a", false), true);

    writeStorage("b", "0");
    assert.equal(readStorageBool("b", true), false);
    assert.equal(readStorageBool("missing_bool", true), true);

    removeStorage("a");
    assert.equal(readStorage("a"), null);
  } finally {
    globalThis.window = originalWindow;
  }
});

test("state_event_utils swallows localStorage exceptions", () => {
  const originalWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem() {
        throw new Error("blocked");
      },
      setItem() {
        throw new Error("blocked");
      },
      removeItem() {
        throw new Error("blocked");
      },
    },
  };

  try {
    assert.equal(readStorage("x"), null);
    assert.equal(readStorageBool("x", true), true);
    assert.doesNotThrow(() => writeStorage("x", "1"));
    assert.doesNotThrow(() => removeStorage("x"));
  } finally {
    globalThis.window = originalWindow;
  }
});
