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
  width: 180px;
  height: 180px;
  border-radius: 50%;
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

.image-magnifier-crosshair {
  position: absolute;
  inset: 0;
}

.image-magnifier-crosshair::before,
.image-magnifier-crosshair::after {
  content: "";
  position: absolute;
  background: rgba(33, 39, 43, 0.35);
}

.image-magnifier-crosshair::before {
  left: 50%;
  top: 0;
  width: 1px;
  height: 100%;
  transform: translateX(-50%);
}

.image-magnifier-crosshair::after {
  top: 50%;
  left: 0;
  height: 1px;
  width: 100%;
  transform: translateY(-50%);
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
  offsetX = 20,
  offsetY = 20,
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
  const left = Math.max(minLeft, Math.min(maxLeft, x + Number(offsetX)));
  const top = Math.max(minTop, Math.min(maxTop, y + Number(offsetY)));
  return { left, top };
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
  lensSize = 180,
  defaultZoom = 4,
  minZoom = 2,
  maxZoom = 8,
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

  const crosshair = document.createElement("div");
  crosshair.className = "image-magnifier-crosshair";
  lens.appendChild(crosshair);
  document.body.appendChild(lens);

  const ctx = canvas.getContext("2d");
  let enabled = false;
  let temporary = false;
  let pointerInside = false;
  let lastPointer = null;
  let zoom = clampMagnifierZoom(defaultZoom, { min: minZoom, max: maxZoom, fallback: 4 });

  const isActive = () => enabled || temporary;

  const hideLens = () => {
    lens.hidden = true;
  };

  const renderAtPointer = (pointer) => {
    if (!ctx || !pointer || !isActive()) {
      hideLens();
      return;
    }
    const naturalWidth = image.naturalWidth;
    const naturalHeight = image.naturalHeight;
    if (!naturalWidth || !naturalHeight) {
      hideLens();
      return;
    }
    const imageRect = image.getBoundingClientRect();
    if (!imageRect.width || !imageRect.height) {
      hideLens();
      return;
    }

    const localX = pointer.clientX - imageRect.left;
    const localY = pointer.clientY - imageRect.top;
    if (localX < 0 || localY < 0 || localX > imageRect.width || localY > imageRect.height) {
      hideLens();
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
      hideLens();
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

    const lensPos = computeMagnifierLensPosition({
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
    hideLens();
  };

  const onViewportScroll = () => {
    if (!pointerInside || !lastPointer) {
      hideLens();
      return;
    }
    renderAtPointer(lastPointer);
  };

  viewport.addEventListener("pointermove", onPointerMove);
  viewport.addEventListener("pointerleave", onPointerLeave);
  viewport.addEventListener("scroll", onViewportScroll, { passive: true });
  window.addEventListener("resize", onViewportScroll, { passive: true });

  const refresh = () => {
    if (!lastPointer) {
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
      if (!isActive()) {
        hideLens();
        return;
      }
      if (pointerInside && lastPointer) {
        renderAtPointer(lastPointer);
      }
    },
    setTemporary(value) {
      temporary = Boolean(value);
      if (!isActive()) {
        hideLens();
        return;
      }
      if (pointerInside && lastPointer) {
        renderAtPointer(lastPointer);
      }
    },
    getZoom() {
      return zoom;
    },
    setZoom(value) {
      zoom = clampMagnifierZoom(value, { min: minZoom, max: maxZoom, fallback: defaultZoom });
      if (pointerInside && lastPointer && isActive()) {
        renderAtPointer(lastPointer);
      }
    },
    refresh,
    destroy() {
      viewport.removeEventListener("pointermove", onPointerMove);
      viewport.removeEventListener("pointerleave", onPointerLeave);
      viewport.removeEventListener("scroll", onViewportScroll);
      window.removeEventListener("resize", onViewportScroll);
      lens.remove();
    },
  };
}
