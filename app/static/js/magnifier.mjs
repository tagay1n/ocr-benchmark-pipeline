const MAGNIFIER_STYLE_ID = "shared-image-magnifier-style";

function ensureMagnifierStyles() {
  if (typeof document === "undefined") {
    return;
  }
  if (document.getElementById(MAGNIFIER_STYLE_ID)) {
    return;
  }
  const style = document.createElement("style");
  style.id = MAGNIFIER_STYLE_ID;
  style.textContent = `
.image-magnifier-lens {
  position: fixed;
  width: 270px;
  height: 270px;
  border-radius: 6px;
  border: 1px solid rgba(53, 64, 67, 0.45);
  box-shadow:
    0 14px 34px rgba(17, 24, 28, 0.28),
    inset 0 0 0 1px rgba(255, 255, 255, 0.35);
  overflow: hidden;
  pointer-events: none;
  z-index: 9999;
  backdrop-filter: blur(0.5px);
  background: #f4f1e8;
}

.image-magnifier-lens[hidden] {
  display: none;
}

.image-magnifier-canvas {
  width: 100%;
  height: 100%;
  display: block;
}

.image-magnifier-zoom-controls {
  position: absolute;
  top: 6px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 4px;
  border-radius: 8px;
  border: 1px solid rgba(188, 181, 164, 0.78);
  background: rgba(252, 250, 245, 0.92);
  box-shadow: 0 2px 8px rgba(23, 29, 32, 0.18);
  pointer-events: auto;
}

.image-magnifier-zoom-btn {
  width: 22px;
  height: 22px;
  min-width: 22px;
  padding: 0;
  border: 1px solid rgba(190, 184, 169, 0.92);
  border-radius: 6px;
  background: #f0ece1;
  color: #232521;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}

.image-magnifier-zoom-btn:hover:not(:disabled) {
  background: #e6e0d1;
}

.image-magnifier-zoom-btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.image-magnifier-zoom-value {
  min-width: 40px;
  text-align: center;
  font-size: 12px;
  line-height: 1;
  color: #4a4a44;
  font-variant-numeric: tabular-nums;
}

.image-magnifier-crosshair {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  background: #c83a3a;
  border: 1px solid rgba(255, 255, 255, 0.85);
  box-shadow: 0 0 0 1px rgba(150, 24, 24, 0.34);
}

.image-magnifier-hide-cursor,
.image-magnifier-hide-cursor * {
  cursor: none !important;
}
`.trim();
  document.head.appendChild(style);
}

export function clampMagnifierZoom(value, { min = 2, max = 8, fallback = 4 } = {}) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, numeric));
}

export function computeMagnifierSampleRect({
  naturalWidth,
  naturalHeight,
  displayWidth,
  displayHeight,
  pointerNaturalX,
  pointerNaturalY,
  lensSize,
  zoom,
}) {
  const nWidth = Number(naturalWidth);
  const nHeight = Number(naturalHeight);
  const dWidth = Number(displayWidth);
  const dHeight = Number(displayHeight);
  const pointerX = Number(pointerNaturalX);
  const pointerY = Number(pointerNaturalY);
  const targetLensSize = Number(lensSize);
  const targetZoom = Number(zoom);
  if (
    !Number.isFinite(nWidth) ||
    !Number.isFinite(nHeight) ||
    !Number.isFinite(dWidth) ||
    !Number.isFinite(dHeight) ||
    !Number.isFinite(pointerX) ||
    !Number.isFinite(pointerY) ||
    !Number.isFinite(targetLensSize) ||
    !Number.isFinite(targetZoom)
  ) {
    return null;
  }
  if (nWidth <= 0 || nHeight <= 0 || dWidth <= 0 || dHeight <= 0 || targetLensSize <= 0 || targetZoom <= 0) {
    return null;
  }

  const sampleWidth = Math.min(nWidth, (targetLensSize / targetZoom) * (nWidth / dWidth));
  const sampleHeight = Math.min(nHeight, (targetLensSize / targetZoom) * (nHeight / dHeight));
  const maxLeft = Math.max(0, nWidth - sampleWidth);
  const maxTop = Math.max(0, nHeight - sampleHeight);

  const left = Math.max(0, Math.min(maxLeft, pointerX - sampleWidth / 2));
  const top = Math.max(0, Math.min(maxTop, pointerY - sampleHeight / 2));
  return {
    left,
    top,
    width: sampleWidth,
    height: sampleHeight,
  };
}

