import test from "node:test";
import assert from "node:assert/strict";

import {
  closeModal,
  openModal,
  shouldCloseOnBackdropPointerDown,
} from "../app/static/js/modal_controller.mjs";

test("openModal unhides modal and invokes hook", () => {
  let opened = false;
  const modal = { hidden: true };
  openModal(modal, {
    onOpen() {
      opened = true;
    },
  });
  assert.equal(modal.hidden, false);
  assert.equal(opened, true);
});

test("closeModal respects busy guard unless forced", () => {
  const modal = { hidden: false };
  const closedBusy = closeModal(modal, {
    isBusy: () => true,
  });
  assert.equal(closedBusy, false);
  assert.equal(modal.hidden, false);

  const closedForced = closeModal(modal, {
    force: true,
    isBusy: () => true,
  });
  assert.equal(closedForced, true);
  assert.equal(modal.hidden, true);
});

test("closeModal invokes onClose hook", () => {
  let closed = false;
  const modal = { hidden: false };
  closeModal(modal, {
    onClose() {
      closed = true;
    },
  });
  assert.equal(closed, true);
  assert.equal(modal.hidden, true);
});

test("shouldCloseOnBackdropPointerDown only matches backdrop target", () => {
  const modal = {};
  assert.equal(shouldCloseOnBackdropPointerDown({ target: modal }, modal), true);
  assert.equal(shouldCloseOnBackdropPointerDown({ target: {} }, modal), false);
});
