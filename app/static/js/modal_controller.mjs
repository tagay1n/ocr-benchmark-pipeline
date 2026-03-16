export function openModal(modalElement, { onOpen } = {}) {
  if (modalElement && "hidden" in modalElement) {
    modalElement.hidden = false;
  }
  if (typeof onOpen === "function") {
    onOpen();
  }
}

export function closeModal(
  modalElement,
  {
    force = false,
    isBusy = null,
    onClose,
  } = {},
) {
  const busy = typeof isBusy === "function" ? Boolean(isBusy()) : false;
  if (!force && busy) {
    return false;
  }
  if (modalElement && "hidden" in modalElement) {
    modalElement.hidden = true;
  }
  if (typeof onClose === "function") {
    onClose();
  }
  return true;
}

export function shouldCloseOnBackdropPointerDown(event, modalElement) {
  return Boolean(event && modalElement && event.target === modalElement);
}