export function computeMagnifierLensPosition({
  clientX,
  clientY,
  lensSize,
  viewportWidth,
  viewportHeight,
  offsetX = 0,
  offsetY = 0,
  padding = 8,
}) {
  const x = Number(clientX);
  const y = Number(clientY);
  const size = Number(lensSize);
  const width = Number(viewportWidth);
  const height = Number(viewportHeight);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(size) || !Number.isFinite(width) || !Number.isFinite(height)) {
    return null;
  }
  if (size <= 0 || width <= 0 || height <= 0) {
    return null;
  }

  const minLeft = Number(padding);
  const minTop = Number(padding);
  const maxLeft = Math.max(minLeft, width - size - Number(padding));
  const maxTop = Math.max(minTop, height - size - Number(padding));
  const left = Math.max(minLeft, Math.min(maxLeft, x - size / 2 + Number(offsetX)));
  const top = Math.max(minTop, Math.min(maxTop, y - size / 2 + Number(offsetY)));
  return { left, top };
}

export function computeDockedMagnifierPosition({
  lensSize,
  viewportRect,
  viewportGap = 10,
  edgeInset = 8,
  windowWidth,
  windowHeight,
  dockInsideViewport = false,
  dockCorner = "bottom-left",
}) {
  const size = Number(lensSize);
  const gap = Number(viewportGap);
  const inset = Number(edgeInset);
  const w = Number(windowWidth);
  const h = Number(windowHeight);
  if (!Number.isFinite(size) || !Number.isFinite(gap) || !Number.isFinite(inset) || !Number.isFinite(w) || !Number.isFinite(h)) {
    return null;
  }
  if (size <= 0 || w <= 0 || h <= 0) {
    return null;
  }
  const leftLimit = inset;
  const topLimit = inset;
  const rightLimit = Math.max(leftLimit, w - size - inset);
  const bottomLimit = Math.max(topLimit, h - size - inset);
  const fallback = { left: rightLimit, top: bottomLimit };
  const rect = viewportRect;
  if (!rect) {
    return fallback;
  }
  const viewportLeft = Number(rect.left);
  const viewportTop = Number(rect.top);
  const viewportRight = Number(rect.right);
  const viewportBottom = Number(rect.bottom);
  if (![viewportLeft, viewportTop, viewportRight, viewportBottom].every(Number.isFinite)) {
    return fallback;
  }

  const corner = String(dockCorner || "bottom-left").toLowerCase();
  const preferTop = corner.startsWith("top");
  const preferRight = corner.endsWith("right");

  if (dockInsideViewport) {
    const safeTop = preferTop
      ? Math.max(topLimit, Math.min(bottomLimit, viewportTop + gap))
      : Math.max(topLimit, Math.min(bottomLimit, viewportBottom - size - gap));
    const safeLeft = preferRight
      ? Math.max(leftLimit, Math.min(rightLimit, viewportRight - size - gap))
      : Math.max(leftLimit, Math.min(rightLimit, viewportLeft + gap));
    return { left: safeLeft, top: safeTop };
  }

  const alignedTop = preferTop
    ? Math.max(topLimit, Math.min(bottomLimit, viewportTop + gap))
    : Math.max(topLimit, Math.min(bottomLimit, viewportBottom - size - gap));
  const leftOutsideLeft = viewportLeft - size - gap;
  const rightOutsideLeft = viewportRight + gap;
  if (preferRight) {
    if (rightOutsideLeft <= rightLimit) {
      return { left: rightOutsideLeft, top: alignedTop };
    }
    if (leftOutsideLeft >= leftLimit) {
      return { left: leftOutsideLeft, top: alignedTop };
    }
  } else {
    if (leftOutsideLeft >= leftLimit) {
      return { left: leftOutsideLeft, top: alignedTop };
    }
    if (rightOutsideLeft <= rightLimit) {
      return { left: rightOutsideLeft, top: alignedTop };
    }
  }

  const alignedLeft = Math.max(leftLimit, Math.min(rightLimit, viewportRight - size - gap));
  const aboveOutsideTop = viewportTop - size - gap;
  const belowOutsideTop = viewportBottom + gap;
  if (preferTop) {
    if (aboveOutsideTop >= topLimit) {
      return { left: alignedLeft, top: aboveOutsideTop };
    }
    if (belowOutsideTop <= bottomLimit) {
      return { left: alignedLeft, top: belowOutsideTop };
    }
  } else {
    if (belowOutsideTop <= bottomLimit) {
      return { left: alignedLeft, top: belowOutsideTop };
    }
    if (aboveOutsideTop >= topLimit) {
      return { left: alignedLeft, top: aboveOutsideTop };
    }
  }

  return {
    left: preferRight ? rightLimit : leftLimit,
    top: preferTop ? topLimit : bottomLimit,
  };
}

