export function rebuildZoomPresetOptions(zoomMenu, presetPercents = []) {
  if (!zoomMenu || typeof zoomMenu.querySelector !== "function") {
    return [];
  }
  const separator = zoomMenu.querySelector(".zoom-separator");
  if (!separator || typeof separator.after !== "function") {
    return Array.from(zoomMenu.querySelectorAll(".zoom-option"));
  }

  for (const option of zoomMenu.querySelectorAll(".zoom-option[data-zoom-percent]")) {
    option.remove();
  }

  if (typeof document === "undefined" || typeof document.createDocumentFragment !== "function") {
    return Array.from(zoomMenu.querySelectorAll(".zoom-option"));
  }
  const fragment = document.createDocumentFragment();
  for (const rawPercent of presetPercents) {
    const percent = Number(rawPercent);
    if (!Number.isFinite(percent) || percent <= 0) {
      continue;
    }
    const option = document.createElement("button");
    option.type = "button";
    option.className = "zoom-option";
    option.dataset.zoomPercent = String(Math.round(percent));
    option.textContent = `${Math.round(percent)}%`;
    fragment.appendChild(option);
  }
  separator.after(fragment);
  return Array.from(zoomMenu.querySelectorAll(".zoom-option"));
}

export function closeZoomMenu(zoomMenu, zoomTrigger) {
  if (zoomMenu && "hidden" in zoomMenu) {
    zoomMenu.hidden = true;
  }
  if (zoomTrigger && typeof zoomTrigger.setAttribute === "function") {
    zoomTrigger.setAttribute("aria-expanded", "false");
  }
}

export function openZoomMenu(zoomMenu, zoomTrigger) {
  if (zoomMenu && "hidden" in zoomMenu) {
    zoomMenu.hidden = false;
  }
  if (zoomTrigger && typeof zoomTrigger.setAttribute === "function") {
    zoomTrigger.setAttribute("aria-expanded", "true");
  }
}

export function updateZoomMenuSelection(zoomOptions, { zoomMode, zoomPercent } = {}) {
  const mode = String(zoomMode || "");
  const percent = Number(zoomPercent);
  for (const option of Array.isArray(zoomOptions) ? zoomOptions : []) {
    const optionMode = String(option?.dataset?.zoomMode || "");
    const optionPercent = Number(option?.dataset?.zoomPercent);
    const modeMatch = optionMode !== "" && optionMode === mode;
    const percentMatch =
      Number.isFinite(optionPercent) &&
      mode === "custom" &&
      Number.isFinite(percent) &&
      optionPercent === Math.round(percent);
    if (option && option.classList && typeof option.classList.toggle === "function") {
      option.classList.toggle("active", modeMatch || percentMatch);
    }
  }
}

export function setZoomInputFromApplied(zoomPercentInput, zoomAppliedPercent) {
  if (!zoomPercentInput || typeof zoomPercentInput !== "object") {
    return;
  }
  const percent = Number(zoomAppliedPercent);
  const rounded = Number.isFinite(percent) ? Math.round(percent) : 100;
  zoomPercentInput.value = String(rounded);
}

export function loadStoredZoomSettings({
  readStorage,
  zoomModeKey,
  zoomPercentKey,
  normalizeZoomMode,
  clampZoomPercent,
  fallbackMode = "automatic",
} = {}) {
  const normalizeModeFn = typeof normalizeZoomMode === "function" ? normalizeZoomMode : (value) => value;
  const clampPercentFn = typeof clampZoomPercent === "function" ? clampZoomPercent : (value) => value;
  const readStorageFn = typeof readStorage === "function" ? readStorage : () => null;

  const zoomMode = normalizeModeFn(readStorageFn(zoomModeKey), {
    fallback: fallbackMode,
    allowCustom: true,
  });
  let zoomPercent = 100;
  const storedPercent = readStorageFn(zoomPercentKey);
  if (storedPercent !== null) {
    zoomPercent = clampPercentFn(storedPercent);
  }

  return {
    zoomMode,
    zoomPercent,
    zoomAppliedPercent: 100,
  };
}
