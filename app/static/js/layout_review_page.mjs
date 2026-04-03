      import {
        clampZoomPercent,
        compactReadingOrdersAfterDeletion,
        detectOverlappingBorderSegments,
        computeDraggedBBox,
        computeViewportScrollTargetForLayoutId,
        computeZoomScale,
        computeOverlayBadgeScale,
        filterReviewHistory,
        hasContiguousUniqueReadingOrders,
        isLayoutNotFoundErrorMessage,
        mergeLayoutsForReview,
        nextManualReadingOrder,
        nextHistoryPageId,
        normalizeReviewHistory,
        nextLayoutReviewUrl,
        normalizeLayoutOrderMode,
        normalizeZoomMode,
        pointHandleForCoordinateKey,
        previousHistoryPageId,
        reorderReadingOrderIds,
        summarizeDraftChangesForReorder,
        swapReadingOrderIds,
        shiftDraftReadingOrdersAfterInsertion,
        ZOOM_PRESET_PERCENTS,
        updateReviewHistoryOnVisit,
      } from "/static/js/layout_review_utils.mjs";
      import {
        clampMagnifierZoom,
        createImageMagnifier,
      } from "/static/js/magnifier.mjs";
      import {
        KNOWN_LAYOUT_CLASSES,
        colorForClass,
        formatClassLabel,
        normalizeClassName,
        isCaptionClassName,
        isCaptionTargetClassName,
      } from "/static/js/layout_class_catalog.mjs";
      import {
        completeLayoutReview,
        createPageLayout,
        deleteLayout,
        detectPageLayouts,
        fetchLayoutBenchmarkGrid,
        fetchLayoutDetectionDefaults,
        fetchNextLayoutReviewPage,
        fetchPageDetails,
        fetchPageLayouts,
        fetchPages,
        patchLayout,
        putCaptionBindings,
        reorderPageLayouts,
        updateLayoutOrderMode,
      } from "/static/js/layout_review_api.mjs";
      import {
        readStorage,
        readStorageBool,
        removeStorage,
        writeStorage,
      } from "/static/js/state_event_utils.mjs";
      import {
        loadStoredZoomSettings,
        rebuildZoomPresetOptions as rebuildZoomPresetOptionsShared,
        closeZoomMenu as closeZoomMenuShared,
        openZoomMenu as openZoomMenuShared,
        setZoomInputFromApplied as setZoomInputFromAppliedShared,
        updateZoomMenuSelection as updateZoomMenuSelectionShared,
      } from "/static/js/zoom_controller.mjs";
      import {
        formatStatusLabel,
        isInteractiveShortcutTarget,
        resolveViewportBottomLeftDockCorner,
        setToggleButtonActiveState,
        updateHistoryNavigationButtons,
        updateReviewStateBadge,
      } from "/static/js/review_shell_utils.mjs";
      import {
        historyNavigationTargets,
        loadReviewHistoryState,
        persistReviewHistoryState,
        registerCurrentPageVisit,
        sanitizeReviewHistoryFromPages,
      } from "/static/js/review_history_controller.mjs";
      import {
        closeModal,
        openModal,
        shouldCloseOnBackdropPointerDown,
      } from "/static/js/modal_controller.mjs";
      import {
        ensureNormalizedBBoxVisible,
        isNormalizedBBoxVisible,
      } from "/static/js/viewport_visibility_utils.mjs";

      const params = new URLSearchParams(window.location.search);
      const pageId = Number(params.get("page_id"));
      const AGREED_DETECT_DEFAULT_CONF = 0.2;
      const AGREED_DETECT_DEFAULT_IOU = 0.45;
      const DETECT_MIN_IMGSZ = 32;
      const DETECT_MAX_IMGSZ = 4096;
      const DETECT_MIN_MAX_DET = 1;
      const DETECT_MAX_MAX_DET = 3000;
      const MAGNIFIER_ZOOM_MIN = 1.5;
      const MAGNIFIER_ZOOM_MAX = 6;
      const MAGNIFIER_ZOOM_STEP = 0.5;
      const MAGNIFIER_ZOOM_DEFAULT = 3;
      const MAGNIFIER_NEAR_BOTTOM_THRESHOLD = 36;
      const RESIZE_HANDLE_SPACING_PX = 180;
      const RESIZE_HANDLE_MIN_INTERMEDIATE = 1;
      const RESIZE_HANDLE_MAX_INTERMEDIATE = 12;
      const STORAGE_KEYS = {
        layoutDraftPrefix: "layout.draft.page",
        zoomMode: "layout.zoom.mode",
        zoomPercent: "layout.zoom.percent",
        magnifierEnabled: "layout.magnifier.enabled",
        magnifierZoom: "layout.magnifier.zoom",
        reviewNavHistory: "layout.review_nav.history",
        reviewNavIndex: "layout.review_nav.index",
        lastAddedClass: "layout.last_added_class",
      };
      const LAYOUT_ORIENTATION_VALUES = ["horizontal", "vertical"];
      const LAYOUT_ORIENTATION_GLYPH_BY_VALUE = {
        horizontal: "↔",
        vertical: "↕",
      };

      const pageMeta = document.getElementById("page-meta");
      const imageViewport = document.getElementById("image-viewport");
      const imageWrap = document.getElementById("image-wrap");
      const pageImage = document.getElementById("page-image");
      const overlay = document.getElementById("overlay");
      const drawLayer = document.getElementById("draw-layer");
      const drawPreviewBox = document.getElementById("draw-preview-box");
      const statusLine = document.getElementById("status-line");
      const layoutsBody = document.getElementById("layouts-body");
      const reviewStateBadge = document.getElementById("review-state-badge");
      const zoomTrigger = document.getElementById("zoom-trigger");
      const zoomMenu = document.getElementById("zoom-menu");
      let zoomOptions = [];
      const zoomPercentInput = document.getElementById("zoom-percent-input");

      const detectBtn = document.getElementById("detect-btn");
      const addBtn = document.getElementById("add-btn");
      const reviewBtn = document.getElementById("review-btn");
      const layoutOrderModeInput = document.getElementById("layout-order-mode");
      const magnifierToggleBtn = document.getElementById("magnifier-toggle-btn");
      const historyBackBtn = document.getElementById("history-back-btn");
      const historyForthBtn = document.getElementById("history-forth-btn");
      const detectModal = document.getElementById("detect-modal");
      const detectModalCard = detectModal.querySelector(".modal-card");
      const detectModalRunBtn = document.getElementById("detect-modal-run-btn");
      const detectModalCancelBtn = document.getElementById("detect-modal-cancel-btn");
      const detectModalTopConfigInput = document.getElementById("detect-modal-top-config");
      const detectModalModelInput = document.getElementById("detect-modal-model");
      const detectModalConfInput = document.getElementById("detect-modal-conf");
      const detectModalIouInput = document.getElementById("detect-modal-iou");
      const detectModalImgszInput = document.getElementById("detect-modal-imgsz");
      const detectModalMaxDetInput = document.getElementById("detect-modal-max-det");
      const detectModalReplaceExistingInput = document.getElementById("detect-modal-replace-existing");
      const detectModalAgnosticNmsInput = document.getElementById("detect-modal-agnostic-nms");
      const detectModalHelpButtons = Array.from(detectModal.querySelectorAll(".field-help-btn"));
      const detectModalHelpCloud = document.getElementById("detect-modal-help-cloud");
      const DETECT_HELP_TEXT_BY_KEY = {
        model: "Selects which trained YOLO DocLayNet checkpoint is used for detection.",
        conf: "Minimum prediction confidence to keep a box. Lower catches more but may add noise.",
        iou: "NMS overlap threshold. Lower removes overlaps more aggressively; higher keeps more nearby boxes.",
        imgsz: "Inference resize target. Larger values can improve detail but increase runtime and memory.",
        max_det: "Maximum number of detections returned for one page after NMS.",
        agnostic_nms: "If enabled, NMS suppresses overlaps across classes instead of per class.",
      };

      const state = {
        page: null,
        layouts: [],
        serverLayoutsById: {},
        serverCaptionBindingsByCaptionId: {},
        localEditsById: {},
        deletedLayoutIds: new Set(),
        captionBindingsByCaptionId: {},
        selectedLayoutId: null,
        activeBindingCaptionId: null,
        activePointHighlight: null,
        expandedBboxLayoutId: null,
        zoomMode: "automatic",
        zoomPercent: 100,
        zoomAppliedPercent: 100,
        reviewHistory: [],
        reviewHistoryIndex: -1,
        nextReviewPageId: null,
        drawModeActive: false,
        drawPointerId: null,
        drawStartPoint: null,
        drawPreviewBBox: null,
        draggingLayoutId: null,
        dragOverLayoutId: null,
        reviewSubmitInProgress: false,
        detectInProgress: false,
        layoutOrderModeUpdateInProgress: false,
        layoutReorderInProgress: false,
        detectDefaultsLoaded: false,
        detectTopConfigs: [],
        activeDetectHelpKey: null,
        layoutsLoaded: false,
        magnifierEnabled: readStorageBool(STORAGE_KEYS.magnifierEnabled, true),
        magnifierZoom: clampMagnifierZoom(readStorage(STORAGE_KEYS.magnifierZoom), {
          min: MAGNIFIER_ZOOM_MIN,
          max: MAGNIFIER_ZOOM_MAX,
          fallback: MAGNIFIER_ZOOM_DEFAULT,
        }),
        lastAddedClass: normalizeClassName(readStorage(STORAGE_KEYS.lastAddedClass)) || "text",
      };
      let cursorGuideHorizontal = null;
      let cursorGuideVertical = null;

      function updateMagnifierToggleUi() {
        setToggleButtonActiveState(magnifierToggleBtn, state.magnifierEnabled);
      }

      function resolveMagnifierDockCorner() {
        return resolveViewportBottomLeftDockCorner(imageViewport, MAGNIFIER_NEAR_BOTTOM_THRESHOLD);
      }

      const imageMagnifier = createImageMagnifier({
        viewport: imageViewport,
        image: pageImage,
        defaultZoom: state.magnifierZoom,
        minZoom: MAGNIFIER_ZOOM_MIN,
        maxZoom: MAGNIFIER_ZOOM_MAX,
        dockInsideViewport: true,
        dockCorner: "bottom-left",
        getDockCorner: resolveMagnifierDockCorner,
        showZoomControls: true,
        zoomStep: MAGNIFIER_ZOOM_STEP,
        onZoomChange: (zoom) => {
          state.magnifierZoom = Number(zoom);
          writeStorage(STORAGE_KEYS.magnifierZoom, zoom);
        },
        getOverlayItems: () => {
          const items = state.layouts.map((layout) => {
            const layoutId = Number(layout.id);
            const color = colorForClass(layout.class_name);
            const selected = layoutId === Number(state.selectedLayoutId);
            return {
              bbox: layout.bbox,
              stroke: color,
              fill: selected ? hexToRgba(color, 0.2) : "",
              lineWidth: selected ? 2 : 1.3,
            };
          });
          if (state.drawModeActive && state.drawPreviewBBox) {
            items.push({
              bbox: state.drawPreviewBBox,
              stroke: "#0b7a75",
              fill: "rgba(11, 122, 117, 0.12)",
              lineWidth: 1.8,
              dash: [5, 3],
            });
          }
          return items;
        },
      });

      function setMagnifierEnabled(enabled) {
        const normalized = Boolean(enabled);
        if (state.magnifierEnabled === normalized) {
          return;
        }
        state.magnifierEnabled = normalized;
        writeStorage(STORAGE_KEYS.magnifierEnabled, normalized ? "1" : "0");
        imageMagnifier.setEnabled(normalized);
        updateMagnifierToggleUi();
      }

      function toggleMagnifier() {
        setMagnifierEnabled(!state.magnifierEnabled);
      }

      function setMagnifierZoom(value, { persist = true } = {}) {
        const zoom = Number(
          clampMagnifierZoom(value, {
            min: MAGNIFIER_ZOOM_MIN,
            max: MAGNIFIER_ZOOM_MAX,
            fallback: MAGNIFIER_ZOOM_DEFAULT,
          }),
        );
        state.magnifierZoom = zoom;
        if (persist) {
          writeStorage(STORAGE_KEYS.magnifierZoom, zoom);
        }
        imageMagnifier.setZoom(zoom);
      }

      imageMagnifier.setEnabled(state.magnifierEnabled);
      setMagnifierZoom(state.magnifierZoom, { persist: false });
      updateMagnifierToggleUi();

      function rebuildZoomPresetOptions() {
        zoomOptions = rebuildZoomPresetOptionsShared(zoomMenu, ZOOM_PRESET_PERCENTS);
      }

      function applyStoredZoomSettings() {
        const zoomState = loadStoredZoomSettings({
          readStorage,
          zoomModeKey: STORAGE_KEYS.zoomMode,
          zoomPercentKey: STORAGE_KEYS.zoomPercent,
          normalizeZoomMode,
          clampZoomPercent,
          fallbackMode: "automatic",
        });
        state.zoomMode = zoomState.zoomMode;
        state.zoomPercent = zoomState.zoomPercent;
        state.zoomAppliedPercent = zoomState.zoomAppliedPercent;
        setZoomInputFromApplied();
        updateZoomMenuSelection();
      }

      function closeZoomMenu() {
        closeZoomMenuShared(zoomMenu, zoomTrigger);
      }

      function openZoomMenu() {
        openZoomMenuShared(zoomMenu, zoomTrigger);
      }

      function updateZoomMenuSelection() {
        updateZoomMenuSelectionShared(zoomOptions, {
          zoomMode: state.zoomMode,
          zoomPercent: state.zoomPercent,
        });
      }

      function setZoomInputFromApplied() {
        setZoomInputFromAppliedShared(zoomPercentInput, state.zoomAppliedPercent);
      }

      function centerImageInViewport({ alignTop = false } = {}) {
        const viewportWidth = imageViewport.clientWidth;
        const viewportHeight = imageViewport.clientHeight;
        const contentWidth = imageWrap.offsetWidth;
        const contentHeight = imageWrap.offsetHeight;
        if (!viewportWidth || !viewportHeight || !contentWidth || !contentHeight) {
          return;
        }
        imageViewport.scrollLeft = Math.max(0, Math.round((contentWidth - viewportWidth) / 2));
        imageViewport.scrollTop = alignTop ? 0 : Math.max(0, Math.round((contentHeight - viewportHeight) / 2));
      }

      function fitMeasurementForViewport(viewport) {
        const rect = viewport.getBoundingClientRect();
        const visibleWidth = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
        const visibleHeight = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
        const width = Math.max(
          1,
          Math.min(
            viewport.clientWidth || 1,
            Math.max(1, Math.floor(visibleWidth || viewport.clientWidth || 1)),
          ),
        );
        const height = Math.max(
          1,
          Math.min(
            viewport.clientHeight || 1,
            Math.max(1, Math.floor(visibleHeight || viewport.clientHeight || 1)),
          ),
        );
        return { width, height };
      }

      function applyZoom() {
        const naturalWidth = pageImage.naturalWidth;
        const naturalHeight = pageImage.naturalHeight;
        if (!naturalWidth || !naturalHeight) {
          return;
        }

        const fitViewport = fitMeasurementForViewport(imageViewport);
        const wrapStyle = window.getComputedStyle(imageWrap);
        const topGutter = Math.max(0, Number.parseFloat(wrapStyle.marginTop || "0") || 0);
        const scale = computeZoomScale({
          mode: state.zoomMode,
          zoomPercent: state.zoomPercent,
          naturalWidth,
          naturalHeight,
          viewportWidth: fitViewport.width,
          viewportHeight: fitViewport.height,
          extraVerticalSpace: topGutter,
        });
        if (!scale || !Number.isFinite(scale) || scale <= 0) {
          return;
        }

        const snap = state.zoomMode === "custom" ? Math.round : Math.floor;
        const displayWidth = Math.max(1, snap(naturalWidth * scale));
        const displayHeight = Math.max(1, snap(naturalHeight * scale));
        pageImage.style.width = `${displayWidth}px`;
        pageImage.style.height = `${displayHeight}px`;
        imageWrap.style.width = `${displayWidth}px`;
        imageWrap.style.height = `${displayHeight}px`;
        imageWrap.style.setProperty("--overlay-badge-scale", String(computeOverlayBadgeScale(scale)));

        state.zoomAppliedPercent = Math.round(scale * 1000) / 10;
        setZoomInputFromApplied();
        updateZoomMenuSelection();
        requestAnimationFrame(() => {
          renderOverlay();
          const alignTop = state.zoomMode === "fit-page" || state.zoomMode === "fit-height";
          centerImageInViewport({ alignTop });
        });
      }

      function persistZoomSettings() {
        writeStorage(STORAGE_KEYS.zoomMode, state.zoomMode);
        writeStorage(STORAGE_KEYS.zoomPercent, String(Math.round(clampZoomPercent(state.zoomPercent))));
      }

      function setZoomMode(mode) {
        if (!["fit-page", "fit-width", "fit-height", "automatic"].includes(mode)) {
          return;
        }
        state.zoomMode = mode;
        applyZoom();
        persistZoomSettings();
      }

      function setCustomZoomPercent(percent) {
        state.zoomMode = "custom";
        state.zoomPercent = clampZoomPercent(percent);
        applyZoom();
        persistZoomSettings();
      }

      function applyCustomZoomFromInput() {
        const raw = Number(zoomPercentInput.value);
        if (!Number.isFinite(raw)) {
          setZoomInputFromApplied();
          return;
        }
        setCustomZoomPercent(raw);
      }

      function persistReviewHistory() {
        persistReviewHistoryState({
          writeStorage,
          historyKey: STORAGE_KEYS.reviewNavHistory,
          historyIndexKey: STORAGE_KEYS.reviewNavIndex,
          history: state.reviewHistory,
          historyIndex: state.reviewHistoryIndex,
        });
      }

      function updateHistoryNavButtons() {
        const targets = historyNavigationTargets({
          history: state.reviewHistory,
          historyIndex: state.reviewHistoryIndex,
          nextReviewPageId: state.nextReviewPageId,
          previousHistoryPageId,
          nextHistoryPageId,
        });
        updateHistoryNavigationButtons({
          historyBackButton: historyBackBtn,
          historyForwardButton: historyForthBtn,
          backTarget: targets.backTarget,
          forwardHistoryTarget: targets.forwardHistoryTarget,
          queueTarget: targets.queueTarget,
          labels: {
            noBackTitle: "No previously reviewed page in this session history.",
            backTitle: "Previous reviewed page",
            forwardHistoryTitle: "Open next reviewed page in this session history.",
            forwardQueueTitle: "Open next page waiting for layout review.",
            noForwardTitle: "No next page waiting for layout review.",
          },
        });
      }

      function loadReviewHistory() {
        const normalized = loadReviewHistoryState({
          readStorage,
          historyKey: STORAGE_KEYS.reviewNavHistory,
          historyIndexKey: STORAGE_KEYS.reviewNavIndex,
          normalizeReviewHistory,
        });
        state.reviewHistory = normalized.history;
        state.reviewHistoryIndex = normalized.index;
      }

      async function sanitizeReviewHistoryAgainstServer() {
        try {
          const payload = await fetchPages();
          const filtered = sanitizeReviewHistoryFromPages({
            history: state.reviewHistory,
            historyIndex: state.reviewHistoryIndex,
            pages: payload?.pages,
            currentPageId: pageId,
            filterReviewHistory,
          });
          state.reviewHistory = filtered.history;
          state.reviewHistoryIndex = filtered.index;
          persistReviewHistory();
        } catch {
          // Keep local history when server list is temporarily unavailable.
        }
        updateHistoryNavButtons();
      }

      function registerCurrentPageInHistory() {
        const updated = registerCurrentPageVisit({
          history: state.reviewHistory,
          historyIndex: state.reviewHistoryIndex,
          currentPageId: pageId,
          updateReviewHistoryOnVisit,
        });
        state.reviewHistory = updated.history;
        state.reviewHistoryIndex = updated.index;
        persistReviewHistory();
        updateHistoryNavButtons();
      }

      function scrollImageViewportToLayout(layoutId) {
        if (!pageImage.naturalWidth || !pageImage.naturalHeight) {
          return false;
        }
        const normalizedLayoutId = Number(layoutId);
        const layout =
          state.layouts.find((candidate) => Number(candidate?.id) === normalizedLayoutId) || null;
        if (layout?.bbox) {
          if (isNormalizedBBoxVisible(layout.bbox, imageViewport, imageWrap, { paddingPx: 24 })) {
            return true;
          }
          if (ensureNormalizedBBoxVisible(layout.bbox, imageViewport, imageWrap, { paddingPx: 24 })) {
            return true;
          }
        }
        const target = computeViewportScrollTargetForLayoutId({
          layoutId,
          layouts: state.layouts,
          contentWidth: imageWrap.offsetWidth,
          contentHeight: imageWrap.offsetHeight,
          viewportWidth: imageViewport.clientWidth,
          viewportHeight: imageViewport.clientHeight,
        });
        if (!target) {
          return false;
        }
        imageViewport.scrollLeft = target.left;
        imageViewport.scrollTop = target.top;
        return true;
      }

      function ensureLayoutVisible(layoutId, retries = 8) {
        if (scrollImageViewportToLayout(layoutId)) {
          return;
        }
        if (retries <= 0) {
          return;
        }
        requestAnimationFrame(() => {
          ensureLayoutVisible(layoutId, retries - 1);
        });
      }

      function draftStorageKey() {
        return `${STORAGE_KEYS.layoutDraftPrefix}:${pageId}`;
      }

      function toDraftShape(layout) {
        return {
          class_name: normalizeClassName(layout.class_name) || "text",
          reading_order: layout.reading_order === null ? null : Number(layout.reading_order),
          orientation: normalizeLayoutOrientationValue(layout.orientation),
          bbox: {
            x1: roundTo4(layout.bbox.x1),
            y1: roundTo4(layout.bbox.y1),
            x2: roundTo4(layout.bbox.x2),
            y2: roundTo4(layout.bbox.y2),
          },
        };
      }

      function sameDraft(a, b) {
        return (
          a.class_name === b.class_name &&
          a.reading_order === b.reading_order &&
          normalizeLayoutOrientationValue(a.orientation) === normalizeLayoutOrientationValue(b.orientation) &&
          a.bbox.x1 === b.bbox.x1 &&
          a.bbox.y1 === b.bbox.y1 &&
          a.bbox.x2 === b.bbox.x2 &&
          a.bbox.y2 === b.bbox.y2
        );
      }

      function normalizeLayoutOrientationValue(value) {
        const normalized = String(value || "").trim().toLowerCase().replaceAll("_", "-");
        if (normalized === "horizontal" || normalized === "h") {
          return "horizontal";
        }
        if (normalized === "vertical" || normalized === "v") {
          return "vertical";
        }
        return "horizontal";
      }

      function parseStoredDraft(rawDraft) {
        if (!rawDraft || typeof rawDraft !== "object") {
          return null;
        }

        const className = normalizeClassName(rawDraft.class_name);
        if (!className) {
          return null;
        }

        const readingOrderRaw = rawDraft.reading_order;
        let readingOrder = null;
        if (readingOrderRaw !== null) {
          const parsed = Number(readingOrderRaw);
          if (!Number.isInteger(parsed) || parsed < 1) {
            return null;
          }
          readingOrder = parsed;
        }

        const bbox = rawDraft.bbox;
        if (!bbox || typeof bbox !== "object") {
          return null;
        }

        const x1 = roundTo4(bbox.x1);
        const y1 = roundTo4(bbox.y1);
        const x2 = roundTo4(bbox.x2);
        const y2 = roundTo4(bbox.y2);
        if ([x1, y1, x2, y2].some((value) => Number.isNaN(value) || value < 0 || value > 1)) {
          return null;
        }

        return {
          class_name: className,
          reading_order: readingOrder,
          orientation: normalizeLayoutOrientationValue(rawDraft.orientation),
          bbox: { x1, y1, x2, y2 },
        };
      }

      function loadLayoutDraftState() {
        state.localEditsById = {};
        state.deletedLayoutIds = new Set();
        state.captionBindingsByCaptionId = {};
        state.layoutsLoaded = false;

        const raw = readStorage(draftStorageKey());
        if (!raw) {
          return;
        }

        let parsed;
        try {
          parsed = JSON.parse(raw);
        } catch {
          return;
        }
        if (!parsed || typeof parsed !== "object") {
          return;
        }

        const edits = parsed.edits;
        if (edits && typeof edits === "object") {
          for (const [key, value] of Object.entries(edits)) {
            const id = Number(key);
            if (!Number.isInteger(id) || id <= 0) {
              continue;
            }
            const draft = parseStoredDraft(value);
            if (!draft) {
              continue;
            }
            state.localEditsById[String(id)] = draft;
          }
        }

        if (Array.isArray(parsed.deleted_ids)) {
          for (const rawId of parsed.deleted_ids) {
            const id = Number(rawId);
            if (Number.isInteger(id) && id > 0) {
              state.deletedLayoutIds.add(id);
              delete state.localEditsById[String(id)];
            }
          }
        }

        const captionBindings = parsed.caption_bindings;
        if (captionBindings && typeof captionBindings === "object") {
          for (const [rawCaptionId, rawTargets] of Object.entries(captionBindings)) {
            const captionId = Number(rawCaptionId);
            if (!Number.isInteger(captionId) || captionId <= 0) {
              continue;
            }
            state.captionBindingsByCaptionId[String(captionId)] = normalizeLayoutIdList(rawTargets);
          }
        }
      }

      function persistLayoutDraftState() {
        if (state.layoutsLoaded) {
          sanitizeCaptionBindingsInPlace();
        }
        const payload = {
          edits: state.localEditsById,
          deleted_ids: Array.from(state.deletedLayoutIds).sort((a, b) => a - b),
          caption_bindings: state.captionBindingsByCaptionId,
        };
        writeStorage(draftStorageKey(), JSON.stringify(payload));
        updateReviewUiState();
      }

      function clearLayoutDraftState() {
        state.localEditsById = {};
        state.deletedLayoutIds = new Set();
        state.captionBindingsByCaptionId = {};
        removeStorage(draftStorageKey());
        updateReviewUiState();
      }

      function rememberLastAddedClass(className) {
        const normalized = normalizeClassName(className) || "text";
        state.lastAddedClass = normalized;
        writeStorage(STORAGE_KEYS.lastAddedClass, normalized);
      }

      function hexToRgba(hex, alpha) {
        const clean = hex.replace("#", "");
        const r = Number.parseInt(clean.slice(0, 2), 16);
        const g = Number.parseInt(clean.slice(2, 4), 16);
        const b = Number.parseInt(clean.slice(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
      }

      function setStatus(message, { isError = false } = {}) {
        if (!statusLine) {
          if (isError) {
            console.error(message);
          }
          return;
        }
        statusLine.textContent = message;
        statusLine.classList.toggle("error", isError);
      }

      function pluralize(count, singular, plural = `${singular}s`) {
        return Number(count) === 1 ? singular : plural;
      }

      function hasPendingLayoutDraftChanges() {
        return (
          Object.keys(state.localEditsById).length > 0 ||
          state.deletedLayoutIds.size > 0 ||
          hasPendingCaptionBindingDraftChanges()
        );
      }

      function pendingCaptionBindingDraftCount() {
        if (!state.layoutsLoaded) {
          return 0;
        }
        let count = 0;
        const captionIds = state.layouts
          .filter((layout) => isCaptionClass(layout.class_name))
          .map((layout) => String(layout.id));
        for (const captionId of captionIds) {
          const currentTargets = normalizeLayoutIdList(state.captionBindingsByCaptionId[captionId]);
          const baselineTargets = normalizeLayoutIdList(state.serverCaptionBindingsByCaptionId[captionId]);
          if (
            currentTargets.length !== baselineTargets.length ||
            currentTargets.some((targetId, index) => targetId !== baselineTargets[index])
          ) {
            count += 1;
          }
        }
        return count;
      }

      function reorderDraftResolutionSummary() {
        const localDraftSummary = summarizeDraftChangesForReorder({
          localEditsById: state.localEditsById,
          serverLayoutsById: state.serverLayoutsById,
        });
        const deletedCount = state.deletedLayoutIds.size;
        const captionBindingCount = pendingCaptionBindingDraftCount();
        const blockingDraftCount = localDraftSummary.blockingDraftCount;
        const hasBlockingChanges =
          blockingDraftCount > 0 || deletedCount > 0 || captionBindingCount > 0;
        if (!hasBlockingChanges) {
          return {
            canReorder: true,
            message: "",
            readingOrderOnlyLayoutIds: localDraftSummary.readingOrderOnlyLayoutIds,
          };
        }
        const details = [];
        if (blockingDraftCount > 0) {
          details.push(
            `${blockingDraftCount} unsaved ${pluralize(blockingDraftCount, "layout edit", "layout edits")}`,
          );
        }
        if (deletedCount > 0) {
          details.push(
            `${deletedCount} pending ${pluralize(deletedCount, "deletion", "deletions")}`,
          );
        }
        if (captionBindingCount > 0) {
          details.push(
            `${captionBindingCount} pending ${pluralize(captionBindingCount, "caption binding change", "caption binding changes")}`,
          );
        }
        return {
          canReorder: false,
          message: `Cannot recompute reading order while ${details.join(", ")} exist. Submit review or restore drafts first.`,
          readingOrderOnlyLayoutIds: [],
        };
      }

      function updateReviewBadge() {
        updateReviewStateBadge({
          badge: reviewStateBadge,
          status: state.page?.status,
          needsReviewStatus: "layout_detected",
          reviewedStatus: "layout_reviewed",
          needsReviewTitle: "This page is waiting for layout review.",
          reviewedTitle: "This page was already marked as layout reviewed.",
          unknownTitleFormatter: (status) => `Current page status: ${status}.`,
        });
      }

      function updateReviewButtonState() {
        const unboundCaptionIds = findUnboundCaptionIds();
        if (state.reviewSubmitInProgress) {
          reviewBtn.textContent = "Saving...";
          reviewBtn.disabled = true;
          reviewBtn.title = "Saving layout review changes.";
          return;
        }
        if (unboundCaptionIds.length > 0) {
          reviewBtn.textContent = "Mark reviewed";
          reviewBtn.disabled = true;
          reviewBtn.title =
            "Each caption must be bound to at least one table, picture, or formula before review.";
          return;
        }

        reviewBtn.textContent = "Mark reviewed";
        reviewBtn.disabled = false;
        const alreadyReviewed = state.page?.status === "layout_reviewed";
        reviewBtn.title = alreadyReviewed
          ? "Submit current changes and keep this page reviewed."
          : "Mark this page as reviewed.";
      }

      function currentLayoutOrderMode() {
        const pageMode = normalizeLayoutOrderMode(state.page?.layout_order_mode, { fallback: "auto" });
        if (state.page) {
          state.page.layout_order_mode = pageMode;
        }
        return pageMode;
      }

      function updateLayoutOrderControls() {
        const mode = currentLayoutOrderMode();
        if (layoutOrderModeInput instanceof HTMLSelectElement) {
          layoutOrderModeInput.value = mode;
          layoutOrderModeInput.disabled = state.layoutOrderModeUpdateInProgress || state.layoutReorderInProgress;
        }
      }

      function updateReviewUiState() {
        updateReviewBadge();
        updateReviewButtonState();
        updateLayoutOrderControls();
      }

      function toFixed(value) {
        return Number(value).toFixed(4);
      }

      function roundTo4(value) {
        return Math.round(Number(value) * 10000) / 10000;
      }

      function boxStyle(layout) {
        const { x1, y1, x2, y2 } = layout.bbox;
        return {
          left: `${x1 * 100}%`,
          top: `${y1 * 100}%`,
          width: `${(x2 - x1) * 100}%`,
          height: `${(y2 - y1) * 100}%`,
        };
      }

      function applyBoxElementStyle(boxElement, bbox, color) {
        const style = boxStyle({ bbox });
        boxElement.style.left = style.left;
        boxElement.style.top = style.top;
        boxElement.style.width = style.width;
        boxElement.style.height = style.height;
        boxElement.style.borderColor = color;
        boxElement.style.background = hexToRgba(color, 0.16);
      }

      function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
      }

      function readingOrderSortValue(layout) {
        const value = Number(layout.reading_order);
        if (Number.isInteger(value) && value >= 1) {
          return value;
        }
        return Number.MAX_SAFE_INTEGER;
      }

      function sortLayoutsInPlace() {
        state.layouts.sort((a, b) => {
          const orderCmp = readingOrderSortValue(a) - readingOrderSortValue(b);
          if (orderCmp !== 0) {
            return orderCmp;
          }
          return Number(a.id) - Number(b.id);
        });
      }

      function findLayoutById(layoutId) {
        return state.layouts.find((row) => Number(row.id) === Number(layoutId)) || null;
      }

      function clearSelectedLayoutIfMissing() {
        if (state.selectedLayoutId === null) {
          return;
        }
        const exists = state.layouts.some((row) => Number(row.id) === Number(state.selectedLayoutId));
        if (!exists) {
          state.selectedLayoutId = null;
        }
      }

      function applySelectedLayoutStyles({ scrollRowIntoView = false } = {}) {
        clearSelectedLayoutIfMissing();
        const selectedId = Number(state.selectedLayoutId);

        for (const rowEl of layoutsBody.querySelectorAll("tr[data-layout-id]")) {
          const rowId = Number(rowEl.dataset.layoutId);
          rowEl.classList.toggle("layout-selected", rowId === selectedId);
        }
        for (const boxEl of overlay.querySelectorAll(".box[data-layout-id]")) {
          const boxId = Number(boxEl.dataset.layoutId);
          boxEl.classList.toggle("layout-selected", boxId === selectedId);
        }

        if (scrollRowIntoView) {
          const selectedRow = layoutsBody.querySelector(`tr[data-layout-id="${selectedId}"]`);
          selectedRow?.scrollIntoView({ block: "nearest" });
        }
      }

      function selectLayout(layoutId, { scrollRowIntoView = false, scrollImageToLayout = false } = {}) {
        const normalizedId = Number(layoutId);
        if (!Number.isInteger(normalizedId)) {
          return;
        }
        const exists = state.layouts.some((row) => Number(row.id) === normalizedId);
        if (!exists) {
          return;
        }
        const previousSelectedLayoutId = Number(state.selectedLayoutId);
        state.selectedLayoutId = normalizedId;
        if (previousSelectedLayoutId !== normalizedId) {
          renderOverlay();
        } else {
          applySelectedLayoutStyles({ scrollRowIntoView });
        }
        if (scrollImageToLayout) {
          ensureLayoutVisible(normalizedId);
        }
      }

      function clearSelectedLayout() {
        if (state.selectedLayoutId === null && state.activePointHighlight === null) {
          return;
        }
        const hadSelectedLayout = state.selectedLayoutId !== null;
        state.selectedLayoutId = null;
        state.activePointHighlight = null;
        if (hadSelectedLayout) {
          renderOverlay();
        } else {
          applySelectedLayoutStyles();
          applyActivePointHighlightStyles();
        }
        imageMagnifier.refresh();
      }

      function clearActivePointHighlightIfMissing() {
        if (!state.activePointHighlight) {
          return;
        }
        const { layoutId } = state.activePointHighlight;
        const exists = state.layouts.some((row) => Number(row.id) === Number(layoutId));
        if (!exists) {
          state.activePointHighlight = null;
        }
      }

      function clearExpandedBboxIfMissing() {
        if (!Number.isInteger(Number(state.expandedBboxLayoutId))) {
          state.expandedBboxLayoutId = null;
          return;
        }
        const exists = state.layouts.some((row) => Number(row.id) === Number(state.expandedBboxLayoutId));
        if (!exists) {
          state.expandedBboxLayoutId = null;
        }
      }

      function applyActivePointHighlightStyles() {
        clearActivePointHighlightIfMissing();
        const highlight = state.activePointHighlight;
        const selector = highlight
          ? `.box-handle[data-layout-id="${highlight.layoutId}"][data-handle="${highlight.handle}"]`
          : null;

        for (const handleEl of overlay.querySelectorAll(".box-handle")) {
          const isActive = Boolean(selector) && handleEl.matches(selector);
          handleEl.classList.toggle("point-highlight", isActive);
        }
      }

      function setActivePointHighlight(layoutId, handle) {
        const normalizedId = Number(layoutId);
        if (!Number.isInteger(normalizedId)) {
          return;
        }
        const exists = state.layouts.some((row) => Number(row.id) === normalizedId);
        if (!exists) {
          return;
        }
        if (handle !== "nw" && handle !== "se") {
          return;
        }
        state.activePointHighlight = { layoutId: normalizedId, handle };
        applyActivePointHighlightStyles();
      }

      function hideCursorGuides() {
        if (cursorGuideHorizontal instanceof HTMLElement) {
          cursorGuideHorizontal.hidden = true;
        }
        if (cursorGuideVertical instanceof HTMLElement) {
          cursorGuideVertical.hidden = true;
        }
      }

      function updateCursorGuidesFromPointerEvent(event) {
        if (!(event instanceof PointerEvent)) {
          return;
        }
        if (!(cursorGuideHorizontal instanceof HTMLElement) || !(cursorGuideVertical instanceof HTMLElement)) {
          return;
        }
        const rect = overlay.getBoundingClientRect();
        if (!rect.width || !rect.height) {
          hideCursorGuides();
          return;
        }
        const localX = event.clientX - rect.left;
        const localY = event.clientY - rect.top;
        if (localX < 0 || localY < 0 || localX > rect.width || localY > rect.height) {
          hideCursorGuides();
          return;
        }
        const x = Math.round(Math.max(0, Math.min(rect.width, localX)));
        const y = Math.round(Math.max(0, Math.min(rect.height, localY)));
        cursorGuideHorizontal.style.top = `${y}px`;
        cursorGuideVertical.style.left = `${x}px`;
        cursorGuideHorizontal.hidden = false;
        cursorGuideVertical.hidden = false;
      }

      function clearActivePointHighlight(layoutId, handle) {
        const current = state.activePointHighlight;
        if (!current) {
          return;
        }
        if (Number(current.layoutId) !== Number(layoutId) || current.handle !== handle) {
          return;
        }
        state.activePointHighlight = null;
        applyActivePointHighlightStyles();
      }

      function upsertDraftForLayout(layoutId, draft) {
        const layout = findLayoutById(layoutId);
        if (!layout) {
          return false;
        }

        layout.class_name = draft.class_name;
        layout.reading_order = draft.reading_order;
        layout.orientation = normalizeLayoutOrientationValue(draft.orientation);
        layout.bbox = { ...draft.bbox };

        const serverLayout = state.serverLayoutsById[String(layoutId)];
        const serverBaseline = serverLayout ? toDraftShape(serverLayout) : toDraftShape(layout);
        if (sameDraft(draft, serverBaseline)) {
          delete state.localEditsById[String(layoutId)];
        } else {
          state.localEditsById[String(layoutId)] = draft;
        }
        state.deletedLayoutIds.delete(Number(layoutId));
        persistLayoutDraftState();
        return true;
      }

      function clearRowDragUi() {
        for (const row of layoutsBody.querySelectorAll("tr.layout-dragging, tr.layout-drop-target")) {
          row.classList.remove("layout-dragging", "layout-drop-target");
        }
      }

      function resetRowDragState() {
        state.draggingLayoutId = null;
        state.dragOverLayoutId = null;
        clearRowDragUi();
      }

      function layoutIdsInCurrentOrder() {
        sortLayoutsInPlace();
        return state.layouts
          .map((layout) => Number(layout.id))
          .filter((layoutId) => Number.isInteger(layoutId) && layoutId > 0);
      }

      function syncDraftWithServerBaseline(layoutId) {
        const layout = findLayoutById(layoutId);
        if (!layout) {
          return;
        }
        const draft = toDraftShape(layout);
        const serverLayout = state.serverLayoutsById[String(layoutId)];
        const serverBaseline = serverLayout ? toDraftShape(serverLayout) : draft;
        if (sameDraft(draft, serverBaseline)) {
          delete state.localEditsById[String(layoutId)];
        } else {
          state.localEditsById[String(layoutId)] = draft;
        }
        state.deletedLayoutIds.delete(Number(layoutId));
      }

      function applySequentialReadingOrder(layoutIdSequence) {
        const sequence = Array.isArray(layoutIdSequence)
          ? layoutIdSequence
              .map((layoutId) => Number(layoutId))
              .filter((layoutId) => Number.isInteger(layoutId) && layoutId > 0)
          : [];
        if (sequence.length === 0) {
          return false;
        }

        let changed = false;
        for (let index = 0; index < sequence.length; index += 1) {
          const layoutId = sequence[index];
          const layout = findLayoutById(layoutId);
          if (!layout) {
            continue;
          }
          const nextOrder = index + 1;
          if (Number(layout.reading_order) !== nextOrder) {
            changed = true;
          }
          layout.reading_order = nextOrder;
          syncDraftWithServerBaseline(layoutId);
        }

        if (!changed) {
          return false;
        }
        persistLayoutDraftState();
        renderLayouts();
        return true;
      }

      function markLayoutDeleted(layoutId) {
        const normalizedLayoutId = Number(layoutId);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          return false;
        }
        const removedLayout = state.layouts.find((row) => Number(row.id) === normalizedLayoutId) || null;
        if (!removedLayout) {
          return false;
        }
        const removedOrder = removedLayout.reading_order;

        state.deletedLayoutIds.add(normalizedLayoutId);
        delete state.localEditsById[String(normalizedLayoutId)];
        delete state.captionBindingsByCaptionId[String(normalizedLayoutId)];
        if (Number(state.activeBindingCaptionId) === normalizedLayoutId) {
          state.activeBindingCaptionId = null;
        }
        for (const [captionId, targetIds] of Object.entries(state.captionBindingsByCaptionId)) {
          state.captionBindingsByCaptionId[captionId] = normalizeLayoutIdList(targetIds).filter(
            (targetId) => targetId !== normalizedLayoutId,
          );
        }

        const remainingLayouts = state.layouts.filter((row) => Number(row.id) !== normalizedLayoutId);
        const { layouts: compactedLayouts, shiftedIds } = compactReadingOrdersAfterDeletion(
          remainingLayouts,
          removedOrder,
        );
        state.layouts = compactedLayouts;

        for (const shiftedId of shiftedIds) {
          const shiftedLayout = state.layouts.find((row) => Number(row.id) === Number(shiftedId));
          if (!shiftedLayout) {
            continue;
          }
          const shiftedDraft = toDraftShape(shiftedLayout);
          const shiftedServer = state.serverLayoutsById[String(shiftedId)];
          const shiftedBaseline = shiftedServer ? toDraftShape(shiftedServer) : shiftedDraft;
          if (sameDraft(shiftedDraft, shiftedBaseline)) {
            delete state.localEditsById[String(shiftedId)];
          } else {
            state.localEditsById[String(shiftedId)] = shiftedDraft;
          }
          state.deletedLayoutIds.delete(Number(shiftedId));
        }

        persistLayoutDraftState();
        renderLayouts();
        return true;
      }

      function setRowDropIndicator(targetLayoutId) {
        const targetId = Number(targetLayoutId);
        if (!Number.isInteger(targetId) || targetId <= 0) {
          return;
        }
        if (targetId === Number(state.draggingLayoutId)) {
          return;
        }
        if (state.dragOverLayoutId === targetId) {
          return;
        }

        clearRowDragUi();
        const draggingRow = layoutsBody.querySelector(`tr[data-layout-id="${state.draggingLayoutId}"]`);
        draggingRow?.classList.add("layout-dragging");

        const row = layoutsBody.querySelector(`tr[data-layout-id="${targetId}"]`);
        if (!row) {
          return;
        }
        row.classList.add("layout-drop-target");
        state.dragOverLayoutId = targetId;
      }

      function finishRowReorder(targetLayoutId) {
        const draggingLayoutId = Number(state.draggingLayoutId);
        if (!Number.isInteger(draggingLayoutId) || draggingLayoutId <= 0) {
          resetRowDragState();
          return;
        }

        const orderedIds = layoutIdsInCurrentOrder();
        const nextOrder = reorderReadingOrderIds({
          orderedIds,
          draggedId: draggingLayoutId,
          targetId: targetLayoutId,
          position: targetLayoutId === null || targetLayoutId === undefined ? "after" : "before",
        });
        resetRowDragState();
        if (!nextOrder) {
          return;
        }
        const changed = applySequentialReadingOrder(nextOrder);
        if (changed) {
          selectLayout(draggingLayoutId, { scrollRowIntoView: true, scrollImageToLayout: true });
          setStatus("Draft saved locally. Order updated by drag-and-drop.");
        }
      }

      function moveLayoutToOrder(layoutId, requestedOrder) {
        const normalizedLayoutId = Number(layoutId);
        const desiredOrder = Number(requestedOrder);
        if (
          !Number.isInteger(normalizedLayoutId) ||
          normalizedLayoutId <= 0 ||
          !Number.isInteger(desiredOrder)
        ) {
          return false;
        }
        const orderedIds = layoutIdsInCurrentOrder();
        const currentIndex = orderedIds.indexOf(normalizedLayoutId);
        if (currentIndex < 0) {
          return false;
        }
        const total = orderedIds.length;
        const targetOrder = Math.max(1, Math.min(total, desiredOrder));
        if (targetOrder === currentIndex + 1) {
          return false;
        }
        const nextOrder = swapReadingOrderIds({
          orderedIds,
          movedId: normalizedLayoutId,
          targetOrder,
        });
        if (!nextOrder) {
          return false;
        }
        return applySequentialReadingOrder(nextOrder);
      }

      function rowDragStart(event, layoutId) {
        const target = event.target;
        if (
          target instanceof Element &&
          target.closest("input, select, button, textarea, label, .row-actions")
        ) {
          event.preventDefault();
          return;
        }

        const normalizedLayoutId = Number(layoutId);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          event.preventDefault();
          return;
        }

        state.draggingLayoutId = normalizedLayoutId;
        state.dragOverLayoutId = null;
        clearRowDragUi();

        const row = event.currentTarget;
        if (row instanceof HTMLTableRowElement) {
          row.classList.add("layout-dragging");
        }
        if (event.dataTransfer) {
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", String(normalizedLayoutId));
        }
        selectLayout(normalizedLayoutId, { scrollImageToLayout: true });
      }

      function rowDragOver(event, layoutId) {
        if (!Number.isInteger(Number(state.draggingLayoutId))) {
          return;
        }
        event.preventDefault();
        const row = event.currentTarget;
        if (!(row instanceof HTMLTableRowElement)) {
          return;
        }
        setRowDropIndicator(layoutId);
        if (event.dataTransfer) {
          event.dataTransfer.dropEffect = "move";
        }
      }

      function rowDrop(event, layoutId) {
        if (!Number.isInteger(Number(state.draggingLayoutId))) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        finishRowReorder(layoutId);
      }

      function bboxWithMinSize(bbox, handle) {
        const minSize = 0.001;
        let { x1, y1, x2, y2 } = bbox;

        x1 = clamp(x1, 0, 1);
        x2 = clamp(x2, 0, 1);
        y1 = clamp(y1, 0, 1);
        y2 = clamp(y2, 0, 1);

        if (x2 - x1 < minSize) {
          if (handle.includes("w")) {
            x1 = x2 - minSize;
          } else {
            x2 = x1 + minSize;
          }
        }
        if (y2 - y1 < minSize) {
          if (handle.includes("n")) {
            y1 = y2 - minSize;
          } else {
            y2 = y1 + minSize;
          }
        }

        x1 = clamp(x1, 0, 1 - minSize);
        x2 = clamp(x2, minSize, 1);
        y1 = clamp(y1, 0, 1 - minSize);
        y2 = clamp(y2, minSize, 1);

        if (x2 - x1 < minSize) {
          x2 = clamp(x1 + minSize, minSize, 1);
        }
        if (y2 - y1 < minSize) {
          y2 = clamp(y1 + minSize, minSize, 1);
        }

        return {
          x1: roundTo4(x1),
          y1: roundTo4(y1),
          x2: roundTo4(x2),
          y2: roundTo4(y2),
        };
      }

      function resizeBBox(startBBox, deltaX, deltaY, handle) {
        const next = { ...startBBox };
        if (handle.includes("w")) next.x1 += deltaX;
        if (handle.includes("e")) next.x2 += deltaX;
        if (handle.includes("n")) next.y1 += deltaY;
        if (handle.includes("s")) next.y2 += deltaY;
        return bboxWithMinSize(next, handle);
      }

      function intermediateResizeHandleCount(
        sideLengthPx,
        { spacingPx = 180, minCount = 1, maxCount = 10 } = {},
      ) {
        const side = Number(sideLengthPx);
        const spacing = Number(spacingPx);
        const min = Math.max(0, Math.floor(Number(minCount) || 0));
        const max = Math.max(min, Math.floor(Number(maxCount) || min));
        if (!Number.isFinite(side) || side <= 0 || !Number.isFinite(spacing) || spacing <= 0) {
          return min;
        }
        const estimated = Math.floor(side / spacing);
        return Math.max(min, Math.min(max, estimated));
      }

      function adaptiveResizeHandlesForBBox(bbox, overlayWidth, overlayHeight) {
        const widthPx = Math.max(0, Math.abs(Number(bbox.x2) - Number(bbox.x1)) * overlayWidth);
        const heightPx = Math.max(0, Math.abs(Number(bbox.y2) - Number(bbox.y1)) * overlayHeight);
        const topCount = intermediateResizeHandleCount(widthPx, {
          spacingPx: RESIZE_HANDLE_SPACING_PX,
          minCount: RESIZE_HANDLE_MIN_INTERMEDIATE,
          maxCount: RESIZE_HANDLE_MAX_INTERMEDIATE,
        });
        const sideCount = intermediateResizeHandleCount(heightPx, {
          spacingPx: RESIZE_HANDLE_SPACING_PX,
          minCount: RESIZE_HANDLE_MIN_INTERMEDIATE,
          maxCount: RESIZE_HANDLE_MAX_INTERMEDIATE,
        });

        const handles = [
          { key: "nw", xRatio: 0, yRatio: 0, cursor: "nwse-resize" },
          { key: "ne", xRatio: 1, yRatio: 0, cursor: "nesw-resize" },
          { key: "se", xRatio: 1, yRatio: 1, cursor: "nwse-resize" },
          { key: "sw", xRatio: 0, yRatio: 1, cursor: "nesw-resize" },
        ];

        for (let index = 1; index <= topCount; index += 1) {
          const ratio = index / (topCount + 1);
          handles.push({ key: `n-${index}`, xRatio: ratio, yRatio: 0, cursor: "ns-resize" });
          handles.push({ key: `s-${index}`, xRatio: ratio, yRatio: 1, cursor: "ns-resize" });
        }
        for (let index = 1; index <= sideCount; index += 1) {
          const ratio = index / (sideCount + 1);
          handles.push({ key: `e-${index}`, xRatio: 1, yRatio: ratio, cursor: "ew-resize" });
          handles.push({ key: `w-${index}`, xRatio: 0, yRatio: ratio, cursor: "ew-resize" });
        }
        return handles;
      }

      function beginOverlayDrag(event, layoutId, handle, boxElement, color) {
        if (event.button !== 0) {
          return;
        }
        const layout = findLayoutById(layoutId);
        if (!layout) {
          return;
        }

        event.preventDefault();
        event.stopPropagation();
        selectLayout(layoutId, { scrollRowIntoView: true });
        boxElement.setPointerCapture?.(event.pointerId);

        const rect = overlay.getBoundingClientRect();
        if (!rect.width || !rect.height) {
          return;
        }

        const startClientX = event.clientX;
        const startClientY = event.clientY;
        const startBBox = { ...layout.bbox };

        const onPointerMove = (moveEvent) => {
          const dx = (moveEvent.clientX - startClientX) / rect.width;
          const dy = (moveEvent.clientY - startClientY) / rect.height;

          const nextBBox = resizeBBox(startBBox, dx, dy, handle);
          layout.bbox = { ...nextBBox };
          applyBoxElementStyle(boxElement, nextBBox, color);
        };

        const finish = () => {
          window.removeEventListener("pointermove", onPointerMove);
          window.removeEventListener("pointerup", onPointerUp);
          window.removeEventListener("pointercancel", onPointerCancel);

          const latest = findLayoutById(layoutId);
          if (!latest) {
            return;
          }
          const draft = toDraftShape(latest);
          if (!upsertDraftForLayout(layoutId, draft)) {
            return;
          }
          renderLayouts();
          setStatus("Layout draft updated from canvas.");
        };

        const onPointerUp = () => {
          finish();
        };
        const onPointerCancel = () => {
          finish();
        };

        window.addEventListener("pointermove", onPointerMove);
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("pointercancel", onPointerCancel);
      }

      function renderOverlay() {
        overlay.innerHTML = "";
        const overlayWidth = Math.max(1, overlay.clientWidth || pageImage.clientWidth || imageWrap.offsetWidth || 1);
        const overlayHeight = Math.max(1, overlay.clientHeight || pageImage.clientHeight || imageWrap.offsetHeight || 1);

        const bindingLinesLayer = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        bindingLinesLayer.id = "bind-lines-layer";
        bindingLinesLayer.setAttribute("viewBox", `0 0 ${overlayWidth} ${overlayHeight}`);
        bindingLinesLayer.setAttribute("preserveAspectRatio", "none");
        bindingLinesLayer.setAttribute("width", String(overlayWidth));
        bindingLinesLayer.setAttribute("height", String(overlayHeight));

        const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
        const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
        marker.setAttribute("id", "bind-arrowhead");
        marker.setAttribute("viewBox", "0 0 10 10");
        marker.setAttribute("refX", "9");
        marker.setAttribute("refY", "5");
        marker.setAttribute("markerWidth", "5");
        marker.setAttribute("markerHeight", "5");
        marker.setAttribute("orient", "auto-start-reverse");
        const markerPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        markerPath.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
        markerPath.setAttribute("fill", "#496f98");
        marker.appendChild(markerPath);
        defs.appendChild(marker);
        bindingLinesLayer.appendChild(defs);
        overlay.appendChild(bindingLinesLayer);
        const overlapLayer = document.createElement("div");
        overlapLayer.className = "overlap-layer";
        overlay.appendChild(overlapLayer);
        const cursorGuidesLayer = document.createElement("div");
        cursorGuidesLayer.id = "cursor-guides-layer";
        const horizontalGuide = document.createElement("div");
        horizontalGuide.className = "cursor-guide-line horizontal";
        horizontalGuide.style.width = `${overlayWidth}px`;
        horizontalGuide.hidden = true;
        const verticalGuide = document.createElement("div");
        verticalGuide.className = "cursor-guide-line vertical";
        verticalGuide.style.height = `${overlayHeight}px`;
        verticalGuide.hidden = true;
        cursorGuidesLayer.appendChild(horizontalGuide);
        cursorGuidesLayer.appendChild(verticalGuide);
        overlay.appendChild(cursorGuidesLayer);
        cursorGuideHorizontal = horizontalGuide;
        cursorGuideVertical = verticalGuide;

        const activeBindingCaptionId = Number(state.activeBindingCaptionId);
        const selectedLayoutId = Number(state.selectedLayoutId);
        const activeBindingTargetIds = Number.isInteger(activeBindingCaptionId) && activeBindingCaptionId > 0
          ? new Set(captionTargetIds(activeBindingCaptionId))
          : new Set();
        const layoutColorById = new Map();

        for (const layout of state.layouts) {
          const layoutId = Number(layout.id);
          const color = colorForClass(layout.class_name);
          if (Number.isInteger(layoutId) && layoutId > 0) {
            layoutColorById.set(layoutId, color);
          }
          const box = document.createElement("div");
          box.className = "box";
          box.dataset.layoutId = String(layoutId);
          applyBoxElementStyle(box, layout.bbox, color);
          if (layoutId === activeBindingCaptionId) {
            box.classList.add("binding-caption-active");
          } else if (Number.isInteger(activeBindingCaptionId) && activeBindingCaptionId > 0 && isCaptionTargetClass(layout.class_name)) {
            box.classList.add("binding-target-candidate");
            if (activeBindingTargetIds.has(layoutId)) {
              box.classList.add("binding-target-linked");
            }
          }
          box.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) {
              return;
            }
            const target = event.target;
            if (target instanceof Element && target.closest(".box-handle, .box-overlay-btn")) {
              return;
            }

            if (Number.isInteger(activeBindingCaptionId) && activeBindingCaptionId > 0) {
              if (layoutId === activeBindingCaptionId) {
                selectLayout(layoutId, { scrollRowIntoView: true, scrollImageToLayout: true });
                return;
              }
              if (isCaptionTargetClass(layout.class_name)) {
                const applied = toggleCaptionTargetBinding(activeBindingCaptionId, layoutId);
                if (applied) {
                  const nowLinked = captionTargetIds(activeBindingCaptionId).includes(layoutId);
                  setStatus(
                    nowLinked
                      ? "Caption binding saved locally."
                      : "Caption unbound locally.",
                  );
                  renderLayouts();
                }
                return;
              }
            }
            selectLayout(layoutId, { scrollRowIntoView: true, scrollImageToLayout: true });
          });

          const label = document.createElement("div");
          label.className = "box-label";
          label.style.color = color;
          label.style.borderColor = hexToRgba(color, 0.62);
          label.textContent = `${layout.reading_order}. ${formatClassLabel(layout.class_name)}`;
          box.appendChild(label);

          if (isCaptionClass(layout.class_name)) {
            const cornerControls = document.createElement("div");
            cornerControls.className = "box-corner-controls";

            const bindBtn = document.createElement("button");
            bindBtn.className = "box-bind-btn box-overlay-btn";
            bindBtn.type = "button";
            bindBtn.textContent = "🔗︎";
            const isActiveCaption = layoutId === activeBindingCaptionId;
            bindBtn.classList.toggle("active", isActiveCaption);
            bindBtn.title = isActiveCaption ? "Exit bind mode" : "Bind caption";
            bindBtn.setAttribute("aria-label", isActiveCaption ? "Exit bind mode" : "Bind caption");
            bindBtn.addEventListener("pointerdown", (event) => {
              event.stopPropagation();
            });
            bindBtn.addEventListener("click", (event) => {
              event.preventDefault();
              event.stopPropagation();
              if (layoutId === Number(state.activeBindingCaptionId)) {
                setActiveBindingCaption(null);
                setStatus("Bind mode closed.");
              } else {
                setActiveBindingCaption(layoutId);
                setStatus("Bind mode enabled. Click table, picture, or formula boxes to toggle binding.");
              }
            });
            cornerControls.appendChild(bindBtn);

            if (layoutId === selectedLayoutId) {
              const orientationBtn = document.createElement("button");
              orientationBtn.className = "box-orientation-btn box-overlay-btn";
              orientationBtn.type = "button";
              const currentOrientation = normalizeLayoutOrientationValue(layout.orientation);
              const currentIndex = LAYOUT_ORIENTATION_VALUES.indexOf(currentOrientation);
              const nextOrientation =
                LAYOUT_ORIENTATION_VALUES[(currentIndex + 1 + LAYOUT_ORIENTATION_VALUES.length) % LAYOUT_ORIENTATION_VALUES.length];
              orientationBtn.textContent = LAYOUT_ORIENTATION_GLYPH_BY_VALUE[currentOrientation] || "◌";
              orientationBtn.title = `Orientation: ${currentOrientation}. Click to set ${nextOrientation}.`;
              orientationBtn.setAttribute("aria-label", `Set orientation ${nextOrientation}`);
              orientationBtn.addEventListener("pointerdown", (event) => {
                event.stopPropagation();
              });
              orientationBtn.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const latestLayout = findLayoutById(layoutId);
                if (!latestLayout) {
                  return;
                }
                const draft = toDraftShape(latestLayout);
                draft.orientation = nextOrientation;
                if (!upsertDraftForLayout(layoutId, draft)) {
                  return;
                }
                renderLayouts();
                setStatus(`Orientation set to ${nextOrientation}.`);
              });
              cornerControls.appendChild(orientationBtn);
            }

            box.appendChild(cornerControls);
          } else if (layoutId === selectedLayoutId) {
            const cornerControls = document.createElement("div");
            cornerControls.className = "box-corner-controls";
            const orientationBtn = document.createElement("button");
            orientationBtn.className = "box-orientation-btn box-overlay-btn";
            orientationBtn.type = "button";
            const currentOrientation = normalizeLayoutOrientationValue(layout.orientation);
            const currentIndex = LAYOUT_ORIENTATION_VALUES.indexOf(currentOrientation);
            const nextOrientation =
              LAYOUT_ORIENTATION_VALUES[(currentIndex + 1 + LAYOUT_ORIENTATION_VALUES.length) % LAYOUT_ORIENTATION_VALUES.length];
            orientationBtn.textContent = LAYOUT_ORIENTATION_GLYPH_BY_VALUE[currentOrientation] || "◌";
            orientationBtn.title = `Orientation: ${currentOrientation}. Click to set ${nextOrientation}.`;
            orientationBtn.setAttribute("aria-label", `Set orientation ${nextOrientation}`);
            orientationBtn.addEventListener("pointerdown", (event) => {
              event.stopPropagation();
            });
            orientationBtn.addEventListener("click", (event) => {
              event.preventDefault();
              event.stopPropagation();
              const latestLayout = findLayoutById(layoutId);
              if (!latestLayout) {
                return;
              }
              const draft = toDraftShape(latestLayout);
              draft.orientation = nextOrientation;
              if (!upsertDraftForLayout(layoutId, draft)) {
                return;
              }
              renderLayouts();
              setStatus(`Orientation set to ${nextOrientation}.`);
            });
            cornerControls.appendChild(orientationBtn);
            box.appendChild(cornerControls);
          }

          const resizeHandles = adaptiveResizeHandlesForBBox(layout.bbox, overlayWidth, overlayHeight);
          for (const handle of resizeHandles) {
            const handleEl = document.createElement("div");
            handleEl.className = "box-handle";
            handleEl.dataset.handle = handle.key;
            handleEl.dataset.layoutId = String(layoutId);
            handleEl.style.left = `${(handle.xRatio * 100).toFixed(4)}%`;
            handleEl.style.top = `${(handle.yRatio * 100).toFixed(4)}%`;
            handleEl.style.cursor = handle.cursor;
            handleEl.addEventListener("pointerdown", (event) => {
              beginOverlayDrag(event, layoutId, handle.key, box, color);
            });
            box.appendChild(handleEl);
          }

          overlay.appendChild(box);
        }

        const overlapSegments = detectOverlappingBorderSegments({
          layouts: state.layouts,
          contentWidth: overlayWidth,
          contentHeight: overlayHeight,
          minOverlapPx: 1,
        });
        const overlapThickness = 3;
        for (const segment of overlapSegments) {
          const orientation = String(segment.orientation || "");
          const coordPx = Number(segment.coordPx);
          const startPx = Number(segment.startPx);
          const endPx = Number(segment.endPx);
          if (
            !Number.isFinite(coordPx) ||
            !Number.isFinite(startPx) ||
            !Number.isFinite(endPx) ||
            endPx <= startPx
          ) {
            continue;
          }
          const mainColor =
            layoutColorById.get(Number(segment.layoutIdA)) ||
            layoutColorById.get(Number(segment.layoutIdB)) ||
            "#355fa8";
          const overlapEl = document.createElement("div");
          overlapEl.className = "overlap-segment";
          if (orientation === "horizontal") {
            overlapEl.style.left = `${startPx.toFixed(2)}px`;
            overlapEl.style.top = `${(coordPx - overlapThickness / 2).toFixed(2)}px`;
            overlapEl.style.width = `${(endPx - startPx).toFixed(2)}px`;
            overlapEl.style.height = `${overlapThickness}px`;
            overlapEl.style.background = `repeating-linear-gradient(90deg, ${hexToRgba(mainColor, 0.95)} 0 5px, ${hexToRgba("#cc2f2f", 0.95)} 5px 10px)`;
          } else if (orientation === "vertical") {
            overlapEl.style.left = `${(coordPx - overlapThickness / 2).toFixed(2)}px`;
            overlapEl.style.top = `${startPx.toFixed(2)}px`;
            overlapEl.style.width = `${overlapThickness}px`;
            overlapEl.style.height = `${(endPx - startPx).toFixed(2)}px`;
            overlapEl.style.background = `repeating-linear-gradient(180deg, ${hexToRgba(mainColor, 0.95)} 0 5px, ${hexToRgba("#cc2f2f", 0.95)} 5px 10px)`;
          } else {
            continue;
          }
          overlapLayer.appendChild(overlapEl);
        }

        const pixelRectFromBBox = (bbox) => {
          const rawX1 = Number(bbox.x1) * overlayWidth;
          const rawX2 = Number(bbox.x2) * overlayWidth;
          const rawY1 = Number(bbox.y1) * overlayHeight;
          const rawY2 = Number(bbox.y2) * overlayHeight;
          return {
            left: Math.min(rawX1, rawX2),
            right: Math.max(rawX1, rawX2),
            top: Math.min(rawY1, rawY2),
            bottom: Math.max(rawY1, rawY2),
          };
        };

        const shortestConnectorBetweenRects = (sourceRect, targetRect) => {
          let sourceX;
          let targetX;
          if (sourceRect.right < targetRect.left) {
            sourceX = sourceRect.right;
            targetX = targetRect.left;
          } else if (targetRect.right < sourceRect.left) {
            sourceX = sourceRect.left;
            targetX = targetRect.right;
          } else {
            const overlapLeft = Math.max(sourceRect.left, targetRect.left);
            const overlapRight = Math.min(sourceRect.right, targetRect.right);
            const overlapMidX = (overlapLeft + overlapRight) / 2;
            sourceX = overlapMidX;
            targetX = overlapMidX;
          }

          let sourceY;
          let targetY;
          if (sourceRect.bottom < targetRect.top) {
            sourceY = sourceRect.bottom;
            targetY = targetRect.top;
          } else if (targetRect.bottom < sourceRect.top) {
            sourceY = sourceRect.top;
            targetY = targetRect.bottom;
          } else {
            const overlapTop = Math.max(sourceRect.top, targetRect.top);
            const overlapBottom = Math.min(sourceRect.bottom, targetRect.bottom);
            const overlapMidY = (overlapTop + overlapBottom) / 2;
            sourceY = overlapMidY;
            targetY = overlapMidY;
          }

          return {
            source: { x: sourceX, y: sourceY },
            target: { x: targetX, y: targetY },
          };
        };

        for (const layout of state.layouts) {
          if (!isCaptionClass(layout.class_name)) {
            continue;
          }
          const captionId = Number(layout.id);
          if (!Number.isInteger(captionId) || captionId <= 0) {
            continue;
          }
          const captionRect = pixelRectFromBBox(layout.bbox);
          const targets = captionTargetIds(captionId);
          const isActiveCaption = captionId === activeBindingCaptionId;
          for (const targetId of targets) {
            const targetLayout = findLayoutById(targetId);
            if (!targetLayout || !isCaptionTargetClass(targetLayout.class_name)) {
              continue;
            }
            const targetRect = pixelRectFromBBox(targetLayout.bbox);
            const connector = shortestConnectorBetweenRects(captionRect, targetRect);
            const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
            line.setAttribute("x1", connector.source.x.toFixed(2));
            line.setAttribute("y1", connector.source.y.toFixed(2));
            line.setAttribute("x2", connector.target.x.toFixed(2));
            line.setAttribute("y2", connector.target.y.toFixed(2));
            line.setAttribute("stroke", "#496f98");
            line.setAttribute("stroke-opacity", isActiveCaption ? "0.92" : "0.56");
            line.setAttribute("stroke-width", isActiveCaption ? "2.2" : "1.6");
            line.setAttribute("marker-end", "url(#bind-arrowhead)");
            bindingLinesLayer.appendChild(line);
          }
        }

        applySelectedLayoutStyles();
        applyActivePointHighlightStyles();
      }

      function normalizeLayoutIdList(values) {
        if (!Array.isArray(values)) {
          return [];
        }
        const uniqueIds = new Set();
        for (const rawValue of values) {
          const value = Number(rawValue);
          if (!Number.isInteger(value) || value <= 0) {
            continue;
          }
          uniqueIds.add(value);
        }
        return Array.from(uniqueIds).sort((a, b) => a - b);
      }

      function isCaptionClass(className) {
        return isCaptionClassName(className);
      }

      function isCaptionTargetClass(className) {
        return isCaptionTargetClassName(className);
      }

      function captionTargetIds(captionLayoutId) {
        return normalizeLayoutIdList(state.captionBindingsByCaptionId[String(captionLayoutId)]);
      }

      function setCaptionTargetIds(captionLayoutId, targetLayoutIds) {
        const normalizedCaptionId = Number(captionLayoutId);
        if (!Number.isInteger(normalizedCaptionId) || normalizedCaptionId <= 0) {
          return false;
        }
        const captionLayout = findLayoutById(normalizedCaptionId);
        if (!captionLayout || !isCaptionClass(captionLayout.class_name)) {
          return false;
        }
        const normalizedTargets = normalizeLayoutIdList(targetLayoutIds).filter((targetId) => {
          if (targetId === normalizedCaptionId) {
            return false;
          }
          const targetLayout = findLayoutById(targetId);
          return Boolean(targetLayout && isCaptionTargetClass(targetLayout.class_name));
        });
        state.captionBindingsByCaptionId[String(normalizedCaptionId)] = normalizedTargets;
        persistLayoutDraftState();
        return true;
      }

      function toggleCaptionTargetBinding(captionLayoutId, targetLayoutId) {
        const normalizedCaptionId = Number(captionLayoutId);
        const normalizedTargetId = Number(targetLayoutId);
        if (!Number.isInteger(normalizedCaptionId) || normalizedCaptionId <= 0) {
          return false;
        }
        if (!Number.isInteger(normalizedTargetId) || normalizedTargetId <= 0) {
          return false;
        }
        const targetLayout = findLayoutById(normalizedTargetId);
        if (!targetLayout || !isCaptionTargetClass(targetLayout.class_name)) {
          return false;
        }
        const current = captionTargetIds(normalizedCaptionId);
        const hasBinding = current.includes(normalizedTargetId);
        const nextTargets = hasBinding
          ? current.filter((value) => value !== normalizedTargetId)
          : [...current, normalizedTargetId];
        return setCaptionTargetIds(normalizedCaptionId, nextTargets);
      }

      function setActiveBindingCaption(captionLayoutId) {
        if (captionLayoutId === null) {
          state.activeBindingCaptionId = null;
          renderOverlay();
          return;
        }
        const normalizedId = Number(captionLayoutId);
        if (!Number.isInteger(normalizedId) || normalizedId <= 0) {
          return;
        }
        const captionLayout = findLayoutById(normalizedId);
        if (!captionLayout || !isCaptionClass(captionLayout.class_name)) {
          return;
        }
        state.activeBindingCaptionId = normalizedId;
        selectLayout(normalizedId, { scrollRowIntoView: true, scrollImageToLayout: true });
        renderOverlay();
      }

      function clearActiveBindingCaptionIfMissing() {
        if (!Number.isInteger(Number(state.activeBindingCaptionId))) {
          state.activeBindingCaptionId = null;
          return;
        }
        const captionLayout = findLayoutById(state.activeBindingCaptionId);
        if (!captionLayout || !isCaptionClass(captionLayout.class_name)) {
          state.activeBindingCaptionId = null;
        }
      }

      function sanitizeCaptionBindingsInPlace() {
        if (!state.layoutsLoaded) {
          return;
        }

        const captionIds = new Set();
        const targetIds = new Set();
        for (const layout of state.layouts) {
          const layoutId = Number(layout.id);
          if (!Number.isInteger(layoutId) || layoutId <= 0) {
            continue;
          }
          if (isCaptionClass(layout.class_name)) {
            captionIds.add(layoutId);
          }
          if (isCaptionTargetClass(layout.class_name)) {
            targetIds.add(layoutId);
          }
        }

        const nextBindings = {};
        for (const captionId of captionIds) {
          const key = String(captionId);
          const sourceList = Array.isArray(state.captionBindingsByCaptionId[key])
            ? state.captionBindingsByCaptionId[key]
            : state.serverCaptionBindingsByCaptionId[key] || [];
          const sanitizedTargets = normalizeLayoutIdList(sourceList).filter(
            (targetId) => targetId !== captionId && targetIds.has(targetId),
          );
          nextBindings[key] = sanitizedTargets;
        }
        state.captionBindingsByCaptionId = nextBindings;
        clearActiveBindingCaptionIfMissing();
      }

      function hasPendingCaptionBindingDraftChanges() {
        return pendingCaptionBindingDraftCount() > 0;
      }

      function findUnboundCaptionIds() {
        if (!state.layoutsLoaded) {
          return [];
        }
        const unbound = [];
        for (const layout of state.layouts) {
          if (!isCaptionClass(layout.class_name)) {
            continue;
          }
          const layoutId = Number(layout.id);
          const targets = normalizeLayoutIdList(state.captionBindingsByCaptionId[String(layoutId)]);
          if (targets.length === 0) {
            unbound.push(layoutId);
          }
        }
        return unbound.sort((a, b) => a - b);
      }

      function buildClassSelect(initialClass) {
        const select = document.createElement("select");
        const normalizedInitial = normalizeClassName(initialClass);
        const classes = [...KNOWN_LAYOUT_CLASSES];
        if (normalizedInitial && !classes.includes(normalizedInitial)) {
          classes.unshift(normalizedInitial);
        }

        for (const className of classes) {
          const option = document.createElement("option");
          option.value = className;
          option.textContent = formatClassLabel(className);
          select.appendChild(option);
        }

        select.value = normalizedInitial || "text";
        return select;
      }

      function applyClassColorToSelect(select, className) {
        const color = colorForClass(className);
        select.style.borderColor = hexToRgba(color, 0.55);
        select.style.color = color;
      }

      function layoutRow(layout) {
        const tr = document.createElement("tr");
        const layoutId = Number(layout.id);
        tr.dataset.layoutId = String(layoutId);
        tr.draggable = true;
        tr.addEventListener("dragstart", (event) => {
          rowDragStart(event, layoutId);
        });
        tr.addEventListener("dragover", (event) => {
          rowDragOver(event, layoutId);
        });
        tr.addEventListener("drop", (event) => {
          rowDrop(event, layoutId);
        });
        tr.addEventListener("dragend", () => {
          resetRowDragState();
        });
        const serverLayout = state.serverLayoutsById[String(layoutId)];
        const serverBaseline = serverLayout ? toDraftShape(serverLayout) : toDraftShape(layout);

        const orderTd = document.createElement("td");
        orderTd.className = "layout-order-col";
        const orderValueBtn = document.createElement("button");
        orderValueBtn.type = "button";
        orderValueBtn.className = "layout-order-value-btn";
        orderValueBtn.textContent = layout.reading_order === null ? "" : String(layout.reading_order);

        const orderEditInput = document.createElement("input");
        orderEditInput.type = "text";
        orderEditInput.inputMode = "numeric";
        orderEditInput.pattern = "[0-9]*";
        orderEditInput.className = "layout-order-edit-input";
        orderEditInput.hidden = true;
        orderEditInput.value = layout.reading_order === null ? "" : String(layout.reading_order);

        function closeOrderEditor({ restore = false } = {}) {
          if (restore) {
            orderEditInput.value = layout.reading_order === null ? "" : String(layout.reading_order);
          }
          orderEditInput.hidden = true;
          orderValueBtn.hidden = false;
        }

        function openOrderEditor() {
          orderEditInput.max = String(Math.max(1, state.layouts.length));
          orderEditInput.value = layout.reading_order === null ? "" : String(layout.reading_order);
          orderValueBtn.hidden = true;
          orderEditInput.hidden = false;
          requestAnimationFrame(() => {
            orderEditInput.focus();
            orderEditInput.select();
          });
        }

        function commitOrderEditorValue() {
          const rawValue = String(orderEditInput.value || "").trim();
          if (!rawValue) {
            closeOrderEditor({ restore: true });
            return;
          }
          const parsed = Number(rawValue);
          if (!Number.isInteger(parsed)) {
            closeOrderEditor({ restore: true });
            return;
          }
          const changed = moveLayoutToOrder(layoutId, parsed);
          if (changed) {
            selectLayout(layoutId, { scrollRowIntoView: true, scrollImageToLayout: true });
            setStatus("Draft saved locally. Order updated.");
            return;
          }
          closeOrderEditor({ restore: true });
        }

        orderValueBtn.addEventListener("click", () => {
          openOrderEditor();
        });
        orderEditInput.addEventListener("focus", () => {
          selectLayout(layoutId, { scrollImageToLayout: true });
        });
        orderEditInput.addEventListener("pointerdown", () => {
          selectLayout(layoutId, { scrollImageToLayout: true });
        });
        orderEditInput.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commitOrderEditorValue();
            return;
          }
          if (event.key === "Escape") {
            event.preventDefault();
            closeOrderEditor({ restore: true });
            return;
          }
        });
        orderEditInput.addEventListener("blur", () => {
          commitOrderEditorValue();
        });
        orderTd.appendChild(orderValueBtn);
        orderTd.appendChild(orderEditInput);
        tr.appendChild(orderTd);

        const classTd = document.createElement("td");
        classTd.className = "layout-class-col layout-class-cell";
        const classInput = buildClassSelect(layout.class_name);
        classInput.classList.add("layout-class-select");
        applyClassColorToSelect(classInput, layout.class_name);
        classInput.addEventListener("focus", () => {
          selectLayout(layoutId, { scrollImageToLayout: true });
        });
        classInput.addEventListener("pointerdown", () => {
          selectLayout(layoutId, { scrollImageToLayout: true });
        });
        classTd.appendChild(classInput);

        if (isCaptionClass(layout.class_name)) {
          const targetIds = captionTargetIds(layoutId);
          if (targetIds.length > 0) {
            const summary = document.createElement("div");
            summary.className = "caption-bind-summary";
            for (const targetId of targetIds) {
              const targetLayout = findLayoutById(targetId);
              const chip = document.createElement("span");
              chip.className = "caption-bind-chip";
              chip.title = "Click to focus target layout";
              chip.addEventListener("pointerdown", (event) => {
                event.stopPropagation();
              });
              chip.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const normalizedTargetId = Number(targetId);
                if (!Number.isInteger(normalizedTargetId) || normalizedTargetId <= 0) {
                  return;
                }
                selectLayout(normalizedTargetId, { scrollRowIntoView: true, scrollImageToLayout: true });
              });

              const chipLabel = document.createElement("span");
              chipLabel.className = "caption-bind-chip-label";
              if (targetLayout) {
                const targetOrder = Number(targetLayout.reading_order);
                const positionLabel =
                  Number.isInteger(targetOrder) && targetOrder > 0 ? String(targetOrder) : "?";
                chipLabel.textContent = `${formatClassLabel(targetLayout.class_name)} ${positionLabel}`;
              } else {
                chipLabel.textContent = "Missing";
              }
              chip.appendChild(chipLabel);

              const removeBtn = document.createElement("button");
              removeBtn.className = "caption-bind-chip-remove";
              removeBtn.type = "button";
              removeBtn.textContent = "×";
              removeBtn.title = "Unbind target";
              removeBtn.setAttribute("aria-label", "Unbind target");
              removeBtn.addEventListener("pointerdown", (event) => {
                event.stopPropagation();
              });
              removeBtn.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                const nextTargets = captionTargetIds(layoutId).filter((value) => value !== Number(targetId));
                if (setCaptionTargetIds(layoutId, nextTargets)) {
                  setStatus("Caption unbound locally.");
                  renderLayouts();
                }
              });
              chip.appendChild(removeBtn);
              summary.appendChild(chip);
            }
            classTd.appendChild(summary);
          }
        }
        tr.appendChild(classTd);

        const bboxSpec = [
          ["x1", "x1"],
          ["y1", "y1"],
          ["x2", "x2"],
          ["y2", "y2"],
        ];
        const bboxFields = bboxSpec.map(([key, labelText]) => {
          const input = document.createElement("input");
          input.type = "number";
          input.min = "0";
          input.max = "1";
          input.step = "0.001";
          input.className = "layout-bbox-input";
          input.value = toFixed(layout.bbox[key]);
          const field = document.createElement("label");
          field.className = "bbox-field";
          const label = document.createElement("span");
          label.className = "bbox-label";
          label.textContent = labelText;
          field.appendChild(label);
          field.appendChild(input);
          return [key, input, field];
        });
        const bboxEditor = document.createElement("div");
        bboxEditor.className = "layout-bbox-editor";
        if (Number(state.expandedBboxLayoutId) === layoutId) {
          bboxEditor.classList.add("is-open");
        }
        for (const [, , field] of bboxFields) {
          bboxEditor.appendChild(field);
        }
        classTd.appendChild(bboxEditor);

        for (const [key, input] of bboxFields) {
          const pointHandle = pointHandleForCoordinateKey(key);
          if (!pointHandle) {
            continue;
          }
          input.addEventListener("focus", () => {
            selectLayout(layoutId, { scrollRowIntoView: true, scrollImageToLayout: true });
            setActivePointHighlight(layoutId, pointHandle);
          });
          input.addEventListener("pointerdown", () => {
            selectLayout(layoutId, { scrollRowIntoView: true, scrollImageToLayout: true });
            setActivePointHighlight(layoutId, pointHandle);
          });
          input.addEventListener("blur", () => {
            clearActivePointHighlight(layoutId, pointHandle);
          });
        }

        function applyDraftToInputs(draft) {
          classInput.value = draft.class_name;
          applyClassColorToSelect(classInput, draft.class_name);
          orderValueBtn.textContent = draft.reading_order === null ? "" : String(draft.reading_order);
          orderEditInput.value = draft.reading_order === null ? "" : String(draft.reading_order);
          closeOrderEditor();
          bboxFields[0][1].value = toFixed(draft.bbox.x1);
          bboxFields[1][1].value = toFixed(draft.bbox.y1);
          bboxFields[2][1].value = toFixed(draft.bbox.x2);
          bboxFields[3][1].value = toFixed(draft.bbox.y2);
        }

        function parseBoundedNumber(rawValue) {
          const value = roundTo4(rawValue);
          if (Number.isNaN(value) || value < 0 || value > 1) {
            throw new Error("BBox values must be between 0 and 1.");
          }
          return value;
        }

        function payloadFromInputs() {
          const className = normalizeClassName(classInput.value) || "text";
          return {
            class_name: className,
            reading_order: Number.isInteger(Number(layout.reading_order))
              ? Number(layout.reading_order)
              : null,
            orientation: normalizeLayoutOrientationValue(layout.orientation),
            bbox: {
              x1: parseBoundedNumber(bboxFields[0][1].value),
              y1: parseBoundedNumber(bboxFields[1][1].value),
              x2: parseBoundedNumber(bboxFields[2][1].value),
              y2: parseBoundedNumber(bboxFields[3][1].value),
            },
          };
        }

        function replaceLayoutInState(updatedLayout) {
          const idx = state.layouts.findIndex((row) => row.id === updatedLayout.id);
          if (idx >= 0) {
            state.layouts[idx] = updatedLayout;
            renderOverlay();
          }
        }

        function applyDraftToState(draft) {
          replaceLayoutInState({
            ...layout,
            id: layoutId,
            class_name: draft.class_name,
            reading_order: draft.reading_order,
            orientation: normalizeLayoutOrientationValue(draft.orientation),
            bbox: { ...draft.bbox },
          });
        }

        function saveLocalDraft() {
          let draft;
          try {
            draft = payloadFromInputs();
          } catch (error) {
            setStatus(`Draft not saved: ${error.message}`, { isError: true });
            return false;
          }

          applyDraftToState(draft);
          if (sameDraft(draft, serverBaseline)) {
            delete state.localEditsById[String(layoutId)];
            state.deletedLayoutIds.delete(layoutId);
            setStatus("Draft cleared (matches original).");
          } else {
            state.localEditsById[String(layoutId)] = draft;
            state.deletedLayoutIds.delete(layoutId);
            setStatus("Draft saved locally.");
          }
          persistLayoutDraftState();
          return true;
        }

        classInput.addEventListener("change", () => {
          applyClassColorToSelect(classInput, classInput.value);
          rememberLastAddedClass(classInput.value);
          if (saveLocalDraft()) {
            renderLayouts();
          }
        });
        for (const [, input] of bboxFields) {
          input.addEventListener("change", () => {
            const parsed = Number(input.value);
            if (!Number.isNaN(parsed)) {
              input.value = toFixed(roundTo4(parsed));
            }
            saveLocalDraft();
          });
        }

        const actionsTd = document.createElement("td");
        actionsTd.className = "layout-actions-col";
        const actionsWrap = document.createElement("div");
        actionsWrap.className = "row-actions";

        const showBboxBtn = document.createElement("button");
        showBboxBtn.className = "secondary icon-btn layout-show-bbox-btn";
        showBboxBtn.type = "button";
        showBboxBtn.title = "Toggle bbox values";
        showBboxBtn.setAttribute("aria-label", "Toggle bbox values");
        showBboxBtn.textContent = "□";
        showBboxBtn.addEventListener("click", () => {
          const shouldExpand = Number(state.expandedBboxLayoutId) !== layoutId;
          state.expandedBboxLayoutId = shouldExpand ? layoutId : null;

          if (!shouldExpand) {
            const activeEl = document.activeElement;
            if (activeEl instanceof HTMLElement && activeEl.classList.contains("layout-bbox-input")) {
              activeEl.blur();
            }
            state.activePointHighlight = null;
            applyActivePointHighlightStyles();
            renderLayouts();
            return;
          }

          renderLayouts();
          selectLayout(layoutId, { scrollRowIntoView: true, scrollImageToLayout: true });
          requestAnimationFrame(() => {
            const row = layoutsBody.querySelector(`tr[data-layout-id="${layoutId}"]`);
            const firstBboxInput = row?.querySelector(".layout-bbox-editor.is-open .layout-bbox-input");
            if (!(firstBboxInput instanceof HTMLInputElement)) {
              return;
            }
            firstBboxInput.focus();
            firstBboxInput.select();
          });
        });
        actionsWrap.appendChild(showBboxBtn);

        const restoreBtn = document.createElement("button");
        restoreBtn.className = "secondary icon-btn";
        restoreBtn.type = "button";
        restoreBtn.title = "Restore values";
        restoreBtn.setAttribute("aria-label", "Restore values");
        restoreBtn.textContent = "↺";
        restoreBtn.addEventListener("click", () => {
          applyDraftToInputs(serverBaseline);
          applyDraftToState(serverBaseline);
          delete state.localEditsById[String(layoutId)];
          state.deletedLayoutIds.delete(layoutId);
          state.captionBindingsByCaptionId[String(layoutId)] = normalizeLayoutIdList(
            state.serverCaptionBindingsByCaptionId[String(layoutId)],
          );
          persistLayoutDraftState();
          renderLayouts();
          setStatus("Layout values restored.");
        });
        actionsWrap.appendChild(restoreBtn);

        const deleteBtn = document.createElement("button");
        deleteBtn.className = "danger icon-btn";
        deleteBtn.type = "button";
        deleteBtn.title = "Delete layout";
        deleteBtn.setAttribute("aria-label", "Delete layout");
        deleteBtn.textContent = "🗑";
        deleteBtn.addEventListener("click", () => {
          if (!markLayoutDeleted(layoutId)) {
            return;
          }
          setStatus("Layout marked for deletion. It will be deleted after review.");
        });
        actionsWrap.appendChild(deleteBtn);

        actionsTd.appendChild(actionsWrap);
        tr.appendChild(actionsTd);
        return tr;
      }

      function renderLayouts() {
        sortLayoutsInPlace();
        sanitizeCaptionBindingsInPlace();
        clearSelectedLayoutIfMissing();
        clearActivePointHighlightIfMissing();
        clearExpandedBboxIfMissing();
        layoutsBody.innerHTML = "";
        for (const layout of state.layouts) {
          layoutsBody.appendChild(layoutRow(layout));
        }
        renderOverlay();
        applySelectedLayoutStyles();
      }

      async function loadPage() {
        const payload = await fetchPageDetails(pageId);
        state.page = payload.page;
        pageMeta.textContent = `Page #${state.page.id} | ${state.page.rel_path}`;
        updateReviewUiState();
        pageImage.src = payload.image_url;
      }

      async function loadLayouts() {
        const payload = await fetchPageLayouts(pageId);
        const merged = mergeLayoutsForReview({
          layouts: payload.layouts,
          localEditsById: state.localEditsById,
          deletedLayoutIds: Array.from(state.deletedLayoutIds),
        });
        state.serverLayoutsById = merged.serverLayoutsById;
        state.serverCaptionBindingsByCaptionId = {};
        for (const layout of payload.layouts) {
          if (isCaptionClass(layout.class_name)) {
            state.serverCaptionBindingsByCaptionId[String(layout.id)] = normalizeLayoutIdList(
              layout.bound_target_ids,
            );
          }
        }

        for (const key of Object.keys(state.localEditsById)) {
          if (!(key in state.serverLayoutsById)) {
            delete state.localEditsById[key];
          }
        }
        for (const layoutId of Array.from(state.deletedLayoutIds)) {
          if (!(String(layoutId) in state.serverLayoutsById)) {
            state.deletedLayoutIds.delete(layoutId);
          }
        }

        state.layouts = merged.mergedLayouts;
        state.layoutsLoaded = true;
        if (!hasContiguousUniqueReadingOrders(state.layouts)) {
          applySequentialReadingOrder(layoutIdsInCurrentOrder());
          return;
        }
        persistLayoutDraftState();
        renderLayouts();
      }

      async function setPageLayoutOrderMode(nextModeRaw) {
        const nextMode = normalizeLayoutOrderMode(nextModeRaw, { fallback: "auto" });
        if (!state.page) {
          return;
        }
        const draftResolution = reorderDraftResolutionSummary();
        if (!draftResolution.canReorder) {
          setStatus(draftResolution.message, { isError: true });
          updateLayoutOrderControls();
          return;
        }
        const currentMode = currentLayoutOrderMode();
        if (nextMode === currentMode) {
          updateLayoutOrderControls();
          return;
        }
        state.layoutOrderModeUpdateInProgress = true;
        updateReviewUiState();
        try {
          const payload = await updateLayoutOrderMode(pageId, { mode: nextMode });
          const appliedMode = normalizeLayoutOrderMode(payload?.layout_order_mode, { fallback: nextMode });
          state.page.layout_order_mode = appliedMode;
          await recomputeReadingOrder({ modeOverride: appliedMode });
        } catch (error) {
          setStatus(`Ordering mode update failed: ${error.message}`, { isError: true });
        } finally {
          state.layoutOrderModeUpdateInProgress = false;
          updateReviewUiState();
        }
      }

      async function recomputeReadingOrder({ modeOverride = null } = {}) {
        if (!state.page || state.layoutReorderInProgress) {
          return;
        }
        const draftResolution = reorderDraftResolutionSummary();
        if (!draftResolution.canReorder) {
          setStatus(draftResolution.message, { isError: true });
          return;
        }
        if (draftResolution.readingOrderOnlyLayoutIds.length > 0) {
          for (const layoutId of draftResolution.readingOrderOnlyLayoutIds) {
            delete state.localEditsById[String(layoutId)];
          }
          persistLayoutDraftState();
        }

        const mode = normalizeLayoutOrderMode(
          modeOverride === null ? currentLayoutOrderMode() : modeOverride,
          { fallback: "auto" },
        );

        state.layoutReorderInProgress = true;
        updateReviewUiState();
        try {
          const payload = await reorderPageLayouts(pageId, { mode });
          if (state.page) {
            state.page.layout_order_mode = normalizeLayoutOrderMode(payload?.layout_order_mode, { fallback: mode });
          }
          await loadLayouts();
          const changed = Boolean(payload?.changed);
          setStatus(changed ? "Reading order recomputed." : "Reading order already matches selected mode.");
        } catch (error) {
          setStatus(`Reorder failed: ${error.message}`, { isError: true });
        } finally {
          state.layoutReorderInProgress = false;
          updateReviewUiState();
        }
      }

      async function refreshNextReviewButton() {
        try {
          const payload = await fetchNextLayoutReviewPage(pageId);
          const nextUrl = nextLayoutReviewUrl(payload);
          const candidate = nextUrl ? Number(payload.next_page_id) : null;
          state.nextReviewPageId =
            Number.isInteger(candidate) && candidate > 0 && candidate !== pageId ? candidate : null;
        } catch {
          state.nextReviewPageId = null;
        }
        updateHistoryNavButtons();
      }

      function setDetectModalModelOptions(availableModels, selectedModel) {
        const models = Array.isArray(availableModels) ? availableModels : [];
        const fallbackModel = "yolo26m-doclaynet.pt";
        const resolvedSelectedModel =
          typeof selectedModel === "string" && selectedModel.trim().length > 0
            ? selectedModel.trim()
            : fallbackModel;
        const modelSet = new Set();
        for (const model of models) {
          const normalized = String(model || "").trim();
          if (!normalized) {
            continue;
          }
          modelSet.add(normalized);
        }
        modelSet.add(resolvedSelectedModel);
        detectModalModelInput.innerHTML = "";
        for (const model of Array.from(modelSet.values())) {
          const option = document.createElement("option");
          option.value = model;
          option.textContent = model;
          detectModalModelInput.appendChild(option);
        }
        detectModalModelInput.value = resolvedSelectedModel;
      }

      function normalizeTopConfigRows(rows) {
        const inputRows = Array.isArray(rows) ? rows : [];
        const normalized = [];
        const seen = new Set();
        for (const row of inputRows) {
          if (!row || typeof row !== "object") {
            continue;
          }
          const modelCheckpoint = String(row.model_checkpoint || "").trim();
          const imageSize = Number(row.image_size);
          const meanScore = Number(row.mean_score);
          if (!modelCheckpoint || !Number.isInteger(imageSize) || imageSize < 32) {
            continue;
          }
          const dedupeKey = `${modelCheckpoint}|${imageSize}`;
          if (seen.has(dedupeKey)) {
            continue;
          }
          seen.add(dedupeKey);
          normalized.push({
            model_checkpoint: modelCheckpoint,
            image_size: imageSize,
            mean_score: Number.isFinite(meanScore) ? meanScore : 0,
          });
        }
        normalized.sort((left, right) => Number(right.mean_score) - Number(left.mean_score));
        return normalized.slice(0, 3);
      }

      function applySelectedTopConfig(optionValue) {
        const selectedIndex = Number(optionValue);
        if (!Number.isInteger(selectedIndex) || selectedIndex < 0) {
          return;
        }
        const selected = state.detectTopConfigs[selectedIndex];
        if (!selected || typeof selected !== "object") {
          return;
        }

        const modelCheckpoint = String(selected.model_checkpoint || "").trim();
        const imageSize = Number(selected.image_size);
        if (modelCheckpoint) {
          let optionFound = false;
          for (const option of detectModalModelInput.options) {
            if (String(option.value) === modelCheckpoint) {
              optionFound = true;
              break;
            }
          }
          if (!optionFound) {
            const option = document.createElement("option");
            option.value = modelCheckpoint;
            option.textContent = modelCheckpoint;
            detectModalModelInput.appendChild(option);
          }
          detectModalModelInput.value = modelCheckpoint;
        }
        if (Number.isInteger(imageSize) && imageSize >= 32) {
          detectModalImgszInput.value = String(imageSize);
        }
      }

      function setDetectModalTopConfigOptions(topConfigs) {
        state.detectTopConfigs = normalizeTopConfigRows(topConfigs);
        detectModalTopConfigInput.innerHTML = "";
        if (state.detectTopConfigs.length === 0) {
          const option = document.createElement("option");
          option.value = "";
          option.textContent = "No benchmark configs yet";
          detectModalTopConfigInput.appendChild(option);
          detectModalTopConfigInput.disabled = true;
          return;
        }

        state.detectTopConfigs.forEach((configRow, index) => {
          const option = document.createElement("option");
          option.value = String(index);
          option.textContent =
            `#${index + 1} ${configRow.model_checkpoint} imgsz=${configRow.image_size} ` +
            `score=${Number(configRow.mean_score).toFixed(4)}`;
          detectModalTopConfigInput.appendChild(option);
        });
        detectModalTopConfigInput.disabled = false;
        detectModalTopConfigInput.value = "0";
        applySelectedTopConfig("0");
      }

      async function ensureDetectModalDefaultsLoaded() {
        if (state.detectDefaultsLoaded) {
          return;
        }
        const defaultsPayload = await fetchLayoutDetectionDefaults();
        const defaults =
          defaultsPayload && typeof defaultsPayload.defaults === "object"
            ? defaultsPayload.defaults
            : {};
        let topConfigs = normalizeTopConfigRows(defaultsPayload?.top_configs);
        if (topConfigs.length === 0) {
          try {
            const benchmarkPayload = await fetchLayoutBenchmarkGrid();
            topConfigs = normalizeTopConfigRows(benchmarkPayload?.rows);
          } catch {
            topConfigs = [];
          }
        }
        const availableModels = Array.isArray(defaultsPayload?.available_models)
          ? defaultsPayload.available_models
          : [];
        const suggestedModels = topConfigs.map((row) => row.model_checkpoint);
        setDetectModalModelOptions([...availableModels, ...suggestedModels], defaults.model_checkpoint);
        detectModalConfInput.value = String(AGREED_DETECT_DEFAULT_CONF);
        detectModalIouInput.value = String(AGREED_DETECT_DEFAULT_IOU);
        detectModalImgszInput.value = String(Number(defaults.image_size ?? 1024));
        setDetectModalTopConfigOptions(topConfigs);
        state.detectDefaultsLoaded = true;
      }

      function setDetectModalBusy(busy) {
        const inProgress = Boolean(busy);
        state.detectInProgress = inProgress;
        detectBtn.disabled = inProgress;
        detectModalRunBtn.disabled = inProgress;
        detectModalRunBtn.classList.toggle("is-busy", inProgress);
        detectModalCancelBtn.disabled = inProgress;
        detectModalTopConfigInput.disabled = inProgress || state.detectTopConfigs.length === 0;
        detectModalModelInput.disabled = inProgress;
        detectModalConfInput.disabled = inProgress;
        detectModalIouInput.disabled = inProgress;
        detectModalImgszInput.disabled = inProgress;
        detectModalMaxDetInput.disabled = inProgress;
        detectModalReplaceExistingInput.disabled = inProgress;
        detectModalAgnosticNmsInput.disabled = inProgress;
        for (const button of detectModalHelpButtons) {
          button.disabled = inProgress;
        }
        if (inProgress) {
          hideDetectModalHelp();
        }
      }

      function hideDetectModalHelp() {
        state.activeDetectHelpKey = null;
        if (detectModalHelpCloud instanceof HTMLElement) {
          detectModalHelpCloud.hidden = true;
          detectModalHelpCloud.classList.remove("up");
        }
        for (const button of detectModalHelpButtons) {
          button.classList.remove("active");
        }
      }

      function showDetectModalHelp(helpKeyRaw, anchorButton) {
        const helpKey = String(helpKeyRaw || "").trim();
        const helpText = DETECT_HELP_TEXT_BY_KEY[helpKey];
        if (!helpText || !(anchorButton instanceof HTMLElement)) {
          return;
        }
        if (!(detectModalHelpCloud instanceof HTMLElement) || !(detectModalCard instanceof HTMLElement)) {
          return;
        }
        for (const button of detectModalHelpButtons) {
          button.classList.toggle("active", false);
        }
        state.activeDetectHelpKey = helpKey;
        detectModalHelpCloud.textContent = helpText;
        detectModalHelpCloud.hidden = false;

        for (const button of detectModalHelpButtons) {
          const key = String(button.dataset.helpKey || "");
          button.classList.toggle("active", key === helpKey);
        }

        const cardRect = detectModalCard.getBoundingClientRect();
        const anchorRect = anchorButton.getBoundingClientRect();
        const cloudWidth = detectModalHelpCloud.offsetWidth || 220;
        const cloudHeight = detectModalHelpCloud.offsetHeight || 44;
        const horizontalPadding = 8;
        const verticalGap = 8;

        let left = anchorRect.left - cardRect.left + (anchorRect.width / 2) - (cloudWidth / 2);
        left = Math.max(horizontalPadding, Math.min(left, cardRect.width - cloudWidth - horizontalPadding));

        let top = anchorRect.bottom - cardRect.top + verticalGap;
        let up = false;
        if (top + cloudHeight > cardRect.height - horizontalPadding) {
          top = anchorRect.top - cardRect.top - cloudHeight - verticalGap;
          up = true;
        }
        top = Math.max(horizontalPadding, top);
        detectModalHelpCloud.style.left = `${Math.round(left)}px`;
        detectModalHelpCloud.style.top = `${Math.round(top)}px`;
        detectModalHelpCloud.classList.toggle("up", up);
      }

      function toggleDetectModalHelp(helpKeyRaw, anchorButton) {
        const helpKey = String(helpKeyRaw || "").trim();
        if (!helpKey) {
          hideDetectModalHelp();
          return;
        }
        if (state.activeDetectHelpKey === helpKey) {
          hideDetectModalHelp();
          return;
        }
        showDetectModalHelp(helpKey, anchorButton);
      }

      async function openDetectModal() {
        if (state.detectInProgress) {
          return;
        }
        openModal(detectModal, { onOpen: hideDetectModalHelp });
        try {
          await ensureDetectModalDefaultsLoaded();
        } catch (error) {
          setStatus(`Detection defaults failed: ${error.message}`, { isError: true });
        }
      }

      function closeDetectModal() {
        closeModal(detectModal, {
          isBusy: () => state.detectInProgress,
          onClose: hideDetectModalHelp,
        });
      }

      function parseDetectModalPayload() {
        const modelCheckpoint = String(detectModalModelInput.value || "").trim();
        const confidence = Number(detectModalConfInput.value);
        const iou = Number(detectModalIouInput.value);
        const imageSize = Number(detectModalImgszInput.value);
        const maxDetections = Number(detectModalMaxDetInput.value);
        if (!modelCheckpoint) {
          throw new Error("Model checkpoint must be selected.");
        }
        if (Number.isNaN(confidence) || confidence < 0 || confidence > 1) {
          throw new Error("Confidence (`conf`) must be between 0 and 1.");
        }
        if (Number.isNaN(iou) || iou < 0 || iou > 1) {
          throw new Error("IoU (`iou`) must be between 0 and 1.");
        }
        if (!Number.isInteger(imageSize) || imageSize < DETECT_MIN_IMGSZ || imageSize > DETECT_MAX_IMGSZ) {
          throw new Error(
            `Image size (\`imgsz\`) must be an integer between ${DETECT_MIN_IMGSZ} and ${DETECT_MAX_IMGSZ}.`,
          );
        }
        if (
          !Number.isInteger(maxDetections) ||
          maxDetections < DETECT_MIN_MAX_DET ||
          maxDetections > DETECT_MAX_MAX_DET
        ) {
          throw new Error(
            `Max detections (\`max_det\`) must be an integer between ${DETECT_MIN_MAX_DET} and ${DETECT_MAX_MAX_DET}.`,
          );
        }
        return {
          model_checkpoint: modelCheckpoint,
          replace_existing: detectModalReplaceExistingInput.checked,
          confidence_threshold: confidence,
          iou_threshold: iou,
          image_size: imageSize,
          max_detections: maxDetections,
          agnostic_nms: detectModalAgnosticNmsInput.checked,
        };
      }

      async function detectLayouts(payloadBody) {
        if (state.detectInProgress) {
          return;
        }
        setDetectModalBusy(true);
        let shouldCloseModal = false;
        try {
          const payload = await detectPageLayouts(pageId, payloadBody);
          clearLayoutDraftState();
          shouldCloseModal = true;
          const params = payload.inference_params || {};
          setStatus(
            `Detection finished. Created ${payload.created} layouts. model=${payload.detector || "default"}, conf=${params.confidence_threshold}, iou=${params.iou_threshold}, imgsz=${params.image_size}, max_det=${params.max_detections}, agnostic_nms=${params.agnostic_nms}.`,
          );
          await loadPage();
          await loadLayouts();
          await refreshNextReviewButton();
        } catch (error) {
          setStatus(`Detection failed: ${error.message}`, { isError: true });
        } finally {
          setDetectModalBusy(false);
          if (shouldCloseModal) {
            closeDetectModal();
          }
        }
      }

      function setDrawModeActive(active) {
        state.drawModeActive = active;
        drawLayer.hidden = !active;
        drawLayer.classList.toggle("active", active);
        addBtn.classList.toggle("active", active);
        addBtn.setAttribute("aria-pressed", active ? "true" : "false");
      }

      function clearDrawPreview() {
        state.drawPreviewBBox = null;
        drawPreviewBox.hidden = true;
        imageMagnifier.refresh();
      }

      function resetDrawInteraction() {
        state.drawPointerId = null;
        state.drawStartPoint = null;
        clearDrawPreview();
      }

      function exitDrawMode() {
        resetDrawInteraction();
        setDrawModeActive(false);
      }

      function enterDrawMode() {
        if (addBtn.disabled) {
          return;
        }
        setDrawModeActive(true);
      }

      function toggleDrawMode() {
        if (state.drawModeActive) {
          exitDrawMode();
        } else {
          enterDrawMode();
        }
      }

      function drawLayerPointFromEvent(event) {
        const rect = drawLayer.getBoundingClientRect();
        if (!rect.width || !rect.height) {
          return null;
        }
        const x = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
        const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
        return {
          x,
          y,
          width: rect.width,
          height: rect.height,
        };
      }

      function renderDrawPreview(startPoint, endPoint) {
        const left = Math.min(startPoint.x, endPoint.x);
        const top = Math.min(startPoint.y, endPoint.y);
        const width = Math.abs(endPoint.x - startPoint.x);
        const height = Math.abs(endPoint.y - startPoint.y);
        drawPreviewBox.style.left = `${left}px`;
        drawPreviewBox.style.top = `${top}px`;
        drawPreviewBox.style.width = `${width}px`;
        drawPreviewBox.style.height = `${height}px`;
        drawPreviewBox.hidden = false;
        if (startPoint.width > 0 && startPoint.height > 0) {
          const x1 = roundTo4(clamp(left / startPoint.width, 0, 1));
          const y1 = roundTo4(clamp(top / startPoint.height, 0, 1));
          const x2 = roundTo4(clamp((left + width) / startPoint.width, 0, 1));
          const y2 = roundTo4(clamp((top + height) / startPoint.height, 0, 1));
          if (x2 > x1 && y2 > y1) {
            state.drawPreviewBBox = { x1, y1, x2, y2 };
          } else {
            state.drawPreviewBBox = null;
          }
        } else {
          state.drawPreviewBBox = null;
        }
        imageMagnifier.refresh();
      }

      async function createLayoutFromBBox(bbox) {
        addBtn.disabled = true;
        try {
          const orderingMode = currentLayoutOrderMode();
          const className = normalizeClassName(state.lastAddedClass) || "text";
          const inferredReadingOrder = nextManualReadingOrder(state.layouts);
          const payload = await createPageLayout(pageId, {
            class_name: className,
            bbox,
            reading_order: inferredReadingOrder,
          });
          const insertedOrder = Number(payload?.layout?.reading_order);
          const draftInsertedOrder = Number.isInteger(inferredReadingOrder)
            ? inferredReadingOrder
            : Number.isInteger(insertedOrder)
              ? insertedOrder
              : null;
          state.localEditsById = shiftDraftReadingOrdersAfterInsertion({
            layouts: state.layouts,
            localEditsById: state.localEditsById,
            insertedOrder: draftInsertedOrder,
          });
          persistLayoutDraftState();
          rememberLastAddedClass(className);
          setStatus(`Manual layout added at order ${inferredReadingOrder} (${orderingMode} mode).`);
          await loadPage();
          await loadLayouts();
          await refreshNextReviewButton();
          const createdLayoutId = Number(payload?.layout?.id);
          if (Number.isInteger(createdLayoutId) && createdLayoutId > 0) {
            selectLayout(createdLayoutId, { scrollRowIntoView: true, scrollImageToLayout: true });
          }
        } catch (error) {
          setStatus(`Add failed: ${error.message}`, { isError: true });
        } finally {
          addBtn.disabled = false;
        }
      }

      function buildCaptionBindingsRequestPayload() {
        sanitizeCaptionBindingsInPlace();
        const unboundCaptionIds = findUnboundCaptionIds();
        if (unboundCaptionIds.length > 0) {
          const unboundCaptionOrderLabels = state.layouts
            .filter((layout) => unboundCaptionIds.includes(Number(layout.id)))
            .map((layout) => `#${Number(layout.reading_order || 0) || "?"}`)
            .join(", ");
          const focusCaptionId = Number(unboundCaptionIds[0]);
          if (Number.isInteger(focusCaptionId) && focusCaptionId > 0) {
            selectLayout(focusCaptionId, { scrollRowIntoView: true, scrollImageToLayout: true });
          }
          throw new Error(
            `Bind required for caption ${unboundCaptionOrderLabels || "(unknown)"} before review.`,
          );
        }
        const bindings = state.layouts
          .filter((layout) => isCaptionClass(layout.class_name))
          .map((layout) => {
            const captionLayoutId = Number(layout.id);
            const targetLayoutIds = normalizeLayoutIdList(
              state.captionBindingsByCaptionId[String(captionLayoutId)],
            );
            return {
              caption_layout_id: captionLayoutId,
              target_layout_ids: targetLayoutIds,
            };
          });
        return { bindings };
      }

      async function markReviewed() {
        const runSubmitOnce = async () => {
          let staleLayoutRefFound = false;
          const deletedIds = Array.from(state.deletedLayoutIds).sort((a, b) => a - b);
          const editedEntries = Object.entries(state.localEditsById).sort(
            ([a], [b]) => Number(a) - Number(b),
          );

          for (const layoutId of deletedIds) {
            try {
              await deleteLayout(layoutId);
            } catch (error) {
              if (!isLayoutNotFoundErrorMessage(error?.message)) {
                throw error;
              }
              staleLayoutRefFound = true;
              state.deletedLayoutIds.delete(Number(layoutId));
              delete state.localEditsById[String(layoutId)];
              delete state.captionBindingsByCaptionId[String(layoutId)];
              for (const [captionId, targetIds] of Object.entries(state.captionBindingsByCaptionId)) {
                state.captionBindingsByCaptionId[captionId] = normalizeLayoutIdList(targetIds).filter(
                  (targetId) => targetId !== Number(layoutId),
                );
              }
            }
          }

          for (const [layoutId, draft] of editedEntries) {
            if (state.deletedLayoutIds.has(Number(layoutId))) {
              continue;
            }
            try {
              await patchLayout(layoutId, draft);
            } catch (error) {
              if (!isLayoutNotFoundErrorMessage(error?.message)) {
                throw error;
              }
              staleLayoutRefFound = true;
              delete state.localEditsById[String(layoutId)];
              state.deletedLayoutIds.delete(Number(layoutId));
            }
          }

          if (staleLayoutRefFound) {
            persistLayoutDraftState();
            await loadLayouts();
          }

          const captionBindingsPayload = buildCaptionBindingsRequestPayload();
          await putCaptionBindings(pageId, captionBindingsPayload);

          const payload = await completeLayoutReview(pageId);
          if (state.page && payload && typeof payload.status === "string") {
            state.page.status = payload.status;
            updateReviewUiState();
          }
          clearLayoutDraftState();

          const nextPayload = await fetchNextLayoutReviewPage(pageId);
          const nextUrl = nextLayoutReviewUrl(nextPayload);
          if (nextUrl) {
            window.location.href = nextUrl;
            return;
          }

          setStatus(
            `Page marked reviewed with ${payload.layout_count} layouts. No more pages are waiting for layout review.`,
          );
          await loadPage();
          await loadLayouts();
          await refreshNextReviewButton();
        };

        state.reviewSubmitInProgress = true;
        updateReviewUiState();
        try {
          await loadLayouts();
          try {
            await runSubmitOnce();
          } catch (error) {
            if (!isLayoutNotFoundErrorMessage(error?.message)) {
              throw error;
            }
            await loadLayouts();
            await runSubmitOnce();
          }
        } catch (error) {
          setStatus(`Mark reviewed failed: ${error.message}`, { isError: true });
        } finally {
          state.reviewSubmitInProgress = false;
          updateReviewUiState();
        }
      }

      drawLayer.addEventListener("pointermove", (event) => {
        updateCursorGuidesFromPointerEvent(event);
        if (!state.drawModeActive) {
          return;
        }
        const point = drawLayerPointFromEvent(event);
        if (
          state.drawPointerId !== null &&
          state.drawPointerId === event.pointerId &&
          state.drawStartPoint &&
          point
        ) {
          renderDrawPreview(state.drawStartPoint, point);
        }
      });

      drawLayer.addEventListener("pointerdown", (event) => {
        if (!state.drawModeActive || event.button !== 0) {
          return;
        }
        const point = drawLayerPointFromEvent(event);
        if (!point) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        state.drawPointerId = event.pointerId;
        state.drawStartPoint = point;
        drawLayer.setPointerCapture?.(event.pointerId);
        renderDrawPreview(point, point);
      });

      drawLayer.addEventListener("pointerup", async (event) => {
        if (!state.drawModeActive || state.drawPointerId !== event.pointerId) {
          return;
        }
        const startPoint = state.drawStartPoint;
        const endPoint = drawLayerPointFromEvent(event);
        drawLayer.releasePointerCapture?.(event.pointerId);
        resetDrawInteraction();
        if (!startPoint || !endPoint) {
          exitDrawMode();
          return;
        }

        const rawBBox = computeDraggedBBox({
          startX: startPoint.x,
          startY: startPoint.y,
          endX: endPoint.x,
          endY: endPoint.y,
          contentWidth: startPoint.width,
          contentHeight: startPoint.height,
          minPixels: 8,
        });
        if (!rawBBox) {
          setStatus("Draw a larger box to create a layout.");
          return;
        }

        exitDrawMode();
        await createLayoutFromBBox({
          x1: roundTo4(rawBBox.x1),
          y1: roundTo4(rawBBox.y1),
          x2: roundTo4(rawBBox.x2),
          y2: roundTo4(rawBBox.y2),
        });
      });

      drawLayer.addEventListener("pointercancel", (event) => {
        if (state.drawPointerId !== event.pointerId) {
          return;
        }
        drawLayer.releasePointerCapture?.(event.pointerId);
        resetDrawInteraction();
      });
      imageViewport.addEventListener("pointermove", (event) => {
        updateCursorGuidesFromPointerEvent(event);
      });
      imageViewport.addEventListener("pointerleave", () => {
        hideCursorGuides();
      });
      imageViewport.addEventListener(
        "scroll",
        () => {
          hideCursorGuides();
        },
        { passive: true },
      );

      detectBtn.addEventListener("click", async () => {
        if (state.drawModeActive) {
          exitDrawMode();
        }
        if (state.activeBindingCaptionId !== null) {
          setActiveBindingCaption(null);
        }
        await openDetectModal();
      });
      addBtn.addEventListener("click", () => {
        if (state.activeBindingCaptionId !== null) {
          setActiveBindingCaption(null);
        }
        toggleDrawMode();
      });
      reviewBtn.addEventListener("click", markReviewed);
      layoutOrderModeInput?.addEventListener("change", async () => {
        await setPageLayoutOrderMode(layoutOrderModeInput.value);
      });
      historyBackBtn.addEventListener("click", () => {
        const targetPageId = previousHistoryPageId(state.reviewHistory, state.reviewHistoryIndex);
        if (!Number.isInteger(targetPageId) || targetPageId <= 0) {
          return;
        }
        state.reviewHistoryIndex = Math.max(0, state.reviewHistoryIndex - 1);
        persistReviewHistory();
        window.location.href = `/static/layouts.html?page_id=${targetPageId}`;
      });
      historyForthBtn.addEventListener("click", () => {
        const forwardTarget = nextHistoryPageId(state.reviewHistory, state.reviewHistoryIndex);
        if (Number.isInteger(forwardTarget) && forwardTarget > 0) {
          state.reviewHistoryIndex = Math.min(
            state.reviewHistory.length - 1,
            Math.max(0, state.reviewHistoryIndex + 1),
          );
          persistReviewHistory();
          window.location.href = `/static/layouts.html?page_id=${forwardTarget}`;
          return;
        }

        const nextPageId = Number(state.nextReviewPageId);
        if (!Number.isInteger(nextPageId) || nextPageId <= 0) {
          return;
        }
        window.location.href = `/static/layouts.html?page_id=${nextPageId}`;
      });
      detectModalRunBtn.addEventListener("click", async () => {
        if (state.detectInProgress) {
          return;
        }
        let payloadBody;
        try {
          payloadBody = parseDetectModalPayload();
        } catch (error) {
          setStatus(`Detection failed: ${error.message}`, { isError: true });
          return;
        }
        await detectLayouts(payloadBody);
      });
      detectModalCancelBtn.addEventListener("click", () => {
        if (state.detectInProgress) {
          return;
        }
        closeDetectModal();
      });
      detectModalTopConfigInput.addEventListener("change", () => {
        if (state.detectInProgress) {
          return;
        }
        applySelectedTopConfig(detectModalTopConfigInput.value);
      });
      for (const helpButton of detectModalHelpButtons) {
        helpButton.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (state.detectInProgress) {
            return;
          }
          toggleDetectModalHelp(helpButton.dataset.helpKey, helpButton);
        });
      }
      detectModal.addEventListener("pointerdown", (event) => {
        const target = event.target;
        if (target instanceof Element) {
          if (!target.closest(".field-help-btn") && !target.closest("#detect-modal-help-cloud")) {
            hideDetectModalHelp();
          }
        }
        if (shouldCloseOnBackdropPointerDown(event, detectModal) && !state.detectInProgress) {
          closeDetectModal();
        }
      });
      function selectLayoutFromPanelEventTarget(target) {
        if (!(target instanceof Element)) {
          clearSelectedLayout();
          return;
        }
        const row = target.closest("tr[data-layout-id]");
        if (!row) {
          clearSelectedLayout();
          return;
        }
        const layoutId = Number(row.dataset.layoutId);
        if (!Number.isInteger(layoutId) || layoutId <= 0) {
          clearSelectedLayout();
          return;
        }
        selectLayout(layoutId, { scrollImageToLayout: true });
      }

      layoutsBody.addEventListener("click", (event) => {
        selectLayoutFromPanelEventTarget(event.target);
      });
      layoutsBody.addEventListener("pointerdown", (event) => {
        selectLayoutFromPanelEventTarget(event.target);
      });
      layoutsBody.addEventListener("focusin", (event) => {
        selectLayoutFromPanelEventTarget(event.target);
      });
      overlay.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) {
          return;
        }
        if (event.target === overlay) {
          clearSelectedLayout();
        }
      });
      layoutsBody.addEventListener("dragover", (event) => {
        const draggingLayoutId = Number(state.draggingLayoutId);
        if (!Number.isInteger(draggingLayoutId) || draggingLayoutId <= 0) {
          return;
        }
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        const row = target.closest("tr[data-layout-id]");
        if (row) {
          return;
        }
        event.preventDefault();
        clearRowDragUi();
        const draggingRow = layoutsBody.querySelector(`tr[data-layout-id="${draggingLayoutId}"]`);
        draggingRow?.classList.add("layout-dragging");
        state.dragOverLayoutId = null;
        if (event.dataTransfer) {
          event.dataTransfer.dropEffect = "move";
        }
      });
      layoutsBody.addEventListener("drop", (event) => {
        const draggingLayoutId = Number(state.draggingLayoutId);
        if (!Number.isInteger(draggingLayoutId) || draggingLayoutId <= 0) {
          return;
        }
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        const row = target.closest("tr[data-layout-id]");
        if (row) {
          return;
        }
        event.preventDefault();
        finishRowReorder(null);
      });
      zoomTrigger.addEventListener("click", () => {
        if (zoomMenu.hidden) {
          openZoomMenu();
        } else {
          closeZoomMenu();
        }
      });
      zoomMenu.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        const option = target.closest(".zoom-option");
        if (!(option instanceof HTMLButtonElement)) {
          return;
        }
        const mode = option.dataset.zoomMode;
        const percent = option.dataset.zoomPercent;
        if (mode) {
          setZoomMode(mode);
        } else if (percent) {
          setCustomZoomPercent(Number(percent));
        }
        closeZoomMenu();
      });
      zoomPercentInput.addEventListener("change", () => {
        applyCustomZoomFromInput();
      });
      zoomPercentInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          applyCustomZoomFromInput();
          zoomPercentInput.blur();
        }
      });
      document.addEventListener("pointerdown", (event) => {
        if (!(event.target instanceof Element)) {
          return;
        }
        if (event.target.closest(".zoom-control")) {
          return;
        }
        closeZoomMenu();
      });
      document.addEventListener("keydown", (event) => {
        const key = String(event.key || "").toLowerCase();
        if (key === "alt") {
          imageMagnifier.setTemporary(true);
          return;
        }
        if (
          key === "m" &&
          !event.repeat &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          !isInteractiveShortcutTarget(event.target)
        ) {
          event.preventDefault();
          toggleMagnifier();
          return;
        }
        if (
          event.key === "Insert" &&
          !event.repeat &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          detectModal.hidden &&
          !isInteractiveShortcutTarget(event.target)
        ) {
          event.preventDefault();
          if (state.activeBindingCaptionId !== null) {
            setActiveBindingCaption(null);
          }
          toggleDrawMode();
          return;
        }
        if (
          event.key === "Delete" &&
          !event.repeat &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          detectModal.hidden &&
          !state.drawModeActive &&
          !isInteractiveShortcutTarget(event.target)
        ) {
          const selectedLayoutId = Number(state.selectedLayoutId);
          if (!Number.isInteger(selectedLayoutId) || selectedLayoutId <= 0) {
            return;
          }
          const deleted = markLayoutDeleted(selectedLayoutId);
          if (deleted) {
            event.preventDefault();
            setStatus("Layout marked for deletion. It will be deleted after review.");
          }
          return;
        }
        if (event.key === "Escape") {
          closeZoomMenu();
          if (!state.detectInProgress) {
            closeDetectModal();
          }
          if (state.drawModeActive) {
            exitDrawMode();
          }
          if (state.activeBindingCaptionId !== null) {
            setActiveBindingCaption(null);
          }
          clearSelectedLayout();
        }
      });
      document.addEventListener("keyup", (event) => {
        if (String(event.key || "").toLowerCase() === "alt") {
          imageMagnifier.setTemporary(false);
        }
      });
      window.addEventListener("blur", () => {
        imageMagnifier.setTemporary(false);
      });
      magnifierToggleBtn.addEventListener("click", () => {
        toggleMagnifier();
      });
      pageImage.addEventListener("load", () => {
        applyZoom();
        imageMagnifier.refresh();
        hideCursorGuides();
      });

      if (typeof ResizeObserver !== "undefined") {
        const viewportResizeObserver = new ResizeObserver(() => {
          if (state.zoomMode !== "custom") {
            applyZoom();
          }
        });
        viewportResizeObserver.observe(imageViewport);
      } else {
        window.addEventListener("resize", () => {
          if (state.zoomMode !== "custom") {
            applyZoom();
          }
        });
      }

      async function init() {
        if (!Number.isInteger(pageId) || pageId <= 0) {
          setStatus("Missing or invalid page_id query parameter.", { isError: true });
          return;
        }
        try {
          setDrawModeActive(false);
          rebuildZoomPresetOptions();
          applyStoredZoomSettings();
          loadReviewHistory();
          await sanitizeReviewHistoryAgainstServer();
          registerCurrentPageInHistory();
          loadLayoutDraftState();
          await loadPage();
          await loadLayouts();
          await refreshNextReviewButton();
          applyZoom();
          setStatus("Ready.");
        } catch (error) {
          setStatus(`Load failed: ${error.message}`, { isError: true });
        }
      }

      init();