function drawOverlayItems(ctx, overlayItems, sampleRect, naturalWidth, naturalHeight, lensSize) {
  if (!Array.isArray(overlayItems) || overlayItems.length === 0) {
    return;
  }
  for (const item of overlayItems) {
    const bbox = item?.bbox;
    if (!bbox) {
      continue;
    }
    const rawX1 = Number(bbox.x1) * naturalWidth;
    const rawY1 = Number(bbox.y1) * naturalHeight;
    const rawX2 = Number(bbox.x2) * naturalWidth;
    const rawY2 = Number(bbox.y2) * naturalHeight;
    if (![rawX1, rawY1, rawX2, rawY2].every(Number.isFinite)) {
      continue;
    }
    const left = Math.min(rawX1, rawX2);
    const top = Math.min(rawY1, rawY2);
    const width = Math.abs(rawX2 - rawX1);
    const height = Math.abs(rawY2 - rawY1);
    if (width <= 0 || height <= 0) {
      continue;
    }

    const x = ((left - sampleRect.left) / sampleRect.width) * lensSize;
    const y = ((top - sampleRect.top) / sampleRect.height) * lensSize;
    const w = (width / sampleRect.width) * lensSize;
    const h = (height / sampleRect.height) * lensSize;
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(w) || !Number.isFinite(h)) {
      continue;
    }

    const stroke = String(item.stroke || "#2f556e");
    const fill = item.fill ? String(item.fill) : "";
    const lineWidth = Number.isFinite(Number(item.lineWidth)) ? Number(item.lineWidth) : 1.4;
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fillRect(x, y, w, h);
    }
    ctx.strokeStyle = stroke;
    ctx.lineWidth = lineWidth;
    if (Array.isArray(item.dash) && item.dash.length > 0) {
      ctx.setLineDash(item.dash);
    } else {
      ctx.setLineDash([]);
    }
    ctx.strokeRect(x, y, w, h);
  }
  ctx.setLineDash([]);
}

export function createImageMagnifier({
  viewport,
  image,
  getOverlayItems = () => [],
  lensSize = 270,
  defaultZoom = 4,
  minZoom = 2,
  maxZoom = 8,
  mode = "docked",
  dockGap = 10,
  edgeInset = 8,
  hideCursorWhenActive = false,
  showZoomControls = false,
  zoomStep = 0.5,
  onZoomChange = null,
  dockInsideViewport = false,
  dockCorner = "bottom-left",
  getDockCorner = null,
  hideDuringViewportScroll = false,
  scrollShowDelayMs = 180,
}) {
  if (!(viewport instanceof HTMLElement) || !(image instanceof HTMLImageElement)) {
    throw new Error("Magnifier requires viewport HTMLElement and image HTMLImageElement.");
  }
  ensureMagnifierStyles();

  const size = Math.max(80, Math.round(Number(lensSize) || 180));
  const lens = document.createElement("div");
  lens.className = "image-magnifier-lens";
  lens.hidden = true;
  lens.style.width = `${size}px`;
  lens.style.height = `${size}px`;

  const canvas = document.createElement("canvas");
  canvas.className = "image-magnifier-canvas";
  canvas.width = size;
  canvas.height = size;
  lens.appendChild(canvas);

  let zoomControls = null;
  let zoomOutBtn = null;
  let zoomInBtn = null;
  let zoomValueEl = null;

  if (showZoomControls) {
    zoomControls = document.createElement("div");
    zoomControls.className = "image-magnifier-zoom-controls";
    zoomControls.setAttribute("role", "group");
    zoomControls.setAttribute("aria-label", "Magnifier zoom");

    zoomOutBtn = document.createElement("button");
    zoomOutBtn.type = "button";
    zoomOutBtn.className = "image-magnifier-zoom-btn";
    zoomOutBtn.textContent = "−";
    zoomOutBtn.setAttribute("aria-label", "Decrease magnifier zoom");
    zoomOutBtn.title = "Decrease magnifier zoom";

    zoomValueEl = document.createElement("span");
    zoomValueEl.className = "image-magnifier-zoom-value";

    zoomInBtn = document.createElement("button");
    zoomInBtn.type = "button";
    zoomInBtn.className = "image-magnifier-zoom-btn";
    zoomInBtn.textContent = "+";
    zoomInBtn.setAttribute("aria-label", "Increase magnifier zoom");
    zoomInBtn.title = "Increase magnifier zoom";

    zoomControls.appendChild(zoomOutBtn);
    zoomControls.appendChild(zoomValueEl);
    zoomControls.appendChild(zoomInBtn);
    lens.appendChild(zoomControls);
  }

  const crosshair = document.createElement("div");
  crosshair.className = "image-magnifier-crosshair";
  lens.appendChild(crosshair);
  document.body.appendChild(lens);

  const ctx = canvas.getContext("2d");
  let enabled = false;
  let temporary = false;
  let pointerInside = false;
  let lastPointer = null;
  let scrollResumeTimer = null;
  let hiddenByScroll = false;
  let zoom = clampMagnifierZoom(defaultZoom, { min: minZoom, max: maxZoom, fallback: 4 });
  const isDockedMode = String(mode || "").toLowerCase() !== "cursor";

  const isActive = () => enabled || temporary;

  const resolveDockCorner = () => {
    const dynamicCorner = typeof getDockCorner === "function" ? String(getDockCorner() || "") : "";
    const normalized = (dynamicCorner || String(dockCorner || "bottom-left")).toLowerCase();
    if (normalized === "top-left" || normalized === "top-right" || normalized === "bottom-right") {
      return normalized;
    }
    return "bottom-left";
  };

  const hideLens = () => {
    lens.hidden = true;
  };

  const clearScrollResumeTimer = () => {
    if (scrollResumeTimer !== null) {
      window.clearTimeout(scrollResumeTimer);
      scrollResumeTimer = null;
    }
  };

  const updateDockedLensPosition = () => {
    const activeDockCorner = resolveDockCorner();
    const position = computeDockedMagnifierPosition({
      lensSize: size,
      viewportRect: viewport.getBoundingClientRect(),
      viewportGap: dockGap,
      edgeInset,
      windowWidth: window.innerWidth,
      windowHeight: window.innerHeight,
      dockInsideViewport,
      dockCorner: activeDockCorner,
    });
    if (!position) {
      return false;
    }
    lens.style.left = `${position.left}px`;
    lens.style.top = `${position.top}px`;
    return true;
  };

  const showIdleLens = () => {
    if (!isActive()) {
      hideLens();
      return;
    }
    if (isDockedMode) {
      if (!updateDockedLensPosition()) {
        hideLens();
        return;
      }
    } else if (!lastPointer) {
      hideLens();
      return;
    }
    lens.hidden = false;
  };

  const syncCursorVisibility = () => {
    if (hideCursorWhenActive) {
      viewport.classList.toggle("image-magnifier-hide-cursor", isActive());
      return;
    }
    viewport.classList.remove("image-magnifier-hide-cursor");
  };

  const syncZoomControls = () => {
    if (!(zoomValueEl instanceof HTMLElement)) {
      return;
    }
    zoomValueEl.textContent = `${zoom.toFixed(1)}x`;
    if (zoomOutBtn instanceof HTMLButtonElement) {
      zoomOutBtn.disabled = zoom <= minZoom + 1e-6;
    }
    if (zoomInBtn instanceof HTMLButtonElement) {
      zoomInBtn.disabled = zoom >= maxZoom - 1e-6;
    }
  };

  const setZoomInternal = (value, { emit = true } = {}) => {
    const nextZoom = clampMagnifierZoom(value, { min: minZoom, max: maxZoom, fallback: defaultZoom });
    const changed = Math.abs(nextZoom - zoom) > 1e-6;
    zoom = nextZoom;
    syncZoomControls();
    if (changed && emit && typeof onZoomChange === "function") {
      onZoomChange(zoom);
    }
    if (pointerInside && lastPointer && isActive()) {
      renderAtPointer(lastPointer);
    } else if (isActive()) {
      showIdleLens();
    }
  };

  const renderAtPointer = (pointer) => {
    if (!ctx || !pointer || !isActive() || hiddenByScroll) {
      hideLens();
      return;
    }
    const naturalWidth = image.naturalWidth;
    const naturalHeight = image.naturalHeight;
    if (!naturalWidth || !naturalHeight) {
      showIdleLens();
      return;
    }
    const imageRect = image.getBoundingClientRect();
    if (!imageRect.width || !imageRect.height) {
      showIdleLens();
      return;
    }

    const localX = pointer.clientX - imageRect.left;
    const localY = pointer.clientY - imageRect.top;
    if (localX < 0 || localY < 0 || localX > imageRect.width || localY > imageRect.height) {
      showIdleLens();
      return;
    }

    const pointerNaturalX = (localX / imageRect.width) * naturalWidth;
    const pointerNaturalY = (localY / imageRect.height) * naturalHeight;
    const sampleRect = computeMagnifierSampleRect({
      naturalWidth,
      naturalHeight,
      displayWidth: imageRect.width,
      displayHeight: imageRect.height,
      pointerNaturalX,
      pointerNaturalY,
      lensSize: size,
      zoom,
    });
    if (!sampleRect) {
      showIdleLens();
      return;
    }

    ctx.clearRect(0, 0, size, size);
    ctx.drawImage(
      image,
      sampleRect.left,
      sampleRect.top,
      sampleRect.width,
      sampleRect.height,
      0,
      0,
      size,
      size,
    );
    drawOverlayItems(ctx, getOverlayItems(), sampleRect, naturalWidth, naturalHeight, size);

    const lensPos = isDockedMode
      ? computeDockedMagnifierPosition({
          lensSize: size,
          viewportRect: viewport.getBoundingClientRect(),
          viewportGap: dockGap,
          edgeInset,
          windowWidth: window.innerWidth,
          windowHeight: window.innerHeight,
          dockInsideViewport,
          dockCorner: resolveDockCorner(),
        })
      : computeMagnifierLensPosition({
          clientX: pointer.clientX,
          clientY: pointer.clientY,
          lensSize: size,
          viewportWidth: window.innerWidth,
          viewportHeight: window.innerHeight,
        });
    if (!lensPos) {
      hideLens();
      return;
    }

    lens.style.left = `${lensPos.left}px`;
    lens.style.top = `${lensPos.top}px`;
    lens.hidden = false;
  };

  const onPointerMove = (event) => {
    pointerInside = true;
    lastPointer = {
      clientX: event.clientX,
      clientY: event.clientY,
    };
    renderAtPointer(lastPointer);
  };

  const onPointerLeave = () => {
    pointerInside = false;
    if (!isActive()) {
      hideLens();
      return;
    }
    showIdleLens();
  };

  const onViewportScroll = () => {
    if (!isActive()) {
      hideLens();
      return;
    }
    if (hideDuringViewportScroll) {
      hiddenByScroll = true;
      hideLens();
      clearScrollResumeTimer();
      scrollResumeTimer = window.setTimeout(() => {
        scrollResumeTimer = null;
        hiddenByScroll = false;
        if (!isActive()) {
          hideLens();
          return;
        }
        if (pointerInside && lastPointer) {
          renderAtPointer(lastPointer);
          return;
        }
        showIdleLens();
      }, Math.max(0, Number(scrollShowDelayMs) || 0));
      return;
    }
    if (!pointerInside || !lastPointer) {
      showIdleLens();
      return;
    }
    renderAtPointer(lastPointer);
  };

  viewport.addEventListener("pointermove", onPointerMove);
  viewport.addEventListener("pointerleave", onPointerLeave);
  viewport.addEventListener("scroll", onViewportScroll, { passive: true });
  window.addEventListener("resize", onViewportScroll, { passive: true });

  if (zoomOutBtn instanceof HTMLButtonElement) {
    zoomOutBtn.addEventListener("click", () => {
      setZoomInternal(zoom - Number(zoomStep || 0.5), { emit: true });
    });
  }
  if (zoomInBtn instanceof HTMLButtonElement) {
    zoomInBtn.addEventListener("click", () => {
      setZoomInternal(zoom + Number(zoomStep || 0.5), { emit: true });
    });
  }
  syncZoomControls();

  const refresh = () => {
    if (!isActive()) {
      hideLens();
      return;
    }
    if (!lastPointer) {
      showIdleLens();
      return;
    }
    renderAtPointer(lastPointer);
  };

  return {
    isEnabled() {
      return enabled;
    },
    setEnabled(value) {
      enabled = Boolean(value);
      if (!enabled) {
        hiddenByScroll = false;
        clearScrollResumeTimer();
      }
      syncCursorVisibility();
      if (!isActive()) {
        hideLens();
        return;
      }
      if (pointerInside && lastPointer) {
        renderAtPointer(lastPointer);
      } else {
        showIdleLens();
      }
    },
    setTemporary(value) {
      temporary = Boolean(value);
      if (!temporary) {
        hiddenByScroll = false;
        clearScrollResumeTimer();
      }
      syncCursorVisibility();
      if (!isActive()) {
        hideLens();
        return;
      }
      if (pointerInside && lastPointer) {
        renderAtPointer(lastPointer);
      } else {
        showIdleLens();
      }
    },
    getZoom() {
      return zoom;
    },
    setZoom(value) {
      setZoomInternal(value, { emit: false });
    },
    refresh,
    destroy() {
      clearScrollResumeTimer();
      viewport.removeEventListener("pointermove", onPointerMove);
      viewport.removeEventListener("pointerleave", onPointerLeave);
      viewport.removeEventListener("scroll", onViewportScroll);
      window.removeEventListener("resize", onViewportScroll);
      viewport.classList.remove("image-magnifier-hide-cursor");
      lens.remove();
    },
  };
}
