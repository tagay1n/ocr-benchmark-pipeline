      import {
        clampZoomPercent,
        countStretchableGlyphs,
        computeApproxLineBand,
        computeApproxLineBandByIndex,
        computeZoomScale,
        computeOverlayBadgeScale,
        countStretchableSpaces,
        filterReviewHistory,
        findMaxFittingFontSize,
        nextHistoryPageId,
        normalizeZoomMode,
        normalizeReviewHistory,
        previousHistoryPageId,
        reconstructionHorizontalScale,
        reconstructionLetterSpacing,
        reconstructionLineHeight,
        reconstructionWordSpacing,
        ZOOM_PRESET_PERCENTS,
        updateReviewHistoryOnVisit,
      } from "./layout_review_utils.mjs";
      import {
        containsMarkdownTable,
        renderLatexInto,
        renderMarkdownInto,
      } from "./reconstructed_markdown.mjs";
      import {
        applyInlineMarkdownWrapper,
        applyLinePrefixMarkdown,
        computeViewportAutoCenterTarget,
        computeEditorToolbarState,
        computeReconstructedImageCropStyle,
        computeFloatingControlPlacement,
        countTextLines,
        detectEditorValidationIssues,
        findBestTokenOccurrence,
        hasLocalDraftForLayout,
        isRectOnscreen,
        isReconstructedRestoreDisabled,
        isLineSyncEnabledOutputFormat,
        lineBandFromLineIndex,
        lineIndexFromTextOffset,
        normalizeReviewViewMode,
        normalizeReconstructedRenderMode,
        resolveViewportScrollSyncUpdate,
        resolveEditorDrawerLayout,
        tokenBoundsAtOffset,
        textOffsetForLineIndex,
      } from "./ocr_review_utils.mjs";
      import {
        clampMagnifierZoom,
        createImageMagnifier,
      } from "./magnifier.mjs";
      import {
        colorForClass,
        formatClassLabel,
        normalizeClassName,
      } from "./layout_class_catalog.mjs";
      import {
        completeOcrReview,
        fetchNextOcrReviewPage,
        fetchPageDetails,
        fetchPageLayouts,
        fetchPageOcrOutputs,
        fetchPages,
        patchOcrOutput,
        reextractPageOcr,
      } from "./ocr_review_api.mjs";
      import {
        readStorage,
        readStorageBool,
        removeStorage,
        writeStorage,
      } from "./state_event_utils.mjs";
      import {
        loadStoredZoomSettings,
        rebuildZoomPresetOptions as rebuildZoomPresetOptionsShared,
        closeZoomMenu as closeZoomMenuShared,
        openZoomMenu as openZoomMenuShared,
        setZoomInputFromApplied as setZoomInputFromAppliedShared,
        updateZoomMenuSelection as updateZoomMenuSelectionShared,
      } from "./zoom_controller.mjs";
      import {
        formatStatusLabel,
        resolveViewportBottomLeftDockCorner,
        setToggleButtonActiveState,
        updateHistoryNavigationButtons,
        updateReviewStateBadge,
      } from "./review_shell_utils.mjs";
      import {
        historyNavigationTargets,
        loadReviewHistoryState,
        persistReviewHistoryState,
        registerCurrentPageVisit,
        sanitizeReviewHistoryFromPages,
      } from "./review_history_controller.mjs";
      import {
        closeModal,
        openModal,
        shouldCloseOnBackdropPointerDown,
      } from "./modal_controller.mjs";

      const STORAGE_KEYS = {
        draftPrefix: "ocrReview.drafts",
        history: "ocrReview.history",
        historyIndex: "ocrReview.history.index",
        panelVisibility: "ocrReview.panelVisibility",
        zoomMode: "ocrReview.zoom.mode",
        zoomPercent: "ocrReview.zoom.percent",
        magnifierEnabled: "ocrReview.magnifier.enabled",
        magnifierZoom: "ocrReview.magnifier.zoom",
        reconstructedRenderMode: "ocrReview.reconstructed.render_mode",
        reviewViewMode: "ocrReview.review.view_mode",
        editorFontSize: "ocrReview.editor.font_size",
        editorDrawerWidth: "ocrReview.editor.drawer_width",
      };
      const MAGNIFIER_ZOOM_MIN = 1.5;
      const MAGNIFIER_ZOOM_MAX = 6;
      const MAGNIFIER_ZOOM_STEP = 0.5;
      const MAGNIFIER_ZOOM_DEFAULT = 3;
      const MAGNIFIER_NEAR_BOTTOM_THRESHOLD = 36;
      const EDITOR_FONT_SIZE_MIN = 10;
      const EDITOR_FONT_SIZE_MAX = 24;
      const EDITOR_FONT_SIZE_DEFAULT = 13;
      const EDITOR_FONT_SIZE_STEP = 1;
      const EDITOR_DRAWER_WIDTH_MIN = 420;
      const EDITOR_DRAWER_WIDTH_MAX_RATIO = 0.9;
      const EDITOR_DRAWER_RESPONSIVE_BREAKPOINT = 1120;
      const FOCUSED_STRIP_PAD_RATIO = 0.02;
      const FOCUSED_STRIP_MIN_HEIGHT_RATIO = 0.08;
      const LINE_REVIEW_SLOT_OFFSETS = [0];
      const LINE_REVIEW_CONTEXT_RATIO = 0.28;
      const LINE_REVIEW_TARGET_HEIGHT_PX = 44;
      const LINE_REVIEW_MIN_HEIGHT_PX = 30;
      const LINE_REVIEW_MAX_HEIGHT_PX = 62;
      const LINE_REVIEW_MIN_WIDTH_PX = 120;
      const LINE_REVIEW_MIN_WIDTH_RATIO_FALLBACK = 0.08;
      const LINE_REVIEW_MAX_WIDTH_RATIO = 0.94;

      const reviewBtn = document.getElementById("review-btn");
      const reextractBtn = document.getElementById("reextract-btn");
      const zoomTrigger = document.getElementById("zoom-trigger");
      const zoomMenu = document.getElementById("zoom-menu");
      let zoomOptions = [];
      const zoomPercentInput = document.getElementById("zoom-percent-input");
      const magnifierToggleBtn = document.getElementById("magnifier-toggle-btn");
      const toggleSourceBtn = document.getElementById("toggle-source-btn");
      const toggleReconstructedBtn = document.getElementById("toggle-reconstructed-btn");
      const viewTwoPanelsBtn = document.getElementById("view-two-panels-btn");
      const viewLineByLineBtn = document.getElementById("view-line-by-line-btn");
      const grid = document.querySelector(".grid");
      const sourcePanel = document.getElementById("source-panel");
      const reconstructedPanel = document.getElementById("reconstructed-panel");
      const reconstructedFloatingControls = document.getElementById("reconstructed-floating-controls");
      const renderMarkdownBtn = document.getElementById("render-markdown-btn");
      const renderRawBtn = document.getElementById("render-raw-btn");
      const pageImage = document.getElementById("page-image");
      const reconstructionSurface = document.getElementById("reconstruction-surface");
      const sourceBindLinesLayer = document.getElementById("source-bind-lines-layer");
      const sourceLabelLayer = document.getElementById("source-label-layer");
      const sourceSelectedLabelLayer = document.getElementById("source-label-layer-selected");
      const sourceOverlay = document.getElementById("source-overlay");
      const sourceStripOverlay = document.getElementById("source-strip-overlay");
      const sourceStripTopMask = document.getElementById("source-strip-top-mask");
      const sourceStripBottomMask = document.getElementById("source-strip-bottom-mask");
      const sourceStripTopBoundary = document.getElementById("source-strip-top-boundary");
      const sourceStripBottomBoundary = document.getElementById("source-strip-bottom-boundary");
      const sourceViewport = document.getElementById("source-viewport");
      const reconstructedViewport = document.getElementById("reconstructed-viewport");
      const sourceWrap = document.getElementById("source-wrap");
      const reconstructedWrap = document.getElementById("reconstructed-wrap");
      const reconstructedStripOverlay = document.getElementById("reconstructed-strip-overlay");
      const reconstructedStripTopMask = document.getElementById("reconstructed-strip-top-mask");
      const reconstructedStripBottomMask = document.getElementById("reconstructed-strip-bottom-mask");
      const reconstructedStripTopBoundary = document.getElementById("reconstructed-strip-top-boundary");
      const reconstructedStripBottomBoundary = document.getElementById("reconstructed-strip-bottom-boundary");
      const pageMeta = document.getElementById("page-meta");
      const reviewStateBadge = document.getElementById("review-state-badge");
      const lineReviewPanel = document.getElementById("line-review-panel");
      const lineReviewLayout = document.getElementById("line-review-layout");
      const lineReviewProgress = document.getElementById("line-review-progress");
      const lineReviewReel = document.getElementById("line-review-reel");
      const lineReviewPrevBtn = document.getElementById("line-review-prev-btn");
      const lineReviewApproveBtn = document.getElementById("line-review-approve-btn");
      const lineReviewNextBtn = document.getElementById("line-review-next-btn");
      const lineReviewApproveBboxBtn = document.getElementById("line-review-approve-bbox-btn");
      const lineReviewResetBboxBtn = document.getElementById("line-review-reset-bbox-btn");
      const historyBackBtn = document.getElementById("history-back-btn");
      const historyForthBtn = document.getElementById("history-forth-btn");
      const reextractModal = document.getElementById("reextract-modal");
      const reextractModalLayoutsContainer = document.getElementById("reextract-modal-layouts");
      const reextractModalSelectAllInput = document.getElementById("reextract-modal-select-all");
      const reextractModalTemperatureInput = document.getElementById("reextract-modal-temperature");
      const reextractModalMaxRetriesInput = document.getElementById("reextract-modal-max-retries");
      const reextractModalCancelBtn = document.getElementById("reextract-modal-cancel-btn");
      const reextractModalRunBtn = document.getElementById("reextract-modal-run-btn");
      const expandedEditor = document.getElementById("expanded-editor");
      const expandedEditorResizeHandle = document.getElementById("expanded-editor-resize-handle");
      const expandedEditorModeBadge = document.getElementById("expanded-editor-mode-badge");
      const expandedEditorToolbar = document.getElementById("expanded-editor-toolbar");
      const editorActionBoldBtn = document.getElementById("editor-action-bold");
      const editorActionItalicBtn = document.getElementById("editor-action-italic");
      const editorActionInlineFormulaBtn = document.getElementById("editor-action-inline-formula");
      const editorActionListItemBtn = document.getElementById("editor-action-list-item");
      const editorActionOrderedListItemBtn = document.getElementById("editor-action-ordered-list-item");
      const editorFontSizeDecreaseBtn = document.getElementById("editor-font-size-decrease-btn");
      const editorFontSizeIncreaseBtn = document.getElementById("editor-font-size-increase-btn");
      const editorFontSizeValue = document.getElementById("editor-font-size-value");
      const expandedEditorWrapBtn = document.getElementById("expanded-editor-wrap-btn");
      const expandedEditorStatus = document.getElementById("expanded-editor-status");
      const expandedEditorStatusText = document.getElementById("expanded-editor-status-text");
      const expandedEditorValidation = document.getElementById("expanded-editor-validation");
      const expandedEditorCmHost = document.getElementById("expanded-editor-cm");
      const expandedEditorTextarea = document.getElementById("expanded-editor-textarea");
      const expandedEditorCloseBtn = document.getElementById("expanded-editor-close-btn");

      const state = {
        pageId: null,
        page: null,
        pageLayouts: [],
        outputs: [],
        serverOutputsByLayoutId: {},
        localEditsByLayoutId: {},
        approvedLineIndexesByLayoutId: {},
        lineCursorByLayoutId: {},
        selectedLayoutId: null,
        explicitSelectedLayoutId: null,
        reextractHoverLayoutId: null,
        hoveredLine: null,
        expandedEditorLayoutId: null,
        reviewSubmitInProgress: false,
        reextractInProgress: false,
        reextractProgressCurrent: 0,
        reextractProgressTotal: 0,
        reconstructedRenderMode: "markdown",
        zoomMode: "automatic",
        zoomPercent: 100,
        zoomAppliedPercent: 100,
        history: [],
        historyIndex: -1,
        nextReviewPageId: null,
        magnifierEnabled: readStorageBool(STORAGE_KEYS.magnifierEnabled, true),
        magnifierZoom: clampMagnifierZoom(readStorage(STORAGE_KEYS.magnifierZoom), {
          min: MAGNIFIER_ZOOM_MIN,
          max: MAGNIFIER_ZOOM_MAX,
          fallback: MAGNIFIER_ZOOM_DEFAULT,
        }),
        panelVisibility: {
          source: true,
          reconstructed: true,
        },
        viewMode: "two_panels",
        editorFontSize: EDITOR_FONT_SIZE_DEFAULT,
        editorDrawerWidth: null,
      };
      let reconstructionRefitScheduled = false;
      const RECONSTRUCTED_CONTROLS_IDLE_MS = 2500;
      let reconstructedControlsIdleTimer = null;
      let codeMirrorDepsPromise = null;
      let codeMirrorDeps = null;
      let codeMirrorView = null;
      let suppressCodeMirrorChange = false;
      let editorWrapEnabled = true;
      let editorResizeSession = null;
      let altMagnifierPressed = false;
      let scrollSyncMutedViewport = null;
      let lineReviewTextMeasureNode = null;

      function updateMagnifierToggleUi() {
        setToggleButtonActiveState(magnifierToggleBtn, state.magnifierEnabled);
      }

      function resolveMagnifierDockCorner() {
        return resolveViewportBottomLeftDockCorner(sourceViewport, MAGNIFIER_NEAR_BOTTOM_THRESHOLD);
      }

      const sourceImageMagnifier = createImageMagnifier({
        viewport: sourceViewport,
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
        getOverlayItems: () =>
          state.outputs.map((output) => {
            const color = colorForClass(output.class_name);
            const selected = Number(output.layout_id) === Number(state.selectedLayoutId);
            return {
              bbox: output.bbox,
              stroke: color,
              fill: selected ? hexToRgba(color, 0.2) : "",
              lineWidth: selected ? 2 : 1.3,
            };
          }),
      });

      function setMagnifierEnabled(enabled) {
        const normalized = Boolean(enabled);
        if (state.magnifierEnabled === normalized) {
          return;
        }
        state.magnifierEnabled = normalized;
        writeStorage(STORAGE_KEYS.magnifierEnabled, normalized ? "1" : "0");
        sourceImageMagnifier.setEnabled(normalized);
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
        sourceImageMagnifier.setZoom(zoom);
      }

      function normalizePanelVisibility(rawValue) {
        let parsed = rawValue;
        if (typeof rawValue === "string") {
          try {
            parsed = JSON.parse(rawValue);
          } catch {
            parsed = null;
          }
        }
        const next = {
          source: true,
          reconstructed: true,
        };
        if (parsed && typeof parsed === "object") {
          if (typeof parsed.source === "boolean") next.source = parsed.source;
          if (typeof parsed.reconstructed === "boolean") next.reconstructed = parsed.reconstructed;
        }
        if (!next.source && !next.reconstructed) {
          next.reconstructed = true;
        }
        return next;
      }

      function applyRenderModeUi() {
        const isMarkdown = state.reconstructedRenderMode === "markdown";
        renderMarkdownBtn.classList.toggle("active", isMarkdown);
        renderMarkdownBtn.setAttribute("aria-pressed", isMarkdown ? "true" : "false");
        renderRawBtn.classList.toggle("active", !isMarkdown);
        renderRawBtn.setAttribute("aria-pressed", isMarkdown ? "false" : "true");
      }

      function persistReconstructedRenderMode() {
        writeStorage(STORAGE_KEYS.reconstructedRenderMode, state.reconstructedRenderMode);
      }

      function setReconstructedRenderMode(mode) {
        const nextMode = normalizeReconstructedRenderMode(mode);
        if (nextMode === state.reconstructedRenderMode) {
          return;
        }
        state.reconstructedRenderMode = nextMode;
        persistReconstructedRenderMode();
        applyRenderModeUi();
        renderReconstruction();
      }

      function clearReconstructedControlsIdleTimer() {
        if (reconstructedControlsIdleTimer !== null) {
          window.clearTimeout(reconstructedControlsIdleTimer);
          reconstructedControlsIdleTimer = null;
        }
      }

      function setReconstructedControlsIdle(idle) {
        if (!reconstructedFloatingControls) {
          return;
        }
        reconstructedFloatingControls.classList.toggle("is-idle", Boolean(idle));
      }

      function notifyReconstructedControlsActivity() {
        if (!reconstructedFloatingControls || !state.panelVisibility.reconstructed) {
          return;
        }
        setReconstructedControlsIdle(false);
        clearReconstructedControlsIdleTimer();
        reconstructedControlsIdleTimer = window.setTimeout(() => {
          setReconstructedControlsIdle(true);
          reconstructedControlsIdleTimer = null;
        }, RECONSTRUCTED_CONTROLS_IDLE_MS);
      }

      function updateReconstructedFloatingControlsPosition() {
        if (!reconstructedFloatingControls) {
          return;
        }
        if (!state.panelVisibility.reconstructed) {
          reconstructedFloatingControls.style.visibility = "hidden";
          return;
        }
        const anchorRect = reconstructedViewport.getBoundingClientRect();
        if (!isRectOnscreen(anchorRect, { windowWidth: window.innerWidth, windowHeight: window.innerHeight })) {
          reconstructedFloatingControls.style.visibility = "hidden";
          return;
        }

        const controlRect = reconstructedFloatingControls.getBoundingClientRect();
        const controlHeight = Number.isFinite(controlRect.height) && controlRect.height > 0 ? controlRect.height : 0;
        const placement = computeFloatingControlPlacement({
          anchorRect,
          controlHeight,
          windowWidth: window.innerWidth,
          windowHeight: window.innerHeight,
          desiredTop: 10,
          edgeInset: 6,
        });
        reconstructedFloatingControls.style.visibility = placement.visible ? "visible" : "hidden";
        if (!placement.visible) {
          return;
        }
        reconstructedFloatingControls.style.top = `${placement.top}px`;
        reconstructedFloatingControls.style.right = `${placement.right}px`;
      }

      function syncViewportScroll(sourceViewportEl, targetViewportEl) {
        if (!sourceViewportEl || !targetViewportEl) {
          return;
        }
        if (!state.panelVisibility.source || !state.panelVisibility.reconstructed) {
          scrollSyncMutedViewport = null;
          return;
        }
        if (scrollSyncMutedViewport === sourceViewportEl) {
          scrollSyncMutedViewport = null;
          return;
        }
        const update = resolveViewportScrollSyncUpdate({
          sourceLeft: sourceViewportEl.scrollLeft,
          sourceTop: sourceViewportEl.scrollTop,
          targetLeft: targetViewportEl.scrollLeft,
          targetTop: targetViewportEl.scrollTop,
        });
        if (!update) {
          return;
        }
        scrollSyncMutedViewport = targetViewportEl;
        targetViewportEl.scrollLeft = update.left;
        targetViewportEl.scrollTop = update.top;
        requestAnimationFrame(() => {
          if (scrollSyncMutedViewport === targetViewportEl) {
            scrollSyncMutedViewport = null;
          }
        });
      }

      function visiblePanelCount() {
        return Number(state.panelVisibility.source) + Number(state.panelVisibility.reconstructed);
      }

      function visiblePanelOrder() {
        const order = [];
        if (state.panelVisibility.source) order.push("source");
        if (state.panelVisibility.reconstructed) order.push("reconstructed");
        return order;
      }

      function gridTemplateColumnsForVisiblePanels() {
        const order = visiblePanelOrder();
        if (order.length === 0) {
          return "minmax(0, 1fr)";
        }
        return order.map(() => "minmax(0, 1fr)").join(" ");
      }

      function clearFocusedStripOverlay() {
        const overlays = [sourceStripOverlay, reconstructedStripOverlay];
        for (const overlay of overlays) {
          if (overlay) {
            overlay.hidden = true;
          }
        }
      }

      function focusedStripBoundsForSelectedLayout() {
        const selectedLayoutId = Number(state.selectedLayoutId);
        if (!Number.isInteger(selectedLayoutId) || selectedLayoutId <= 0) {
          return null;
        }
        const selectedOutput =
          state.outputs.find((output) => Number(output.layout_id) === selectedLayoutId) || null;
        if (!selectedOutput || !selectedOutput.bbox) {
          return null;
        }
        const rawTop = Number(selectedOutput.bbox.y1);
        const rawBottom = Number(selectedOutput.bbox.y2);
        if (!Number.isFinite(rawTop) || !Number.isFinite(rawBottom)) {
          return null;
        }
        let top = Math.max(0, Math.min(1, Math.min(rawTop, rawBottom)));
        let bottom = Math.max(0, Math.min(1, Math.max(rawTop, rawBottom)));
        if (bottom - top <= 0) {
          return null;
        }
        top = Math.max(0, top - FOCUSED_STRIP_PAD_RATIO);
        bottom = Math.min(1, bottom + FOCUSED_STRIP_PAD_RATIO);
        const minHeight = Math.max(0.01, FOCUSED_STRIP_MIN_HEIGHT_RATIO);
        if (bottom - top < minHeight) {
          const center = (top + bottom) / 2;
          top = Math.max(0, center - minHeight / 2);
          bottom = Math.min(1, top + minHeight);
          top = Math.max(0, bottom - minHeight);
        }
        return { top, bottom };
      }

      function applyFocusedStripOverlayToNodes(
        overlay,
        topMask,
        bottomMask,
        topBoundary,
        bottomBoundary,
        bounds,
      ) {
        if (!overlay || !topMask || !bottomMask || !topBoundary || !bottomBoundary || !bounds) {
          return;
        }
        const top = Math.max(0, Math.min(1, Number(bounds.top)));
        const bottom = Math.max(top, Math.min(1, Number(bounds.bottom)));
        topMask.style.top = "0";
        topMask.style.height = `${top * 100}%`;
        bottomMask.style.top = `${bottom * 100}%`;
        bottomMask.style.height = `${Math.max(0, 1 - bottom) * 100}%`;
        topBoundary.style.top = `${top * 100}%`;
        bottomBoundary.style.top = `${bottom * 100}%`;
        overlay.hidden = false;
      }

      function applyFocusedStripOverlay() {
        clearFocusedStripOverlay();
      }

      function applyViewModeControls() {
        const isLineByLine = state.viewMode === "line_by_line";
        if (viewTwoPanelsBtn instanceof HTMLButtonElement) {
          viewTwoPanelsBtn.classList.toggle("active", !isLineByLine);
          viewTwoPanelsBtn.setAttribute("aria-pressed", isLineByLine ? "false" : "true");
        }
        if (viewLineByLineBtn instanceof HTMLButtonElement) {
          viewLineByLineBtn.classList.toggle("active", isLineByLine);
          viewLineByLineBtn.setAttribute("aria-pressed", isLineByLine ? "true" : "false");
        }
        grid.classList.toggle("view-mode-line-by-line", isLineByLine);
        grid.classList.toggle("view-mode-two-panels", !isLineByLine);
        applyFocusedStripOverlay();
        renderLineReviewPanel();
      }

      function persistReviewViewMode() {
        writeStorage(STORAGE_KEYS.reviewViewMode, state.viewMode);
      }

      function setReviewViewMode(mode, { persist = true } = {}) {
        const nextMode = normalizeReviewViewMode(mode);
        if (nextMode === state.viewMode) {
          return;
        }
        state.viewMode = nextMode;
        if (persist) {
          persistReviewViewMode();
        }
        if (state.viewMode !== "line_by_line") {
          setHoveredLine(null, null, { source: "view_mode" });
        }
        applyViewModeControls();
        updateReviewUiState();
        const selectedLayoutId = Number(state.selectedLayoutId);
        const selectedOutput = outputByLayoutId(selectedLayoutId);
        if (
          state.viewMode === "line_by_line" &&
          (!selectedOutput || !lineReviewRequiredOutput(selectedOutput))
        ) {
          const firstRequired = state.outputs.find((output) => lineReviewRequiredOutput(output));
          if (firstRequired) {
            selectOutput(firstRequired.layout_id, { scrollImageToLayout: true, isUserSelection: true });
          }
          return;
        }
        if (Number.isInteger(selectedLayoutId) && selectedLayoutId > 0) {
          if (state.viewMode === "line_by_line") {
            syncHoveredLineFromLineReviewCursor(selectedLayoutId);
          }
          ensureLayoutVisible(selectedLayoutId, 8, {
            preferVerticalCenter: state.viewMode === "line_by_line",
          });
        }
      }

      function applyPanelVisibility() {
        sourcePanel.classList.toggle("panel-hidden", !state.panelVisibility.source);
        reconstructedPanel.classList.toggle("panel-hidden", !state.panelVisibility.reconstructed);

        toggleSourceBtn.classList.toggle("active", state.panelVisibility.source);
        toggleSourceBtn.setAttribute("aria-pressed", state.panelVisibility.source ? "true" : "false");
        toggleReconstructedBtn.classList.toggle("active", state.panelVisibility.reconstructed);
        toggleReconstructedBtn.setAttribute("aria-pressed", state.panelVisibility.reconstructed ? "true" : "false");

        applyViewModeControls();
        grid.style.gridTemplateColumns = gridTemplateColumnsForVisiblePanels();
        if (state.panelVisibility.reconstructed) {
          notifyReconstructedControlsActivity();
        } else {
          clearReconstructedControlsIdleTimer();
          setReconstructedControlsIdle(false);
        }
        updateReconstructedFloatingControlsPosition();
        requestAnimationFrame(() => {
          applyZoom();
        });
        applySelectedStyles();
      }

      function persistPanelVisibility() {
        writeStorage(STORAGE_KEYS.panelVisibility, JSON.stringify(state.panelVisibility));
      }

      function togglePanel(panelKey) {
        if (!(panelKey in state.panelVisibility)) {
          return;
        }
        if (state.panelVisibility[panelKey] && visiblePanelCount() <= 1) {
          setStatus("At least one panel must stay visible.");
          return;
        }
        state.panelVisibility[panelKey] = !state.panelVisibility[panelKey];
        applyPanelVisibility();
        persistPanelVisibility();
      }

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

      function applyStoredEditorFontSize() {
        const raw = readStorage(STORAGE_KEYS.editorFontSize);
        if (raw !== null) {
          state.editorFontSize = clampEditorFontSize(raw);
        } else {
          state.editorFontSize = EDITOR_FONT_SIZE_DEFAULT;
        }
        applyExpandedEditorFontSize({ persist: false });
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

      function activeZoomViewport() {
        if (state.panelVisibility.source && sourceViewport.clientWidth > 0 && sourceViewport.clientHeight > 0) {
          return sourceViewport;
        }
        if (
          state.panelVisibility.reconstructed &&
          reconstructedViewport.clientWidth > 0 &&
          reconstructedViewport.clientHeight > 0
        ) {
          return reconstructedViewport;
        }
        if (sourceViewport.clientWidth > 0 && sourceViewport.clientHeight > 0) {
          return sourceViewport;
        }
        if (reconstructedViewport.clientWidth > 0 && reconstructedViewport.clientHeight > 0) {
          return reconstructedViewport;
        }
        return null;
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

      function centerPreviewInViewport(viewport, content, { alignTop = false } = {}) {
        const viewportWidth = viewport.clientWidth;
        const viewportHeight = viewport.clientHeight;
        const contentWidth = content.offsetWidth;
        const contentHeight = content.offsetHeight;
        if (!viewportWidth || !viewportHeight || !contentWidth || !contentHeight) {
          return;
        }
        viewport.scrollLeft = Math.max(0, Math.round((contentWidth - viewportWidth) / 2));
        viewport.scrollTop = alignTop ? 0 : Math.max(0, Math.round((contentHeight - viewportHeight) / 2));
      }

      function applyZoom() {
        const naturalWidth = Number(pageImage.naturalWidth);
        const naturalHeight = Number(pageImage.naturalHeight);
        if (!Number.isFinite(naturalWidth) || !Number.isFinite(naturalHeight) || naturalWidth <= 0 || naturalHeight <= 0) {
          return;
        }

        const viewport = activeZoomViewport();
        if (!viewport) {
          return;
        }

        const fitViewport = fitMeasurementForViewport(viewport);
        const wrapStyle = window.getComputedStyle(sourceWrap);
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
        const width = `${displayWidth}px`;
        const height = `${displayHeight}px`;

        pageImage.style.width = width;
        pageImage.style.height = height;
        sourceWrap.style.width = width;
        sourceWrap.style.height = height;
        sourceWrap.style.setProperty("--overlay-badge-scale", String(computeOverlayBadgeScale(scale)));
        reconstructedWrap.style.width = width;
        reconstructedWrap.style.height = height;
        reconstructionSurface.style.width = width;
        reconstructionSurface.style.height = height;

        state.zoomAppliedPercent = Math.round(scale * 1000) / 10;
        setZoomInputFromApplied();
        updateZoomMenuSelection();
        applyFocusedStripOverlay();

        requestAnimationFrame(() => {
          refitReconstructedContent();
          const alignTop = state.zoomMode === "fit-page" || state.zoomMode === "fit-height";
          if (state.panelVisibility.source) {
            centerPreviewInViewport(sourceViewport, sourceWrap, { alignTop });
          }
          if (state.panelVisibility.reconstructed) {
            centerPreviewInViewport(reconstructedViewport, reconstructedWrap, { alignTop });
          }
          applyFocusedStripOverlay();
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

      function setStatus(message, { isError = false } = {}) {
        if (isError) {
          console.error(message);
        }
      }

      function draftStorageKey() {
        return `${STORAGE_KEYS.draftPrefix}:${state.pageId}`;
      }

      function setExpandedEditorModeBadge(mode) {
        if (!expandedEditorModeBadge) {
          return;
        }
        const normalized = String(mode || "").trim().toLowerCase();
        expandedEditorModeBadge.classList.remove("codemirror", "fallback");
        if (normalized === "codemirror") {
          expandedEditorModeBadge.hidden = false;
          expandedEditorModeBadge.textContent = "CodeMirror";
          expandedEditorModeBadge.classList.add("codemirror");
          return;
        }
        expandedEditorModeBadge.hidden = true;
      }

      function setExpandedEditorWrapButtonState(enabled) {
        editorWrapEnabled = Boolean(enabled);
        expandedEditorWrapBtn.textContent = editorWrapEnabled ? "Wrap on" : "Wrap off";
      }

      function clampEditorFontSize(value) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) {
          return EDITOR_FONT_SIZE_DEFAULT;
        }
        return Math.max(EDITOR_FONT_SIZE_MIN, Math.min(EDITOR_FONT_SIZE_MAX, Math.round(numeric)));
      }

      function applyExpandedEditorFontSize({ persist = false } = {}) {
        const clamped = clampEditorFontSize(state.editorFontSize);
        state.editorFontSize = clamped;
        expandedEditor.style.setProperty("--expanded-editor-font-size", `${clamped}px`);
        if (editorFontSizeValue) {
          editorFontSizeValue.textContent = `${clamped}px`;
        }
        if (editorFontSizeDecreaseBtn) {
          editorFontSizeDecreaseBtn.disabled = clamped <= EDITOR_FONT_SIZE_MIN;
        }
        if (editorFontSizeIncreaseBtn) {
          editorFontSizeIncreaseBtn.disabled = clamped >= EDITOR_FONT_SIZE_MAX;
        }
        if (persist) {
          writeStorage(STORAGE_KEYS.editorFontSize, String(clamped));
        }
      }

      function setExpandedEditorFontSize(nextSize) {
        state.editorFontSize = clampEditorFontSize(nextSize);
        applyExpandedEditorFontSize({ persist: true });
      }

      function applyExpandedEditorDrawerWidth({ persist = false } = {}) {
        const layout = resolveEditorDrawerLayout({
          requestedWidth: state.editorDrawerWidth,
          viewportWidth: window.innerWidth,
          minWidth: EDITOR_DRAWER_WIDTH_MIN,
          maxRatio: EDITOR_DRAWER_WIDTH_MAX_RATIO,
          responsiveBreakpoint: EDITOR_DRAWER_RESPONSIVE_BREAKPOINT,
        });
        const resizable = Boolean(layout.resizable);
        if (expandedEditorResizeHandle) {
          expandedEditorResizeHandle.hidden = !resizable;
        }

        if (!resizable) {
          expandedEditor.style.removeProperty("width");
        } else {
          const clamped = layout.width;
          if (Number.isFinite(clamped)) {
            state.editorDrawerWidth = clamped;
            expandedEditor.style.width = `${clamped}px`;
          } else {
            state.editorDrawerWidth = null;
            expandedEditor.style.removeProperty("width");
          }
        }

        if (persist) {
          if (Number.isFinite(state.editorDrawerWidth)) {
            writeStorage(STORAGE_KEYS.editorDrawerWidth, String(state.editorDrawerWidth));
          } else {
            removeStorage(STORAGE_KEYS.editorDrawerWidth);
          }
        }
      }

      function setExpandedEditorDrawerWidth(nextWidth) {
        state.editorDrawerWidth = Number(nextWidth);
        applyExpandedEditorDrawerWidth({ persist: true });
      }

      function applyStoredEditorDrawerWidth() {
        const raw = readStorage(STORAGE_KEYS.editorDrawerWidth);
        state.editorDrawerWidth = raw !== null ? Number(raw) : null;
        applyExpandedEditorDrawerWidth({ persist: false });
      }

      function beginEditorDrawerResize(event) {
        if (!(event instanceof PointerEvent) || event.button !== 0) {
          return;
        }
        const layout = resolveEditorDrawerLayout({
          requestedWidth: state.editorDrawerWidth,
          viewportWidth: window.innerWidth,
          minWidth: EDITOR_DRAWER_WIDTH_MIN,
          maxRatio: EDITOR_DRAWER_WIDTH_MAX_RATIO,
          responsiveBreakpoint: EDITOR_DRAWER_RESPONSIVE_BREAKPOINT,
        });
        if (!layout.resizable) {
          return;
        }
        const rect = expandedEditor.getBoundingClientRect();
        editorResizeSession = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startWidth: rect.width,
        };
        expandedEditorResizeHandle.setPointerCapture(event.pointerId);
        document.body.classList.add("editor-resizing");
        event.preventDefault();
      }

      function updateEditorDrawerResize(event) {
        if (!editorResizeSession || !(event instanceof PointerEvent)) {
          return;
        }
        if (event.pointerId !== editorResizeSession.pointerId) {
          return;
        }
        const delta = editorResizeSession.startX - event.clientX;
        setExpandedEditorDrawerWidth(editorResizeSession.startWidth + delta);
      }

      function endEditorDrawerResize(event) {
        if (!editorResizeSession) {
          return;
        }
        if (event instanceof PointerEvent && event.pointerId !== editorResizeSession.pointerId) {
          return;
        }
        if (
          expandedEditorResizeHandle &&
          event instanceof PointerEvent &&
          expandedEditorResizeHandle.hasPointerCapture(event.pointerId)
        ) {
          expandedEditorResizeHandle.releasePointerCapture(event.pointerId);
        }
        editorResizeSession = null;
        document.body.classList.remove("editor-resizing");
      }

      function currentExpandedEditorOutput() {
        const layoutId = Number(state.expandedEditorLayoutId);
        if (!Number.isInteger(layoutId) || layoutId <= 0) {
          return null;
        }
        return outputByLayoutId(layoutId);
      }

      function isMarkdownOutput(output) {
        if (!output) {
          return false;
        }
        return isLineSyncEnabledOutputFormat(output.output_format);
      }

      function refreshExpandedEditorToolbar() {
        if (!expandedEditorToolbar) {
          return;
        }
        const output = currentExpandedEditorOutput();
        const toolbarState = computeEditorToolbarState({
          editorHidden: expandedEditor.hidden,
          outputFormat: output?.output_format,
        });
        expandedEditorToolbar.hidden = toolbarState.toolbarHidden;
        for (const button of [
          editorActionBoldBtn,
          editorActionItalicBtn,
          editorActionInlineFormulaBtn,
          editorActionListItemBtn,
          editorActionOrderedListItemBtn,
        ]) {
          if (button) {
            button.disabled = !toolbarState.markdownActionsEnabled;
          }
        }
      }

      function applyMarkdownActionToContent({ action, content, selectionStart, selectionEnd }) {
        const normalized = String(action || "").trim().toLowerCase();
        if (normalized === "bold") {
          return applyInlineMarkdownWrapper({
            content,
            selectionStart,
            selectionEnd,
            left: "**",
            right: "**",
            placeholder: "text",
          });
        }
        if (normalized === "italic") {
          return applyInlineMarkdownWrapper({
            content,
            selectionStart,
            selectionEnd,
            left: "*",
            right: "*",
            placeholder: "text",
          });
        }
        if (normalized === "inline_formula") {
          return applyInlineMarkdownWrapper({
            content,
            selectionStart,
            selectionEnd,
            left: "$",
            right: "$",
            placeholder: "formula",
          });
        }
        if (normalized === "list_item") {
          return applyLinePrefixMarkdown({
            content,
            selectionStart,
            selectionEnd,
            kind: "unordered",
          });
        }
        if (normalized === "ordered_list_item") {
          return applyLinePrefixMarkdown({
            content,
            selectionStart,
            selectionEnd,
            kind: "ordered",
          });
        }
        return null;
      }

      function applyMarkdownAction(action) {
        const output = currentExpandedEditorOutput();
        const layoutId = Number(state.expandedEditorLayoutId);
        if (!Number.isInteger(layoutId) || layoutId <= 0 || !isMarkdownOutput(output)) {
          return false;
        }

        if (codeMirrorView && !expandedEditorCmHost.hidden) {
          const content = codeMirrorView.state.doc.toString();
          const selection = codeMirrorView.state.selection.main;
          const result = applyMarkdownActionToContent({
            action,
            content,
            selectionStart: Number(selection.from),
            selectionEnd: Number(selection.to),
          });
          if (!result) {
            return false;
          }
          codeMirrorView.dispatch({
            changes: {
              from: 0,
              to: codeMirrorView.state.doc.length,
              insert: String(result.content ?? ""),
            },
            selection: {
              anchor: Number(result.selectionStart ?? 0),
              head: Number(result.selectionEnd ?? result.selectionStart ?? 0),
            },
            scrollIntoView: true,
          });
          codeMirrorView.focus();
          return true;
        }

        const content = String(expandedEditorTextarea.value ?? "");
        const start = Number.isInteger(expandedEditorTextarea.selectionStart)
          ? expandedEditorTextarea.selectionStart
          : content.length;
        const end = Number.isInteger(expandedEditorTextarea.selectionEnd)
          ? expandedEditorTextarea.selectionEnd
          : content.length;
        const result = applyMarkdownActionToContent({
          action,
          content,
          selectionStart: start,
          selectionEnd: end,
        });
        if (!result) {
          return false;
        }
        expandedEditorTextarea.value = String(result.content ?? "");
        expandedEditorTextarea.setSelectionRange(
          Number(result.selectionStart ?? 0),
          Number(result.selectionEnd ?? result.selectionStart ?? 0),
        );
        updateOutputFromInput(layoutId, expandedEditorTextarea);
        updateExpandedEditorStatusFromTextarea();
        renderExpandedEditorValidation();
        syncHoveredLineFromExpandedEditor({ source: "editor" });
        expandedEditorTextarea.focus();
        return true;
      }

      function resolveExpandedEditorHotkeyAction(event) {
        if (!(event instanceof KeyboardEvent)) {
          return null;
        }
        const hasMod = Boolean(event.ctrlKey || event.metaKey);
        if (!hasMod || event.altKey) {
          return null;
        }
        const key = String(event.key || "").toLowerCase();
        if (!event.shiftKey && key === "b") {
          return "bold";
        }
        if (!event.shiftKey && key === "i") {
          return "italic";
        }
        if (event.shiftKey && key === "e") {
          return "inline_formula";
        }
        if (event.shiftKey && (event.code === "Digit8" || key === "8" || key === "*")) {
          return "list_item";
        }
        if (event.shiftKey && (event.code === "Digit7" || key === "7")) {
          return "ordered_list_item";
        }
        return null;
      }

      function updateExpandedEditorStatusText({ line = 1, column = 1, chars = 0 } = {}) {
        if (expandedEditorStatusText) {
          expandedEditorStatusText.textContent = `Ln ${line}, Col ${column} | ${chars} chars`;
          return;
        }
        expandedEditorStatus.textContent = `Ln ${line}, Col ${column} | ${chars} chars`;
      }

      function renderExpandedEditorValidation() {
        if (!expandedEditorValidation) {
          return;
        }
        const layoutId = Number(state.expandedEditorLayoutId);
        if (!Number.isInteger(layoutId) || layoutId <= 0 || expandedEditor.hidden) {
          expandedEditorValidation.hidden = true;
          expandedEditorValidation.innerHTML = "";
          return;
        }
        const output = outputByLayoutId(layoutId);
        if (!output) {
          expandedEditorValidation.hidden = true;
          expandedEditorValidation.innerHTML = "";
          return;
        }
        const issues = detectEditorValidationIssues({
          content: output.content,
          format: output.output_format,
        });
        expandedEditorValidation.innerHTML = "";
        if (!issues.length) {
          expandedEditorValidation.hidden = true;
          return;
        }
        const fragment = document.createDocumentFragment();
        for (const issue of issues) {
          const badge = document.createElement("span");
          badge.className = "editor-validation-badge";
          badge.textContent = String(issue?.label || "Validation warning");
          fragment.appendChild(badge);
        }
        expandedEditorValidation.appendChild(fragment);
        expandedEditorValidation.hidden = false;
      }

      function updateExpandedEditorStatusFromCodeMirror(view = codeMirrorView) {
        if (!view) {
          return;
        }
        const head = Number(view.state.selection.main.head);
        const lineInfo = view.state.doc.lineAt(head);
        const line = Number(lineInfo.number);
        const column = Math.max(1, head - lineInfo.from + 1);
        updateExpandedEditorStatusText({
          line,
          column,
          chars: view.state.doc.length,
        });
      }

      function updateExpandedEditorStatusFromTextarea() {
        const text = String(expandedEditorTextarea.value ?? "");
        const cursor = Number.isInteger(expandedEditorTextarea.selectionStart)
          ? expandedEditorTextarea.selectionStart
          : text.length;
        const clampedCursor = Math.max(0, Math.min(text.length, cursor));
        const before = text.slice(0, clampedCursor);
        const line = before.split("\n").length;
        const lineStart = before.lastIndexOf("\n") + 1;
        const column = clampedCursor - lineStart + 1;
        updateExpandedEditorStatusText({
          line,
          column,
          chars: text.length,
        });
      }

      function toggleExpandedEditorWrap() {
        const nextEnabled = !editorWrapEnabled;
        setExpandedEditorWrapButtonState(nextEnabled);
        if (codeMirrorView) {
          const content = codeMirrorView.state.doc.toString();
          const selection = codeMirrorView.state.selection.main;
          const hadFocus = codeMirrorView.hasFocus;
          void ensureCodeMirrorView({
            initialText: content,
            forceRecreate: true,
            selection: {
              anchor: Number(selection.anchor),
              head: Number(selection.head),
            },
            focusEditor: hadFocus,
          });
          return;
        }
        if (expandedEditorTextarea) {
          expandedEditorTextarea.wrap = nextEnabled ? "soft" : "off";
          expandedEditorTextarea.style.whiteSpace = nextEnabled ? "pre-wrap" : "pre";
        }
      }

      function isCodeMirrorFocused() {
        return Boolean(codeMirrorView && codeMirrorView.hasFocus);
      }

      function setCodeMirrorContent(value, { moveCursorToEnd = false } = {}) {
        if (!codeMirrorView) {
          return;
        }
        const nextValue = String(value ?? "");
        const currentValue = codeMirrorView.state.doc.toString();
        const end = nextValue.length;
        suppressCodeMirrorChange = true;
        try {
          if (currentValue !== nextValue) {
            codeMirrorView.dispatch({
              changes: { from: 0, to: codeMirrorView.state.doc.length, insert: nextValue },
              ...(moveCursorToEnd ? { selection: { anchor: end } } : {}),
            });
          } else if (moveCursorToEnd) {
            codeMirrorView.dispatch({ selection: { anchor: end } });
          }
        } finally {
          suppressCodeMirrorChange = false;
        }
      }

      async function loadCodeMirrorDeps() {
        if (codeMirrorDepsPromise !== null) {
          const cached = await codeMirrorDepsPromise;
          if (!cached) {
            codeMirrorDepsPromise = null;
          }
          return cached;
        }
        codeMirrorDepsPromise = (async () => {
          const normalizeModule = (module) => {
            if (!module) {
              return null;
            }
            const EditorView = module?.EditorView ?? null;
            const basicSetup = module?.basicSetup ?? module?.minimalSetup ?? null;
            if (!EditorView || !basicSetup) {
              return null;
            }
            return { EditorView, basicSetup };
          };

          const importFromProvider = async (provider) => {
            try {
              const module = await import(provider.codemirror);
              const normalized = normalizeModule(module);
              if (normalized) {
                return normalized;
              }
            } catch {
              // Continue to fetch+blob fallback below.
            }

            if (!provider.allowFetchFallback) {
              return null;
            }

            try {
              const response = await fetch(provider.codemirror, { cache: "no-store" });
              if (!response.ok) {
                return null;
              }
              const source = await response.text();
              if (!source || !source.trim()) {
                return null;
              }
              const blobUrl = URL.createObjectURL(
                new Blob([source], { type: "text/javascript" }),
              );
              try {
                const blobModule = await import(blobUrl);
                return normalizeModule(blobModule);
              } finally {
                URL.revokeObjectURL(blobUrl);
              }
            } catch {
              return null;
            }
          };

          const providers = [
            {
              codemirror: "/static/js/vendor/codemirror.bundle.mjs",
              allowFetchFallback: true,
            },
            {
              codemirror: "./js/vendor/codemirror.bundle.mjs",
              allowFetchFallback: true,
            },
            {
              codemirror: "https://esm.sh/codemirror@6.0.2",
              allowFetchFallback: false,
            },
            {
              codemirror: "https://ga.jspm.io/npm:codemirror@6.0.2/dist/index.js",
              allowFetchFallback: false,
            },
          ];

          for (const provider of providers) {
            const deps = await importFromProvider(provider);
            if (deps) {
              return deps;
            }
          }
          return null;
        })();
        const deps = await codeMirrorDepsPromise;
        if (!deps) {
          codeMirrorDepsPromise = null;
        }
        return deps;
      }

      function destroyCodeMirrorView() {
        if (!codeMirrorView) {
          return;
        }
        codeMirrorView.destroy();
        codeMirrorView = null;
        if (expandedEditorCmHost) {
          expandedEditorCmHost.textContent = "";
        }
      }

      async function ensureCodeMirrorView({
        initialText = "",
        moveCursorToEnd = false,
        forceRecreate = false,
        selection = null,
        focusEditor = true,
      } = {}) {
        if (!expandedEditorCmHost) {
          return false;
        }
        if (codeMirrorView && !forceRecreate) {
          setCodeMirrorContent(initialText, { moveCursorToEnd });
          expandedEditorCmHost.hidden = false;
          expandedEditorTextarea.hidden = true;
          setExpandedEditorModeBadge("codemirror");
          updateExpandedEditorStatusFromCodeMirror(codeMirrorView);
          if (focusEditor) {
            codeMirrorView.focus();
          }
          return true;
        }
        if (forceRecreate) {
          destroyCodeMirrorView();
        }

        const deps = await loadCodeMirrorDeps();
        if (!deps) {
          setStatus("CodeMirror is unavailable; using textarea fallback.", { isError: true });
          setExpandedEditorModeBadge("fallback");
          return false;
        }

        const insertNewline = (view) => {
          const range = view.state.selection.main;
          const from = Number(range.from);
          const to = Number(range.to);
          view.dispatch({
            changes: { from, to, insert: "\n" },
            selection: { anchor: from + 1 },
          });
          return true;
        };

        const closeDrawer = () => {
          closeExpandedEditor();
          return true;
        };

        const updateListener = deps.EditorView.updateListener.of((update) => {
          if (update.docChanged && !suppressCodeMirrorChange) {
            const layoutId = Number(state.expandedEditorLayoutId);
            if (Number.isInteger(layoutId) && layoutId > 0) {
              const content = update.state.doc.toString();
              updateOutputContent(layoutId, content, { source: "codemirror" });
              const currentLineIndex = Math.max(0, Number(update.state.doc.lineAt(update.state.selection.main.head).number) - 1);
              approveLine(layoutId, currentLineIndex, { approved: true, persist: false });
              setLineReviewCursor(layoutId, currentLineIndex, { persist: false });
              persistDraftState();
            }
          }
          if (!update.docChanged && !update.selectionSet) {
            return;
          }
          updateExpandedEditorStatusFromCodeMirror(update.view);
          if (update.docChanged) {
            renderExpandedEditorValidation();
          }
          syncHoveredLineFromExpandedEditor({ source: "editor" });
        });

        const keyHandlers = deps.EditorView.domEventHandlers({
          keydown(event, view) {
            if (!(event instanceof KeyboardEvent)) {
              return false;
            }
            const hotkeyAction = resolveExpandedEditorHotkeyAction(event);
            if (hotkeyAction) {
              const applied = applyMarkdownAction(hotkeyAction);
              if (applied) {
                event.preventDefault();
              }
              return applied;
            }
            if (event.key !== "Enter") {
              return false;
            }
            if (event.ctrlKey || event.metaKey) {
              event.preventDefault();
              return insertNewline(view);
            }
            event.preventDefault();
            return closeDrawer();
          },
        });

        codeMirrorDeps = deps;
        const wrapExtension = editorWrapEnabled ? deps.EditorView.lineWrapping : [];
        const baseExtensions = [deps.basicSetup, wrapExtension, updateListener, keyHandlers];
        const initialSelection = selection
          ? {
              anchor: Number(selection.anchor ?? selection.head ?? 0),
              head: Number(selection.head ?? selection.anchor ?? 0),
            }
          : null;

        codeMirrorView = new deps.EditorView({
          parent: expandedEditorCmHost,
          doc: String(initialText ?? ""),
          extensions: baseExtensions,
          ...(initialSelection ? { selection: initialSelection } : {}),
        });

        expandedEditorCmHost.hidden = false;
        expandedEditorTextarea.hidden = true;
        setExpandedEditorModeBadge("codemirror");
        if (moveCursorToEnd) {
          setCodeMirrorContent(initialText, { moveCursorToEnd: true });
        }
        updateExpandedEditorStatusFromCodeMirror(codeMirrorView);
        if (focusEditor) {
          codeMirrorView.focus();
        }
        return true;
      }

      function closeExpandedEditor() {
        state.expandedEditorLayoutId = null;
        expandedEditor.hidden = true;
        renderExpandedEditorValidation();
        refreshExpandedEditorToolbar();
      }

      function openExpandedEditor(layoutId) {
        const normalized = Number(layoutId);
        if (!Number.isInteger(normalized) || normalized <= 0) {
          return;
        }
        const output = outputByLayoutId(normalized);
        if (!output) {
          return;
        }
        if (String(output.output_format || "").toLowerCase() === "skip") {
          return;
        }
        selectOutput(normalized, { scrollImageToLayout: true, isUserSelection: true });
        state.expandedEditorLayoutId = normalized;
        expandedEditor.hidden = false;
        const content = String(output.content ?? "");
        setExpandedEditorWrapButtonState(editorWrapEnabled);
        refreshExpandedEditorToolbar();
        if (codeMirrorView) {
          expandedEditorCmHost.hidden = false;
          expandedEditorTextarea.hidden = true;
          setExpandedEditorModeBadge("codemirror");
          setCodeMirrorContent(content, { moveCursorToEnd: true });
          updateExpandedEditorStatusFromCodeMirror(codeMirrorView);
          codeMirrorView.focus();
          renderExpandedEditorValidation();
          syncHoveredLineFromExpandedEditor({ source: "editor" });
          return;
        }
        setExpandedEditorModeBadge("loading");
        expandedEditorTextarea.hidden = false;
        expandedEditorCmHost.hidden = true;
        expandedEditorTextarea.value = content;
        expandedEditorTextarea.wrap = editorWrapEnabled ? "soft" : "off";
        expandedEditorTextarea.style.whiteSpace = editorWrapEnabled ? "pre-wrap" : "pre";
        expandedEditorTextarea.focus();
        const end = content.length;
        expandedEditorTextarea.setSelectionRange(end, end);
        updateExpandedEditorStatusFromTextarea();
        renderExpandedEditorValidation();
        syncHoveredLineFromExpandedEditor({ source: "editor" });
        void ensureCodeMirrorView({ initialText: content, moveCursorToEnd: true });
      }

      function syncExpandedEditorFromState() {
        const layoutId = Number(state.expandedEditorLayoutId);
        if (!Number.isInteger(layoutId) || layoutId <= 0) {
          return;
        }
        const output = outputByLayoutId(layoutId);
        if (!output) {
          closeExpandedEditor();
          return;
        }
        if (expandedEditor.hidden) {
          expandedEditor.hidden = false;
        }
        refreshExpandedEditorToolbar();
        const content = String(output.content ?? "");
        if (document.activeElement !== expandedEditorTextarea) {
          expandedEditorTextarea.value = content;
        }
        if (!isCodeMirrorFocused()) {
          setCodeMirrorContent(content);
        }
        if (!expandedEditorTextarea.hidden) {
          updateExpandedEditorStatusFromTextarea();
        } else {
          updateExpandedEditorStatusFromCodeMirror();
        }
        renderExpandedEditorValidation();
        syncHoveredLineFromExpandedEditor({ source: "editor" });
      }

      function compactTextPreview(value, maxLength = 90) {
        const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
        if (!normalized) {
          return "";
        }
        if (normalized.length <= maxLength) {
          return normalized;
        }
        return `${normalized.slice(0, maxLength - 1)}…`;
      }

      function outputPreviewText(layoutId) {
        const output = outputByLayoutId(layoutId);
        if (!output) {
          return "No OCR yet";
        }
        const format = String(output.output_format || "").toLowerCase();
        if (format === "skip") {
          return "Skipped region (no text extraction)";
        }
        let text = String(output.content ?? "");
        if (format === "html") {
          const parser = new DOMParser();
          const doc = parser.parseFromString(`<body>${text}</body>`, "text/html");
          text = doc.body.textContent || text;
        }
        const preview = compactTextPreview(text);
        return preview || "No OCR content";
      }

      function hexToRgba(hex, alpha) {
        const clean = hex.replace("#", "");
        const r = Number.parseInt(clean.slice(0, 2), 16);
        const g = Number.parseInt(clean.slice(2, 4), 16);
        const b = Number.parseInt(clean.slice(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
      }

      function hasDraftChanges() {
        return Object.keys(state.localEditsByLayoutId).length > 0;
      }

      function updateReviewBadge() {
        updateReviewStateBadge({
          badge: reviewStateBadge,
          status: state.page?.status,
          needsReviewStatus: "ocr_done",
          reviewedStatus: "ocr_reviewed",
        });
      }

      function updateReviewButtonState() {
        const alreadyReviewed = state.page?.status === "ocr_reviewed";
        const lineProgress = reviewProgressSummary();
        if (state.reviewSubmitInProgress) {
          reviewBtn.textContent = "Saving...";
          reviewBtn.disabled = true;
          return;
        }
        if (state.reextractInProgress) {
          reviewBtn.textContent = "Mark reviewed";
          reviewBtn.disabled = true;
          return;
        }
        if (alreadyReviewed && !hasDraftChanges()) {
          reviewBtn.textContent = "REVIEWED";
          reviewBtn.disabled = true;
          return;
        }
        if (state.viewMode === "line_by_line" && !lineProgress.complete) {
          reviewBtn.textContent = `Review lines (${lineProgress.missingTotal})`;
          reviewBtn.disabled = true;
          return;
        }
        reviewBtn.textContent = "Mark reviewed";
        reviewBtn.disabled = false;
      }

      function updateReextractButtonState() {
        if (state.reextractInProgress) {
          reextractBtn.textContent = "Detecting...";
          reextractBtn.disabled = true;
          return;
        }
        reextractBtn.textContent = "Detect";
        reextractBtn.disabled = state.reviewSubmitInProgress || !Number.isInteger(state.pageId) || state.pageId <= 0;
      }

      function updateReviewUiState() {
        updateReviewBadge();
        updateReviewButtonState();
        updateReextractButtonState();
        renderLineReviewPanel();
      }

      function setReextractModalBusy(busy) {
        const inProgress = Boolean(busy);
        reextractModalRunBtn.classList.toggle("is-busy", inProgress);
        reextractModalCancelBtn.disabled = inProgress;
        reextractModalTemperatureInput.disabled = inProgress;
        reextractModalMaxRetriesInput.disabled = inProgress;
        if (reextractModalSelectAllInput instanceof HTMLInputElement) {
          reextractModalSelectAllInput.disabled = inProgress;
        }
        const layoutInputs = reextractModalLayoutsContainer.querySelectorAll('input[name="reextract-layout-id"]');
        for (const checkbox of layoutInputs) {
          checkbox.disabled = inProgress;
        }
        updateReextractModalRunButtonState();
      }

      function normalizedLayoutsForReextract() {
        const rows = [];
        const seen = new Set();
        for (const row of state.pageLayouts) {
          const id = Number(row?.id);
          const readingOrder = Number(row?.reading_order);
          if (!Number.isInteger(id) || id <= 0 || seen.has(id)) {
            continue;
          }
          seen.add(id);
          rows.push({
            id,
            reading_order: Number.isInteger(readingOrder) && readingOrder > 0 ? readingOrder : id,
            class_name: String(row?.class_name || ""),
          });
        }
        rows.sort((a, b) => {
          const orderCmp = Number(a.reading_order) - Number(b.reading_order);
          if (orderCmp !== 0) return orderCmp;
          return Number(a.id) - Number(b.id);
        });
        return rows;
      }

      function defaultReextractSelection(layouts) {
        const selectedLayoutId = Number(state.explicitSelectedLayoutId);
        if (
          Number.isInteger(selectedLayoutId) &&
          selectedLayoutId > 0 &&
          layouts.some((layout) => Number(layout.id) === selectedLayoutId)
        ) {
          return new Set([selectedLayoutId]);
        }
        return new Set(layouts.map((layout) => Number(layout.id)));
      }

      function updateReextractModalSelectAllState() {
        if (!(reextractModalSelectAllInput instanceof HTMLInputElement)) {
          return;
        }
        const checkboxes = Array.from(
          reextractModalLayoutsContainer.querySelectorAll('input[name="reextract-layout-id"]'),
        );
        if (checkboxes.length === 0) {
          reextractModalSelectAllInput.checked = false;
          reextractModalSelectAllInput.indeterminate = false;
          reextractModalSelectAllInput.disabled = true;
          return;
        }
        const checkedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
        reextractModalSelectAllInput.disabled = state.reextractInProgress;
        reextractModalSelectAllInput.checked = checkedCount === checkboxes.length;
        reextractModalSelectAllInput.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
      }

      function updateReextractModalRunButtonLabel() {
        if (state.reextractInProgress) {
          const current = Math.max(0, Number(state.reextractProgressCurrent) || 0);
          const total = Math.max(0, Number(state.reextractProgressTotal) || 0);
          reextractModalRunBtn.textContent = `Processing ${Math.min(current, total)}/${total}`;
          return;
        }
        reextractModalRunBtn.textContent = "Run";
      }

      function updateReextractModalRunButtonState() {
        const checkboxes = Array.from(
          reextractModalLayoutsContainer.querySelectorAll('input[name="reextract-layout-id"]'),
        );
        const checkedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
        reextractModalRunBtn.disabled = state.reextractInProgress || checkboxes.length === 0 || checkedCount === 0;
        updateReextractModalSelectAllState();
        updateReextractModalRunButtonLabel();
      }

      function renderReextractLayoutOptions() {
        const layouts = normalizedLayoutsForReextract();
        const selectedByDefault = defaultReextractSelection(layouts);
        reextractModalLayoutsContainer.innerHTML = "";
        setReextractHoveredLayout(null);

        if (layouts.length === 0) {
          const empty = document.createElement("div");
          empty.className = "modal-layout-empty";
          empty.textContent = "No layouts available on this page.";
          reextractModalLayoutsContainer.appendChild(empty);
          updateReextractModalRunButtonState();
          return;
        }

        for (const layout of layouts) {
          const option = document.createElement("label");
          option.className = "modal-layout-option";

          const checkbox = document.createElement("input");
          checkbox.type = "checkbox";
          checkbox.name = "reextract-layout-id";
          checkbox.value = String(layout.id);
          checkbox.checked = selectedByDefault.has(layout.id);
          checkbox.disabled = state.reextractInProgress;
          checkbox.addEventListener("change", () => {
            updateReextractModalRunButtonState();
          });
          option.appendChild(checkbox);

          const textWrap = document.createElement("div");
          textWrap.className = "modal-layout-text";

          const main = document.createElement("div");
          main.className = "modal-layout-main";

          const swatch = document.createElement("span");
          swatch.className = "modal-layout-swatch";
          swatch.style.background = colorForClass(layout.class_name);
          main.appendChild(swatch);

          const title = document.createElement("span");
          title.className = "modal-layout-title";
          title.textContent = `${layout.reading_order}. ${formatClassLabel(layout.class_name)}`;
          main.appendChild(title);

          textWrap.appendChild(main);

          const meta = document.createElement("div");
          meta.className = "modal-layout-meta";
          meta.textContent = outputPreviewText(layout.id);
          textWrap.appendChild(meta);

          option.appendChild(textWrap);

          option.addEventListener("mouseenter", () => {
            setReextractHoveredLayout(layout.id);
          });
          option.addEventListener("mouseleave", () => {
            setReextractHoveredLayout(null);
          });
          option.addEventListener("focusin", () => {
            setReextractHoveredLayout(layout.id);
          });
          option.addEventListener("focusout", () => {
            setReextractHoveredLayout(null);
          });

          reextractModalLayoutsContainer.appendChild(option);
        }
        updateReextractModalRunButtonState();
      }

      function openReextractModal() {
        if (state.reviewSubmitInProgress || state.reextractInProgress) {
          return;
        }
        state.reextractProgressCurrent = 0;
        state.reextractProgressTotal = 0;
        renderReextractLayoutOptions();
        openModal(reextractModal);
      }

      function closeReextractModal(force = false) {
        closeModal(reextractModal, {
          force,
          isBusy: () => state.reextractInProgress,
          onClose: () => {
            setReextractHoveredLayout(null);
          },
        });
      }

      function parseReextractPayload() {
        const temperature = Number(reextractModalTemperatureInput.value);
        if (Number.isNaN(temperature) || temperature < 0 || temperature > 2) {
          throw new Error("Temperature must be between 0 and 2.");
        }

        const maxRetries = Number(reextractModalMaxRetriesInput.value);
        if (!Number.isInteger(maxRetries) || maxRetries < 1 || maxRetries > 10) {
          throw new Error("Max retries per layout must be an integer between 1 and 10.");
        }

        const layoutIds = Array.from(
          reextractModalLayoutsContainer.querySelectorAll('input[name="reextract-layout-id"]:checked'),
        )
          .map((checkbox) => Number(checkbox.value))
          .filter((value) => Number.isInteger(value) && value > 0);
        if (layoutIds.length === 0) {
          throw new Error("Select at least one layout to process.");
        }

        return {
          layout_ids: layoutIds,
          temperature,
          max_retries_per_layout: maxRetries,
        };
      }

      function toDraftShape(output) {
        return {
          content: String(output.content ?? ""),
        };
      }

      function sameDraft(a, b) {
        return String(a.content) === String(b.content);
      }

      function loadDraftState() {
        state.localEditsByLayoutId = {};
        state.approvedLineIndexesByLayoutId = {};
        state.lineCursorByLayoutId = {};
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
        if (!parsed || typeof parsed !== "object") return;
        const edits = parsed.edits;
        if (!edits || typeof edits !== "object") return;
        for (const [layoutIdRaw, value] of Object.entries(edits)) {
          const layoutId = Number(layoutIdRaw);
          if (!Number.isInteger(layoutId) || layoutId <= 0) continue;
          if (!value || typeof value !== "object") continue;
          state.localEditsByLayoutId[String(layoutId)] = {
            content: String(value.content ?? ""),
          };
        }
        const approvals = parsed.approvals;
        if (approvals && typeof approvals === "object") {
          for (const [layoutIdRaw, indexesRaw] of Object.entries(approvals)) {
            const layoutId = Number(layoutIdRaw);
            if (!Number.isInteger(layoutId) || layoutId <= 0 || !Array.isArray(indexesRaw)) {
              continue;
            }
            const unique = [];
            const seen = new Set();
            for (const rawIndex of indexesRaw) {
              const index = Number(rawIndex);
              if (!Number.isInteger(index) || index < 0 || seen.has(index)) {
                continue;
              }
              seen.add(index);
              unique.push(index);
            }
            state.approvedLineIndexesByLayoutId[String(layoutId)] = unique.sort((a, b) => a - b);
          }
        }
        const cursors = parsed.cursors;
        if (cursors && typeof cursors === "object") {
          for (const [layoutIdRaw, cursorRaw] of Object.entries(cursors)) {
            const layoutId = Number(layoutIdRaw);
            const cursor = Number(cursorRaw);
            if (!Number.isInteger(layoutId) || layoutId <= 0 || !Number.isInteger(cursor) || cursor < 0) {
              continue;
            }
            state.lineCursorByLayoutId[String(layoutId)] = cursor;
          }
        }
      }

      function persistDraftState() {
        const payload = {
          edits: state.localEditsByLayoutId,
          approvals: state.approvedLineIndexesByLayoutId,
          cursors: state.lineCursorByLayoutId,
        };
        writeStorage(draftStorageKey(), JSON.stringify(payload));
        updateReviewUiState();
      }

      function clearDraftState() {
        state.localEditsByLayoutId = {};
        state.approvedLineIndexesByLayoutId = {};
        state.lineCursorByLayoutId = {};
        removeStorage(draftStorageKey());
        updateReviewUiState();
      }

      function applyDraftsToOutputs() {
        state.outputs = state.outputs.map((output) => {
          const draft = state.localEditsByLayoutId[String(output.layout_id)];
          if (!draft) return output;
          return { ...output, content: String(draft.content ?? "") };
        });
      }

      function reconcileLineReviewState() {
        const validLayoutIds = new Set(state.outputs.map((output) => String(output.layout_id)));
        for (const key of Object.keys(state.approvedLineIndexesByLayoutId)) {
          if (!validLayoutIds.has(key)) {
            delete state.approvedLineIndexesByLayoutId[key];
            continue;
          }
          const output = outputByLayoutId(Number(key));
          if (!output || !lineReviewRequiredOutput(output)) {
            delete state.approvedLineIndexesByLayoutId[key];
            continue;
          }
          const lineCount = logicalLinesForOutput(output).length;
          state.approvedLineIndexesByLayoutId[key] = normalizeApprovedLineIndexes(key, lineCount);
        }
        for (const key of Object.keys(state.lineCursorByLayoutId)) {
          if (!validLayoutIds.has(key)) {
            delete state.lineCursorByLayoutId[key];
            continue;
          }
          const output = outputByLayoutId(Number(key));
          if (!output || !lineReviewRequiredOutput(output)) {
            delete state.lineCursorByLayoutId[key];
            continue;
          }
          const lineCount = logicalLinesForOutput(output).length;
          const cursor = Number(state.lineCursorByLayoutId[key]);
          if (!Number.isInteger(cursor) || cursor < 0 || cursor >= lineCount) {
            state.lineCursorByLayoutId[key] = Math.max(0, Math.min(lineCount - 1, firstUnapprovedLineIndex(key)));
          }
        }
      }

      function sortOutputsInPlace() {
        state.outputs.sort((a, b) => {
          const orderCmp = Number(a.reading_order) - Number(b.reading_order);
          if (orderCmp !== 0) return orderCmp;
          return Number(a.layout_id) - Number(b.layout_id);
        });
      }

      function outputByLayoutId(layoutId) {
        return state.outputs.find((output) => Number(output.layout_id) === Number(layoutId)) || null;
      }

      function logicalLinesForOutput(output) {
        const content = String(output?.content ?? "").replace(/\r\n/g, "\n");
        return content.split("\n");
      }

      function serverLogicalLinesForLayout(layoutId) {
        const key = String(Number(layoutId));
        const serverOutput = state.serverOutputsByLayoutId[key];
        const content = String(serverOutput?.content ?? "").replace(/\r\n/g, "\n");
        return content.split("\n");
      }

      function isTextLikeOutput(output) {
        const className = normalizeClassName(output?.class_name);
        return (
          className === "text" ||
          className === "section_header" ||
          className === "list_item" ||
          className === "caption" ||
          className === "footnote" ||
          className === "page_header" ||
          className === "page_footer" ||
          className === "picture_text"
        );
      }

      function lineReviewRequiredOutput(output) {
        return isTextLikeOutput(output) && String(output?.output_format || "").toLowerCase() !== "skip";
      }

      function normalizeApprovedLineIndexes(layoutId, lineCount) {
        const rawIndexes = state.approvedLineIndexesByLayoutId[String(layoutId)];
        if (!Array.isArray(rawIndexes) || lineCount <= 0) {
          return [];
        }
        const unique = [];
        const seen = new Set();
        for (const rawIndex of rawIndexes) {
          const index = Number(rawIndex);
          if (!Number.isInteger(index) || index < 0 || index >= lineCount || seen.has(index)) {
            continue;
          }
          seen.add(index);
          unique.push(index);
        }
        unique.sort((a, b) => a - b);
        return unique;
      }

      function approvedLineSet(layoutId, lineCount) {
        return new Set(normalizeApprovedLineIndexes(layoutId, lineCount));
      }

      function updateApprovedLineIndexes(layoutId, indexes, { persist = true } = {}) {
        const normalizedLayoutId = Number(layoutId);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          return;
        }
        const output = outputByLayoutId(normalizedLayoutId);
        if (!output) {
          return;
        }
        const lineCount = logicalLinesForOutput(output).length;
        const normalizedIndexes = Array.isArray(indexes)
          ? indexes
              .map((value) => Number(value))
              .filter((value) => Number.isInteger(value) && value >= 0 && value < lineCount)
              .filter((value, index, values) => values.indexOf(value) === index)
              .sort((a, b) => a - b)
          : [];
        if (normalizedIndexes.length > 0) {
          state.approvedLineIndexesByLayoutId[String(normalizedLayoutId)] = normalizedIndexes;
        } else {
          delete state.approvedLineIndexesByLayoutId[String(normalizedLayoutId)];
        }
        if (persist) {
          persistDraftState();
        }
      }

      function firstUnapprovedLineIndex(layoutId) {
        const output = outputByLayoutId(layoutId);
        if (!output) {
          return 0;
        }
        const lines = logicalLinesForOutput(output);
        const approved = approvedLineSet(layoutId, lines.length);
        for (let index = 0; index < lines.length; index += 1) {
          if (!approved.has(index)) {
            return index;
          }
        }
        return Math.max(0, lines.length - 1);
      }

      function setLineReviewCursor(layoutId, lineIndex, { persist = true } = {}) {
        const normalizedLayoutId = Number(layoutId);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          return;
        }
        const output = outputByLayoutId(normalizedLayoutId);
        if (!output) {
          return;
        }
        const lines = logicalLinesForOutput(output);
        const safeLineIndex = Math.max(0, Math.min(lines.length - 1, Number(lineIndex) || 0));
        state.lineCursorByLayoutId[String(normalizedLayoutId)] = safeLineIndex;
        if (persist) {
          persistDraftState();
        }
      }

      function currentLineReviewIndex(layoutId) {
        const output = outputByLayoutId(layoutId);
        if (!output) {
          return 0;
        }
        const lines = logicalLinesForOutput(output);
        const stored = Number(state.lineCursorByLayoutId[String(layoutId)]);
        if (!Number.isInteger(stored)) {
          return Math.max(0, Math.min(lines.length - 1, firstUnapprovedLineIndex(layoutId)));
        }
        return Math.max(0, Math.min(lines.length - 1, stored));
      }

      function reviewProgressSummary() {
        let requiredTotal = 0;
        let approvedTotal = 0;
        for (const output of state.outputs) {
          if (!lineReviewRequiredOutput(output)) {
            continue;
          }
          const lines = logicalLinesForOutput(output);
          requiredTotal += lines.length;
          approvedTotal += normalizeApprovedLineIndexes(output.layout_id, lines.length).length;
        }
        const missingTotal = Math.max(0, requiredTotal - approvedTotal);
        return {
          requiredTotal,
          approvedTotal,
          missingTotal,
          complete: requiredTotal === 0 || missingTotal === 0,
        };
      }

      function preferredInitialOutput() {
        const firstRequired = state.outputs.find((output) => lineReviewRequiredOutput(output));
        if (firstRequired) {
          return firstRequired;
        }
        return state.outputs[0] || null;
      }

      function firstPendingLineReviewOutput() {
        for (const output of sortedLineReviewOutputs()) {
          if (!isLineReviewOutputFullyApproved(output)) {
            return output;
          }
        }
        return null;
      }

      function sortedLineReviewOutputs() {
        return state.outputs
          .filter((output) => lineReviewRequiredOutput(output))
          .slice()
          .sort((left, right) => {
            const orderDiff = Number(left.reading_order) - Number(right.reading_order);
            if (orderDiff !== 0) {
              return orderDiff;
            }
            return Number(left.layout_id) - Number(right.layout_id);
          });
      }

      function isLineReviewOutputFullyApproved(output) {
        if (!output || !lineReviewRequiredOutput(output)) {
          return true;
        }
        const lines = logicalLinesForOutput(output);
        return approvedLineSet(output.layout_id, lines.length).size >= lines.length;
      }

      function nextPendingLineReviewOutputAfter(layoutId) {
        const currentLayoutId = Number(layoutId);
        if (!Number.isInteger(currentLayoutId) || currentLayoutId <= 0) {
          return null;
        }
        let seenCurrent = false;
        for (const output of sortedLineReviewOutputs()) {
          if (!seenCurrent) {
            if (Number(output.layout_id) === currentLayoutId) {
              seenCurrent = true;
            }
            continue;
          }
          if (isLineReviewOutputFullyApproved(output)) {
            continue;
          }
          return output;
        }
        return null;
      }

      function moveToNextPendingLineReviewOutput(currentLayoutId) {
        const nextOutput = nextPendingLineReviewOutputAfter(currentLayoutId);
        if (!nextOutput) {
          return false;
        }
        const nextLayoutId = Number(nextOutput.layout_id);
        setLineReviewCursor(nextLayoutId, firstUnapprovedLineIndex(nextLayoutId), { persist: true });
        selectOutput(nextLayoutId, { scrollImageToLayout: true, isUserSelection: true });
        return true;
      }

      function approveLine(layoutId, lineIndex, { approved = true, persist = true } = {}) {
        const output = outputByLayoutId(layoutId);
        if (!output) {
          return;
        }
        const lines = logicalLinesForOutput(output);
        const safeIndex = Math.max(0, Math.min(lines.length - 1, Number(lineIndex) || 0));
        const next = approvedLineSet(layoutId, lines.length);
        if (approved) {
          next.add(safeIndex);
        } else {
          next.delete(safeIndex);
        }
        updateApprovedLineIndexes(layoutId, Array.from(next), { persist });
      }

      function outputLineCount(layoutId) {
        const output = outputByLayoutId(layoutId);
        return countTextLines(output ? output.content : "");
      }

      function outputLookalikeLineIndexes(layoutId) {
        const output = outputByLayoutId(layoutId);
        if (!output || !Array.isArray(output.lookalike_warning_line_indexes)) {
          return [];
        }
        const deduped = new Set();
        for (const raw of output.lookalike_warning_line_indexes) {
          const value = Number(raw);
          if (Number.isInteger(value) && value >= 0) {
            deduped.add(value);
          }
        }
        return Array.from(deduped).sort((a, b) => a - b);
      }

      function appendLineMarkers(container, lineIndexes, totalLines, markerClassName) {
        if (!container || !Array.isArray(lineIndexes) || !lineIndexes.length) {
          return;
        }
        const safeTotalLines = Math.max(1, Number(totalLines) || 1);
        for (const rawIndex of lineIndexes) {
          const lineIndex = Number(rawIndex);
          if (!Number.isInteger(lineIndex) || lineIndex < 0) {
            continue;
          }
          const band = lineBandFromLineIndex(lineIndex, safeTotalLines);
          const marker = document.createElement("div");
          marker.className = markerClassName;
          marker.style.top = `${Math.max(0, Number(band.topRatio)) * 100}%`;
          marker.style.height = `${Math.max(0, Number(band.heightRatio)) * 100}%`;
          container.appendChild(marker);
        }
      }

      function clearLineHoverHighlights() {
        for (const marker of reconstructionSurface.querySelectorAll(".recon-line-highlight")) {
          marker.remove();
        }
        for (const marker of sourceOverlay.querySelectorAll(".box-line-highlight")) {
          marker.remove();
        }
      }

      function clearLineStatusHighlights() {
        for (const marker of reconstructionSurface.querySelectorAll(".recon-line-status")) {
          marker.remove();
        }
        for (const marker of sourceOverlay.querySelectorAll(".box-line-status")) {
          marker.remove();
        }
      }

      function appendLineStatusMarker(container, markerClassName, band) {
        if (!container || !markerClassName || !band) {
          return;
        }
        const top = Math.max(0, Math.min(1, Number(band.topRatio)));
        const height = Math.max(0, Math.min(1 - top, Number(band.heightRatio)));
        if (height <= 0) {
          return;
        }
        const marker = document.createElement("div");
        marker.className = markerClassName;
        marker.style.top = `${top * 100}%`;
        marker.style.height = `${height * 100}%`;
        container.appendChild(marker);
      }

      function applyLineStatusHighlights() {
        clearLineStatusHighlights();
        if (state.viewMode !== "line_by_line") {
          return;
        }
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        const lineCount = logicalLinesForOutput(output).length;
        if (lineCount <= 0) {
          return;
        }
        const approved = approvedLineSet(selectedLayoutId, lineCount);
        const currentIndex = currentLineReviewIndex(selectedLayoutId);
        const reconItem = reconstructionSurface.querySelector(`.recon-item[data-layout-id="${selectedLayoutId}"]`);
        const sourceBox = sourceOverlay.querySelector(`.box[data-layout-id="${selectedLayoutId}"]`);
        if (!reconItem && !sourceBox) {
          return;
        }
        for (let index = 0; index < lineCount; index += 1) {
          let statusClass = "";
          if (index === currentIndex) {
            statusClass = "current";
          } else if (approved.has(index)) {
            statusClass = "approved";
          } else {
            continue;
          }
          const band = resolveLineBandForLayout(selectedLayoutId, index);
          if (!band) {
            continue;
          }
          appendLineStatusMarker(reconItem, `recon-line-status ${statusClass}`, band);
          appendLineStatusMarker(sourceBox, `box-line-status ${statusClass}`, band);
        }
      }

      function applyLineHoverHighlights() {
        clearLineHoverHighlights();
        const hovered = state.hoveredLine;
        if (!hovered || typeof hovered !== "object") {
          return;
        }
        const layoutId = Number(hovered.layoutId);
        const topRatio = Number(hovered.topRatio);
        const heightRatio = Number(hovered.heightRatio);
        if (
          !Number.isInteger(layoutId) ||
          layoutId <= 0 ||
          !Number.isFinite(topRatio) ||
          !Number.isFinite(heightRatio)
        ) {
          return;
        }
        const clampedTop = Math.max(0, Math.min(1, topRatio));
        const clampedHeight = Math.max(0, Math.min(1 - clampedTop, heightRatio));
        if (clampedHeight <= 0) {
          return;
        }

        const reconItem = reconstructionSurface.querySelector(`.recon-item[data-layout-id="${layoutId}"]`);
        if (reconItem) {
          const reconMarker = document.createElement("div");
          reconMarker.className = "recon-line-highlight";
          reconMarker.style.top = `${clampedTop * 100}%`;
          reconMarker.style.height = `${clampedHeight * 100}%`;
          reconItem.appendChild(reconMarker);
        }

        const sourceBox = sourceOverlay.querySelector(`.box[data-layout-id="${layoutId}"]`);
        if (sourceBox) {
          const sourceMarker = document.createElement("div");
          sourceMarker.className = "box-line-highlight";
          sourceMarker.style.top = `${clampedTop * 100}%`;
          sourceMarker.style.height = `${clampedHeight * 100}%`;
          sourceBox.appendChild(sourceMarker);
        }
      }

      function setExpandedEditorCaretToLine(layoutId, lineIndex) {
        const normalizedLayoutId = Number(layoutId);
        const normalizedLineIndex = Number(lineIndex);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          return false;
        }
        if (!Number.isFinite(normalizedLineIndex)) {
          return false;
        }
        if (Number(state.expandedEditorLayoutId) !== normalizedLayoutId || expandedEditor.hidden) {
          return false;
        }

        if (codeMirrorView && !expandedEditorCmHost.hidden) {
          const totalLines = Math.max(1, Number(codeMirrorView.state.doc.lines));
          const targetLine = Math.max(1, Math.min(totalLines, Math.floor(normalizedLineIndex) + 1));
          const currentLine = Number(codeMirrorView.state.doc.lineAt(codeMirrorView.state.selection.main.head).number);
          if (currentLine === targetLine) {
            return true;
          }
          const lineInfo = codeMirrorView.state.doc.line(targetLine);
          codeMirrorView.dispatch({
            selection: { anchor: lineInfo.from },
            scrollIntoView: true,
          });
          updateExpandedEditorStatusFromCodeMirror(codeMirrorView);
          return true;
        }

        const text = String(expandedEditorTextarea.value ?? "");
        const totalLines = countTextLines(text);
        const targetIndex = Math.max(0, Math.min(totalLines - 1, Math.floor(normalizedLineIndex)));
        const currentOffset = Number.isInteger(expandedEditorTextarea.selectionStart)
          ? expandedEditorTextarea.selectionStart
          : text.length;
        const currentIndex = lineIndexFromTextOffset(text, currentOffset);
        if (currentIndex === targetIndex) {
          return true;
        }
        const targetOffset = textOffsetForLineIndex(text, targetIndex);
        expandedEditorTextarea.setSelectionRange(targetOffset, targetOffset);
        updateExpandedEditorStatusFromTextarea();
        return true;
      }

      function setExpandedEditorSelectionRange(layoutId, selectionStart, selectionEnd) {
        const normalizedLayoutId = Number(layoutId);
        const start = Number(selectionStart);
        const end = Number(selectionEnd);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          return false;
        }
        if (!Number.isFinite(start) || !Number.isFinite(end)) {
          return false;
        }
        if (Number(state.expandedEditorLayoutId) !== normalizedLayoutId || expandedEditor.hidden) {
          return false;
        }

        if (codeMirrorView && !expandedEditorCmHost.hidden) {
          codeMirrorView.dispatch({
            selection: {
              anchor: Math.max(0, Math.floor(start)),
              head: Math.max(0, Math.floor(end)),
            },
            scrollIntoView: true,
          });
          updateExpandedEditorStatusFromCodeMirror(codeMirrorView);
          codeMirrorView.focus();
          syncHoveredLineFromExpandedEditor({ source: "editor" });
          return true;
        }

        const text = String(expandedEditorTextarea.value ?? "");
        const clampedStart = Math.max(0, Math.min(text.length, Math.floor(start)));
        const clampedEnd = Math.max(0, Math.min(text.length, Math.floor(end)));
        expandedEditorTextarea.setSelectionRange(clampedStart, clampedEnd);
        expandedEditorTextarea.focus();
        updateExpandedEditorStatusFromTextarea();
        syncHoveredLineFromExpandedEditor({ source: "editor" });
        return true;
      }

      function extractReconstructedTokenAtPoint(contentNode, clientX, clientY) {
        if (!(contentNode instanceof Element)) {
          return null;
        }
        let textNode = null;
        let offset = null;

        if (typeof document.caretPositionFromPoint === "function") {
          const caretPosition = document.caretPositionFromPoint(clientX, clientY);
          if (caretPosition && caretPosition.offsetNode && caretPosition.offsetNode.nodeType === Node.TEXT_NODE) {
            textNode = caretPosition.offsetNode;
            offset = caretPosition.offset;
          }
        } else if (typeof document.caretRangeFromPoint === "function") {
          const caretRange = document.caretRangeFromPoint(clientX, clientY);
          if (caretRange && caretRange.startContainer && caretRange.startContainer.nodeType === Node.TEXT_NODE) {
            textNode = caretRange.startContainer;
            offset = caretRange.startOffset;
          }
        }

        if (!(textNode instanceof Text)) {
          const selected = String(window.getSelection()?.toString() ?? "").trim();
          return selected || null;
        }
        if (!contentNode.contains(textNode)) {
          return null;
        }
        const bounds = tokenBoundsAtOffset(textNode.textContent ?? "", Number(offset));
        if (!bounds || !bounds.token) {
          return null;
        }
        return String(bounds.token).trim() || null;
      }

      function selectTokenInExpandedEditor(layoutId, rawToken, preferredLineIndex = null) {
        const normalizedLayoutId = Number(layoutId);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          return false;
        }
        if (Number(state.expandedEditorLayoutId) !== normalizedLayoutId || expandedEditor.hidden) {
          return false;
        }
        const output = outputByLayoutId(normalizedLayoutId);
        if (!output) {
          return false;
        }
        const token = String(rawToken ?? "").replace(/\u00A0/g, " ").trim();
        if (!token) {
          return false;
        }
        const content = String(output.content ?? "");
        const preferredOffset = Number.isFinite(Number(preferredLineIndex))
          ? textOffsetForLineIndex(content, Number(preferredLineIndex))
          : 0;
        const wholeWord = /[\p{L}\p{N}_]/u.test(token);
        const match = findBestTokenOccurrence(content, token, {
          preferredOffset,
          wholeWord,
        });
        if (!match) {
          return false;
        }
        return setExpandedEditorSelectionRange(normalizedLayoutId, match.start, match.end);
      }

      function selectTokenInExpandedEditorWithRetry(layoutId, token, preferredLineIndex = null, retries = 6) {
        const applied = selectTokenInExpandedEditor(layoutId, token, preferredLineIndex);
        if (applied && codeMirrorView && !expandedEditorCmHost.hidden) {
          return;
        }
        if (retries <= 0) {
          return;
        }
        window.setTimeout(() => {
          selectTokenInExpandedEditorWithRetry(layoutId, token, preferredLineIndex, retries - 1);
        }, 80);
      }

      function reconstructedContentNodeByLayout(layoutId) {
        const normalized = Number(layoutId);
        if (!Number.isInteger(normalized) || normalized <= 0) {
          return null;
        }
        return reconstructionSurface.querySelector(`.recon-item[data-layout-id="${normalized}"] .recon-item-content`);
      }

      function resolveLineBandForLayout(layoutId, lineIndex) {
        const normalizedLayoutId = Number(layoutId);
        const normalizedLineIndex = Number(lineIndex);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          return null;
        }
        if (!Number.isFinite(normalizedLineIndex)) {
          return null;
        }

        const contentNode = reconstructedContentNodeByLayout(normalizedLayoutId);
        if (contentNode) {
          const rect = contentNode.getBoundingClientRect();
          const lineHeight = lineHeightForContentNode(contentNode);
          if (rect && rect.height > 0 && lineHeight) {
            const renderedBand = computeApproxLineBandByIndex({
              lineIndex: Math.floor(normalizedLineIndex),
              contentHeight: rect.height,
              lineHeight,
              minLineHeight: 6,
            });
            if (renderedBand) {
              return renderedBand;
            }
          }
        }

        const totalLines = outputLineCount(normalizedLayoutId);
        return lineBandFromLineIndex(normalizedLineIndex, totalLines);
      }

      function syncExpandedEditorCaretFromHoveredLine({ source = null } = {}) {
        if (source === "editor" || expandedEditor.hidden) {
          return;
        }
        if (isCodeMirrorFocused() || document.activeElement === expandedEditorTextarea) {
          return;
        }
        const hovered = state.hoveredLine;
        if (!hovered || typeof hovered !== "object") {
          return;
        }
        const hoveredLayoutId = Number(hovered.layoutId);
        const hoveredLineIndex = Number(hovered.lineIndex);
        if (!Number.isInteger(hoveredLayoutId) || hoveredLayoutId <= 0 || !Number.isFinite(hoveredLineIndex)) {
          return;
        }
        setExpandedEditorCaretToLine(hoveredLayoutId, hoveredLineIndex);
      }

      function syncHoveredLineFromExpandedEditor({ source = "editor" } = {}) {
        if (expandedEditor.hidden) {
          return;
        }
        const layoutId = Number(state.expandedEditorLayoutId);
        if (!Number.isInteger(layoutId) || layoutId <= 0) {
          return;
        }

        let lineIndex = null;
        if (codeMirrorView && !expandedEditorCmHost.hidden) {
          const lineNumber = Number(codeMirrorView.state.doc.lineAt(codeMirrorView.state.selection.main.head).number);
          lineIndex = Number.isFinite(lineNumber) ? lineNumber - 1 : 0;
        } else {
          const text = String(expandedEditorTextarea.value ?? "");
          const caretOffset = Number.isInteger(expandedEditorTextarea.selectionStart)
            ? expandedEditorTextarea.selectionStart
            : text.length;
          lineIndex = lineIndexFromTextOffset(text, caretOffset);
        }

        const lineBand = resolveLineBandForLayout(layoutId, lineIndex);
        setHoveredLine(layoutId, lineBand, { source });
      }

      function setHoveredLine(layoutId, lineBand, { source = null } = {}) {
        const normalizedId = Number(layoutId);
        if (!Number.isInteger(normalizedId) || normalizedId <= 0 || !lineBand) {
          if (state.hoveredLine === null) {
            return;
          }
          state.hoveredLine = null;
          applyLineHoverHighlights();
          syncExpandedEditorCaretFromHoveredLine({ source });
          return;
        }
        const next = {
          layoutId: normalizedId,
          lineIndex: Number(lineBand.lineIndex),
          topRatio: Number(lineBand.topRatio),
          heightRatio: Number(lineBand.heightRatio),
        };
        const prev = state.hoveredLine;
        if (
          prev &&
          Number(prev.layoutId) === next.layoutId &&
          Number(prev.lineIndex) === next.lineIndex
        ) {
          return;
        }
        state.hoveredLine = next;
        applyLineHoverHighlights();
        if (state.viewMode === "line_by_line" && source === "line_review") {
          ensureFocusedLineVisible(next.layoutId, next, 8);
        }
        syncExpandedEditorCaretFromHoveredLine({ source });
      }

      function syncHoveredLineFromLineReviewCursor(layoutId) {
        const normalizedLayoutId = Number(layoutId);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          setHoveredLine(null, null, { source: "line_review" });
          return;
        }
        const output = outputByLayoutId(normalizedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          setHoveredLine(null, null, { source: "line_review" });
          return;
        }
        const lineIndex = currentLineReviewIndex(normalizedLayoutId);
        const lineBand = resolveLineBandForLayout(normalizedLayoutId, lineIndex);
        setHoveredLine(normalizedLayoutId, lineBand, { source: "line_review" });
      }

      function normalizeBBoxRect(bbox) {
        const rawX1 = Number(bbox?.x1);
        const rawY1 = Number(bbox?.y1);
        const rawX2 = Number(bbox?.x2);
        const rawY2 = Number(bbox?.y2);
        if (![rawX1, rawY1, rawX2, rawY2].every((value) => Number.isFinite(value))) {
          return null;
        }
        const x1 = Math.max(0, Math.min(1, Math.min(rawX1, rawX2)));
        const y1 = Math.max(0, Math.min(1, Math.min(rawY1, rawY2)));
        const x2 = Math.max(0, Math.min(1, Math.max(rawX1, rawX2)));
        const y2 = Math.max(0, Math.min(1, Math.max(rawY1, rawY2)));
        if (x2 <= x1 || y2 <= y1) {
          return null;
        }
        return { x1, y1, x2, y2 };
      }

      function resolveLineReviewSourceCrop(output, lineBand) {
        const normalizedRect = normalizeBBoxRect(output?.bbox);
        if (!normalizedRect || !lineBand) {
          return null;
        }
        const contentWidth = normalizedRect.x2 - normalizedRect.x1;
        const contentHeight = normalizedRect.y2 - normalizedRect.y1;
        if (contentWidth <= 0 || contentHeight <= 0) {
          return null;
        }
        const rawTop = contentHeight * Number(lineBand.topRatio);
        const rawHeight = Math.max(1e-6, contentHeight * Number(lineBand.heightRatio));
        if (!Number.isFinite(rawTop) || !Number.isFinite(rawHeight)) {
          return null;
        }
        const context = rawHeight * LINE_REVIEW_CONTEXT_RATIO;
        const localTop = Math.max(0, rawTop - context);
        const localBottom = Math.min(contentHeight, rawTop + rawHeight + context);
        const sourceHeight = Math.max(1e-6, localBottom - localTop);
        const sourceTop = normalizedRect.y1 + localTop;
        if (!Number.isFinite(sourceTop) || !Number.isFinite(sourceHeight)) {
          return null;
        }
        return {
          normalizedRect,
          contentWidth,
          sourceTop,
          sourceHeight,
        };
      }

      function resolveLineReviewDisplayGeometry(output, crop) {
        const normalizedRect = normalizeBBoxRect(output?.bbox);
        const contentWidth = Math.max(
          1e-6,
          normalizedRect ? normalizedRect.x2 - normalizedRect.x1 : 0.5,
        );
        let widthRatio = Math.min(LINE_REVIEW_MAX_WIDTH_RATIO, Math.max(0.18, contentWidth));
        let heightPx = LINE_REVIEW_TARGET_HEIGHT_PX;
        if (crop && lineReviewReel instanceof HTMLElement) {
          const reelWidth = Number(lineReviewReel.clientWidth);
          const imageWidth = Number(pageImage.naturalWidth || pageImage.width || 0);
          const imageHeight = Number(pageImage.naturalHeight || pageImage.height || 0);
          const aspectFactor =
            Number.isFinite(reelWidth) && reelWidth > 0 &&
            Number.isFinite(imageWidth) && imageWidth > 0 &&
            Number.isFinite(imageHeight) && imageHeight > 0
              ? (reelWidth * crop.sourceHeight * (imageHeight / imageWidth)) / contentWidth
              : 0;
          if (Number.isFinite(aspectFactor) && aspectFactor > 0) {
            const minWidthRatioFromPx = Math.max(
              LINE_REVIEW_MIN_WIDTH_RATIO_FALLBACK,
              Math.min(LINE_REVIEW_MAX_WIDTH_RATIO, LINE_REVIEW_MIN_WIDTH_PX / reelWidth),
            );
            const widthForTarget = LINE_REVIEW_TARGET_HEIGHT_PX / aspectFactor;
            const widthForMinHeight = LINE_REVIEW_MIN_HEIGHT_PX / aspectFactor;
            const widthForMaxHeight = LINE_REVIEW_MAX_HEIGHT_PX / aspectFactor;
            const minAllowedWidth = Math.max(minWidthRatioFromPx, widthForMinHeight);
            const maxAllowedWidth = Math.min(LINE_REVIEW_MAX_WIDTH_RATIO, widthForMaxHeight);
            if (minAllowedWidth <= maxAllowedWidth) {
              widthRatio = Math.max(
                minAllowedWidth,
                Math.min(maxAllowedWidth, widthForTarget),
              );
            } else {
              widthRatio = Math.max(
                minWidthRatioFromPx,
                Math.min(LINE_REVIEW_MAX_WIDTH_RATIO, widthForTarget),
              );
            }
            heightPx = aspectFactor * widthRatio;
          }
        }
        const safeHeight = Math.max(
          LINE_REVIEW_MIN_HEIGHT_PX,
          Math.min(LINE_REVIEW_MAX_HEIGHT_PX, Number(heightPx) || LINE_REVIEW_TARGET_HEIGHT_PX),
        );
        const safeWidth = Math.max(
          LINE_REVIEW_MIN_WIDTH_RATIO_FALLBACK,
          Math.min(LINE_REVIEW_MAX_WIDTH_RATIO, Number(widthRatio) || 0.5),
        );
        return {
          leftRatio: Math.max(0, (1 - safeWidth) / 2),
          widthRatio: safeWidth,
          contentWidth,
          heightPx: safeHeight,
        };
      }

      function applyLineReviewLaneHeights(sourceLane, geminiLane, heightPx) {
        const lanes = [sourceLane, geminiLane];
        const safeHeight = Math.max(
          LINE_REVIEW_MIN_HEIGHT_PX,
          Math.min(LINE_REVIEW_MAX_HEIGHT_PX, Number(heightPx) || LINE_REVIEW_TARGET_HEIGHT_PX),
        );
        for (const lane of lanes) {
          if (lane instanceof HTMLElement) {
            lane.style.height = `${safeHeight}px`;
          }
        }
      }

      function renderLineReviewSourceLine(node, crop) {
        if (!(node instanceof Element) || !crop) {
          return;
        }
        const imageUrl = String(pageImage.currentSrc || pageImage.src || "");
        if (!imageUrl) {
          return;
        }
        const image = document.createElement("img");
        image.src = imageUrl;
        image.alt = "";
        image.draggable = false;
        image.style.width = `${100 / crop.contentWidth}%`;
        image.style.height = `${100 / crop.sourceHeight}%`;
        image.style.left = `${(-crop.normalizedRect.x1 / crop.contentWidth) * 100}%`;
        image.style.top = `${(-crop.sourceTop / crop.sourceHeight) * 100}%`;
        node.appendChild(image);
      }

      function applyLineReviewHorizontalGeometry(node, output, geometry = null) {
        if (!(node instanceof HTMLElement)) {
          return;
        }
        const fallbackRect = normalizeBBoxRect(output?.bbox);
        const fallbackWidth = Math.max(
          LINE_REVIEW_MIN_WIDTH_RATIO_FALLBACK,
          Math.min(LINE_REVIEW_MAX_WIDTH_RATIO, fallbackRect ? fallbackRect.x2 - fallbackRect.x1 : 0.6),
        );
        const leftRatio = Number.isFinite(Number(geometry?.leftRatio))
          ? Number(geometry.leftRatio)
          : Math.max(0, (1 - fallbackWidth) / 2);
        const widthRatio = Number.isFinite(Number(geometry?.widthRatio))
          ? Number(geometry.widthRatio)
          : fallbackWidth;
        node.style.left = `${Math.max(0, Math.min(1, leftRatio)) * 100}%`;
        node.style.width = `${Math.max(0, Math.min(1, widthRatio)) * 100}%`;
      }

      function ensureLineReviewTextMeasureNode() {
        if (lineReviewTextMeasureNode instanceof HTMLElement) {
          return lineReviewTextMeasureNode;
        }
        const node = document.createElement("span");
        node.style.position = "fixed";
        node.style.left = "-100000px";
        node.style.top = "-100000px";
        node.style.visibility = "hidden";
        node.style.pointerEvents = "none";
        node.style.whiteSpace = "pre";
        node.style.padding = "0";
        node.style.margin = "0";
        node.style.border = "0";
        document.body.appendChild(node);
        lineReviewTextMeasureNode = node;
        return node;
      }

      function measureLineReviewTextMetrics(
        lineNode,
        text,
        {
          fontSize = null,
          lineHeight = null,
          wordSpacing = 0,
          letterSpacing = 0,
        } = {},
      ) {
        if (!(lineNode instanceof HTMLElement)) {
          return { width: 0, height: 0 };
        }
        const measureNode = ensureLineReviewTextMeasureNode();
        const computed = window.getComputedStyle(lineNode);
        measureNode.style.fontFamily = computed.fontFamily;
        measureNode.style.fontSize = fontSize ? `${fontSize}px` : computed.fontSize;
        measureNode.style.fontWeight = computed.fontWeight;
        measureNode.style.fontStyle = computed.fontStyle;
        measureNode.style.fontStretch = computed.fontStretch;
        measureNode.style.lineHeight = lineHeight
          ? `${lineHeight}px`
          : computed.lineHeight;
        measureNode.style.letterSpacing = `${Number(letterSpacing) || 0}px`;
        measureNode.style.wordSpacing = `${Number(wordSpacing) || 0}px`;
        measureNode.textContent = String(text ?? "");
        const rect = measureNode.getBoundingClientRect();
        return {
          width: Number.isFinite(rect.width) ? rect.width : 0,
          height: Number.isFinite(rect.height) ? rect.height : 0,
        };
      }

      function fitLineReviewGeminiText(lineNode, text) {
        if (!(lineNode instanceof HTMLElement)) {
          return;
        }
        const rawText = String(text ?? "");
        lineNode.style.wordSpacing = "0px";
        lineNode.style.letterSpacing = "0px";
        lineNode.style.transform = "scaleX(1)";
        lineNode.style.fontSize = "";
        if (!rawText) {
          return;
        }
        const computed = window.getComputedStyle(lineNode);
        const paddingLeft = Number.parseFloat(computed.paddingLeft) || 0;
        const paddingRight = Number.parseFloat(computed.paddingRight) || 0;
        const paddingTop = Number.parseFloat(computed.paddingTop) || 0;
        const paddingBottom = Number.parseFloat(computed.paddingBottom) || 0;
        const availableWidth = Math.max(1, lineNode.clientWidth - paddingLeft - paddingRight);
        const availableHeight = Math.max(1, lineNode.clientHeight - paddingTop - paddingBottom);
        if (availableWidth <= 2) {
          return;
        }
        const targetWidth = Math.max(1, availableWidth - 2);

        const baseFontSize = Number.parseFloat(computed.fontSize) || 12;
        const baseLineHeightPx = Number.parseFloat(computed.lineHeight);
        const lineHeightRatio =
          Number.isFinite(baseLineHeightPx) && baseFontSize > 0
            ? baseLineHeightPx / baseFontSize
            : 1.2;
        const baseMetrics = measureLineReviewTextMetrics(lineNode, rawText, {
          fontSize: baseFontSize,
          lineHeight: baseFontSize * lineHeightRatio,
        });
        if (!Number.isFinite(baseMetrics.width) || baseMetrics.width <= 0) {
          return;
        }
        const maxByWidth = baseFontSize * (targetWidth / baseMetrics.width);
        const maxByHeight = availableHeight / Math.max(1e-6, lineHeightRatio);
        const fittedFontSize = Math.max(10, Math.min(56, maxByWidth, maxByHeight));
        lineNode.style.fontSize = `${fittedFontSize}px`;

        let currentWordSpacing = 0;
        let currentLetterSpacing = 0;
        const fittedLineHeightPx = fittedFontSize * lineHeightRatio;

        const tuneSpacing = (property, minValue, maxValue, iterations = 10) => {
          let low = Number(minValue);
          let high = Number(maxValue);
          let best = 0;
          let bestDiff = Number.POSITIVE_INFINITY;
          for (let idx = 0; idx < iterations; idx += 1) {
            const mid = (low + high) / 2;
            const metrics =
              property === "wordSpacing"
                ? measureLineReviewTextMetrics(lineNode, rawText, {
                    fontSize: fittedFontSize,
                    lineHeight: fittedLineHeightPx,
                    wordSpacing: mid,
                    letterSpacing: currentLetterSpacing,
                  })
                : measureLineReviewTextMetrics(lineNode, rawText, {
                    fontSize: fittedFontSize,
                    lineHeight: fittedLineHeightPx,
                    wordSpacing: currentWordSpacing,
                    letterSpacing: mid,
                  });
            const width = Number(metrics.width);
            if (!Number.isFinite(width) || width <= 0) {
              continue;
            }
            const diff = Math.abs(targetWidth - width);
            if (diff < bestDiff) {
              bestDiff = diff;
              best = mid;
            }
            if (width < targetWidth) {
              low = mid;
            } else {
              high = mid;
            }
          }
          lineNode.style[property] = `${best}px`;
          if (property === "wordSpacing") {
            currentWordSpacing = best;
          } else {
            currentLetterSpacing = best;
          }
        };

        const spacesCount = countStretchableSpaces(rawText);
        if (spacesCount > 0) {
          tuneSpacing("wordSpacing", -1.8, 4.8, 11);
        }

        const glyphsCount = countStretchableGlyphs(rawText);
        if (glyphsCount > 0) {
          tuneSpacing("letterSpacing", -0.22, 0.95, 11);
        }

        const adjustedMetrics = measureLineReviewTextMetrics(lineNode, rawText, {
          fontSize: fittedFontSize,
          lineHeight: fittedLineHeightPx,
          wordSpacing: currentWordSpacing,
          letterSpacing: currentLetterSpacing,
        });
        const adjustedWidth = Number(adjustedMetrics.width);
        if (!Number.isFinite(adjustedWidth) || adjustedWidth <= 0) {
          return;
        }

        const scale = targetWidth / adjustedWidth;
        let appliedScale = Math.max(0.72, Math.min(1.12, scale));
        lineNode.style.transform = `scaleX(${appliedScale})`;

        let postScaleWidth = adjustedWidth * appliedScale;
        if (postScaleWidth > targetWidth + 0.25) {
          const overflowScale = targetWidth / Math.max(1, adjustedWidth);
          appliedScale = Math.max(0.65, Math.min(1.02, overflowScale));
          lineNode.style.transform = `scaleX(${appliedScale})`;
          postScaleWidth = adjustedWidth * appliedScale;
        }
        if (postScaleWidth > targetWidth + 0.25) {
          const fontShrink = targetWidth / postScaleWidth;
          const currentFontSize = Number.parseFloat(lineNode.style.fontSize) || fittedFontSize;
          const nextFontSize = Math.max(9, currentFontSize * Math.max(0.82, fontShrink));
          lineNode.style.fontSize = `${nextFontSize}px`;
        } else if (postScaleWidth < targetWidth - 4 && spacesCount > 0) {
          if (Number.isFinite(currentWordSpacing)) {
            lineNode.style.wordSpacing = `${currentWordSpacing + 0.16}px`;
          }
        }
      }

      function openEditorForLine(layoutId, lineIndex) {
        const normalizedLayoutId = Number(layoutId);
        const normalizedLineIndex = Number(lineIndex);
        if (!Number.isInteger(normalizedLayoutId) || normalizedLayoutId <= 0) {
          return;
        }
        if (!Number.isFinite(normalizedLineIndex)) {
          return;
        }
        openExpandedEditor(normalizedLayoutId);
        if (setExpandedEditorCaretToLine(normalizedLayoutId, normalizedLineIndex)) {
          return;
        }
        let attempts = 8;
        const trySetCaret = () => {
          if (setExpandedEditorCaretToLine(normalizedLayoutId, normalizedLineIndex)) {
            return;
          }
          attempts -= 1;
          if (attempts <= 0) {
            return;
          }
          window.setTimeout(trySetCaret, 70);
        };
        trySetCaret();
      }

      function openEditorForCurrentLine() {
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        const lineIndex = currentLineReviewIndex(selectedLayoutId);
        openEditorForLine(selectedLayoutId, lineIndex);
      }

      function createLineReviewSlot({
        output,
        lineIndex,
        currentIndex,
        lineCount,
        lines,
        baselineLines,
        approved,
      }) {
        if (!Number.isInteger(lineIndex) || lineIndex < 0 || lineIndex >= lineCount) {
          return null;
        }
        const slot = document.createElement("div");
        slot.className = "line-review-slot is-clickable";
        slot.dataset.lineIndex = String(lineIndex);
        const isCurrent = lineIndex === currentIndex;
        if (isCurrent) {
          slot.classList.add("current");
        }
        if (approved.has(lineIndex)) {
          slot.classList.add("is-approved");
        }

        const sourceLane = document.createElement("div");
        sourceLane.className = "line-review-source-lane";
        const sourceLine = document.createElement("div");
        sourceLine.className = "line-review-source-line";
        sourceLane.appendChild(sourceLine);
        slot.appendChild(sourceLane);
        const lineBand =
          resolveLineBandForLayout(output.layout_id, lineIndex) ||
          lineBandFromLineIndex(lineIndex, lineCount);
        const sourceCrop = resolveLineReviewSourceCrop(output, lineBand);
        const displayGeometry = resolveLineReviewDisplayGeometry(output, sourceCrop);
        applyLineReviewHorizontalGeometry(sourceLine, output, displayGeometry);

        const geminiLane = document.createElement("div");
        geminiLane.className = "line-review-gemini-lane";
        const geminiLine = document.createElement("div");
        geminiLine.className = "line-review-gemini-line";
        geminiLane.appendChild(geminiLine);
        slot.appendChild(geminiLane);
        applyLineReviewLaneHeights(sourceLane, geminiLane, displayGeometry.heightPx);
        renderLineReviewSourceLine(sourceLine, sourceCrop);
        applyLineReviewHorizontalGeometry(geminiLine, output, displayGeometry);
        const currentText = String(lines[lineIndex] ?? "");
        const baselineText = String(baselineLines[lineIndex] ?? "");
        geminiLine.textContent = currentText || " ";
        geminiLine.dataset.rawText = currentText;
        geminiLine.classList.toggle("is-changed", baselineText !== currentText);
        if (isCurrent) {
          geminiLine.classList.add("is-editable");
          geminiLine.title = "Double-click to edit this line";
        }
        return slot;
      }

      function refitLineReviewGeminiLines() {
        if (!(lineReviewReel instanceof HTMLElement)) {
          return;
        }
        for (const lineNode of lineReviewReel.querySelectorAll(".line-review-gemini-line[data-raw-text]")) {
          fitLineReviewGeminiText(lineNode, lineNode.dataset.rawText || "");
        }
      }

      function renderLineReviewReel({
        output,
        currentIndex,
        lineCount,
        lines,
        baselineLines,
        approved,
      }) {
        if (!(lineReviewReel instanceof HTMLElement)) {
          return;
        }
        lineReviewReel.innerHTML = "";
        for (let offsetIndex = 0; offsetIndex < LINE_REVIEW_SLOT_OFFSETS.length; offsetIndex += 1) {
          const offset = LINE_REVIEW_SLOT_OFFSETS[offsetIndex];
          const lineIndex = currentIndex + offset;
          if (!Number.isInteger(lineIndex) || lineIndex < 0 || lineIndex >= lineCount) {
            continue;
          }
          const slot = createLineReviewSlot({
            output,
            lineIndex,
            currentIndex,
            lineCount,
            lines,
            baselineLines,
            approved,
          });
          if (slot) {
            lineReviewReel.appendChild(slot);
          }
        }
        requestAnimationFrame(() => {
          refitLineReviewGeminiLines();
        });
      }

      function renderLineReviewPanel() {
        if (!lineReviewPanel) {
          return;
        }
        if (state.viewMode !== "line_by_line") {
          lineReviewPanel.hidden = true;
          if (lineReviewReel) lineReviewReel.innerHTML = "";
          clearLineStatusHighlights();
          return;
        }
        const selectedLayoutId = Number(state.selectedLayoutId);
        const selectedOutput = outputByLayoutId(selectedLayoutId);
        if (!selectedOutput || !lineReviewRequiredOutput(selectedOutput)) {
          lineReviewPanel.hidden = true;
          if (lineReviewReel) lineReviewReel.innerHTML = "";
          clearLineStatusHighlights();
          return;
        }

        const lines = logicalLinesForOutput(selectedOutput);
        const lineCount = lines.length;
        const currentIndex = currentLineReviewIndex(selectedLayoutId);
        const approved = approvedLineSet(selectedLayoutId, lineCount);
        const approvedCount = approved.size;
        const isApproved = approved.has(currentIndex);

        lineReviewPanel.hidden = false;
        lineReviewLayout.textContent = `${selectedOutput.reading_order}. ${formatClassLabel(selectedOutput.class_name)}`;
        lineReviewProgress.textContent = `Line ${currentIndex + 1}/${lineCount} • Approved ${approvedCount}/${lineCount}`;

        const baselineLines = serverLogicalLinesForLayout(selectedLayoutId);
        renderLineReviewReel({
          output: selectedOutput,
          currentIndex,
          lineCount,
          lines,
          baselineLines,
          approved,
        });

        lineReviewPrevBtn.disabled = currentIndex <= 0 || state.reviewSubmitInProgress || state.reextractInProgress;
        const nextPendingOutput = nextPendingLineReviewOutputAfter(selectedLayoutId);
        const canAdvanceWithinCurrent = currentIndex < lineCount - 1;
        const canAdvanceToNextOutput = Boolean(nextPendingOutput);
        lineReviewNextBtn.disabled =
          state.reviewSubmitInProgress ||
          state.reextractInProgress ||
          (!canAdvanceWithinCurrent && !canAdvanceToNextOutput);
        const lineActionDisabled = state.reviewSubmitInProgress || state.reextractInProgress;
        lineReviewApproveBtn.disabled = lineActionDisabled;
        const currentBboxHasPending = approvedCount < lineCount;
        lineReviewApproveBboxBtn.disabled =
          lineActionDisabled || (!currentBboxHasPending && !canAdvanceToNextOutput);
        lineReviewResetBboxBtn.disabled = lineActionDisabled;
        lineReviewApproveBtn.classList.toggle("approved", isApproved);
        lineReviewApproveBtn.textContent = "Approve (A)";
        applyLineStatusHighlights();
      }

      function lineReviewLockActive() {
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        return Boolean(output && lineReviewRequiredOutput(output) && !lineReviewPanel?.hidden);
      }

      function moveLineReviewCursor(delta) {
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        const lines = logicalLinesForOutput(output);
        const currentIndex = currentLineReviewIndex(selectedLayoutId);
        const offset = Number(delta);
        if (
          Number.isFinite(offset) &&
          offset > 0 &&
          currentIndex >= lines.length - 1
        ) {
          updateApprovedLineIndexes(
            selectedLayoutId,
            Array.from({ length: lines.length }, (_, index) => index),
            { persist: true },
          );
          if (moveToNextPendingLineReviewOutput(selectedLayoutId)) {
            return;
          }
          setLineReviewCursor(selectedLayoutId, lines.length - 1, { persist: true });
          syncHoveredLineFromLineReviewCursor(selectedLayoutId);
          renderLineReviewPanel();
          return;
        }
        const nextIndex = Math.max(0, Math.min(lines.length - 1, currentIndex + offset));
        setLineReviewCursor(selectedLayoutId, nextIndex, { persist: true });
        syncHoveredLineFromLineReviewCursor(selectedLayoutId);
        renderLineReviewPanel();
      }

      function approveCurrentLineAndAdvance() {
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        const lineIndex = currentLineReviewIndex(selectedLayoutId);
        const lineCount = logicalLinesForOutput(output).length;
        const approved = approvedLineSet(selectedLayoutId, lineCount);
        if (!approved.has(lineIndex)) {
          approveLine(selectedLayoutId, lineIndex, { approved: true, persist: true });
        }
        if (lineIndex < lineCount - 1) {
          setLineReviewCursor(selectedLayoutId, lineIndex + 1, { persist: true });
          syncHoveredLineFromLineReviewCursor(selectedLayoutId);
          renderLineReviewPanel();
          return;
        }
        updateApprovedLineIndexes(
          selectedLayoutId,
          Array.from({ length: lineCount }, (_, index) => index),
          { persist: true },
        );
        if (moveToNextPendingLineReviewOutput(selectedLayoutId)) {
          return;
        }
        renderLineReviewPanel();
      }

      function unapproveCurrentLine() {
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        const lineIndex = currentLineReviewIndex(selectedLayoutId);
        approveLine(selectedLayoutId, lineIndex, { approved: false, persist: true });
        renderLineReviewPanel();
      }

      function approveAllLinesForSelectedBbox() {
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        const lines = logicalLinesForOutput(output);
        if (isLineReviewOutputFullyApproved(output)) {
          if (moveToNextPendingLineReviewOutput(selectedLayoutId)) {
            return;
          }
          renderLineReviewPanel();
          return;
        }
        updateApprovedLineIndexes(selectedLayoutId, Array.from({ length: lines.length }, (_, idx) => idx), {
          persist: true,
        });
        if (moveToNextPendingLineReviewOutput(selectedLayoutId)) {
          return;
        }
        renderLineReviewPanel();
      }

      function resetLineApprovalsForSelectedBbox() {
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        updateApprovedLineIndexes(selectedLayoutId, [], { persist: true });
        setLineReviewCursor(selectedLayoutId, 0, { persist: true });
        syncHoveredLineFromLineReviewCursor(selectedLayoutId);
        renderLineReviewPanel();
      }

      function applyReextractHoverStyles() {
        const hoveredId = Number(state.reextractHoverLayoutId);
        for (const box of sourceOverlay.querySelectorAll(".box[data-layout-id]")) {
          box.classList.toggle("modal-hovered", Number(box.dataset.layoutId) === hoveredId);
        }
        for (const item of reconstructionSurface.querySelectorAll(".recon-item[data-layout-id]")) {
          item.classList.toggle("modal-hovered", Number(item.dataset.layoutId) === hoveredId);
        }
      }

      function setReextractHoveredLayout(layoutId) {
        const normalized = Number(layoutId);
        state.reextractHoverLayoutId = Number.isInteger(normalized) && normalized > 0 ? normalized : null;
        applyReextractHoverStyles();
      }

      function isCaptionOutput(output) {
        return normalizeClassName(output?.class_name) === "caption";
      }

      function isCaptionTargetOutput(output) {
        const className = normalizeClassName(output?.class_name);
        return className === "table" || className === "picture" || className === "formula";
      }

      function normalizedRectFromBBox(bbox) {
        const x1 = Number(bbox?.x1);
        const y1 = Number(bbox?.y1);
        const x2 = Number(bbox?.x2);
        const y2 = Number(bbox?.y2);
        if (![x1, y1, x2, y2].every((value) => Number.isFinite(value))) {
          return null;
        }
        return {
          left: Math.max(0, Math.min(1, Math.min(x1, x2))),
          right: Math.max(0, Math.min(1, Math.max(x1, x2))),
          top: Math.max(0, Math.min(1, Math.min(y1, y2))),
          bottom: Math.max(0, Math.min(1, Math.max(y1, y2))),
        };
      }

      function shortestConnectorBetweenRects(sourceRect, targetRect) {
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
      }

      function renderSourceCaptionBindingLines() {
        sourceBindLinesLayer.innerHTML = "";
        const byLayoutId = new Map(
          state.outputs.map((output) => [Number(output.layout_id), output]),
        );
        const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
        const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
        marker.setAttribute("id", "source-bind-arrowhead");
        marker.setAttribute("markerWidth", "8");
        marker.setAttribute("markerHeight", "8");
        marker.setAttribute("refX", "7");
        marker.setAttribute("refY", "4");
        marker.setAttribute("orient", "auto");
        marker.setAttribute("markerUnits", "userSpaceOnUse");
        const arrowPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        arrowPath.setAttribute("d", "M0,0 L8,4 L0,8 Z");
        arrowPath.setAttribute("fill", "#496f98");
        arrowPath.setAttribute("fill-opacity", "0.75");
        marker.appendChild(arrowPath);
        defs.appendChild(marker);
        sourceBindLinesLayer.appendChild(defs);

        const selectedLayoutId = Number(state.selectedLayoutId);
        for (const output of state.outputs) {
          if (!isCaptionOutput(output)) {
            continue;
          }
          const captionRect = normalizedRectFromBBox(output.bbox);
          if (!captionRect) {
            continue;
          }
          const targetIds = Array.isArray(output.bound_target_ids) ? output.bound_target_ids : [];
          const isActiveCaption = Number(output.layout_id) === selectedLayoutId;
          for (const rawTargetId of targetIds) {
            const targetId = Number(rawTargetId);
            if (!Number.isInteger(targetId) || targetId <= 0) {
              continue;
            }
            const targetOutput = byLayoutId.get(targetId);
            if (!targetOutput || !isCaptionTargetOutput(targetOutput)) {
              continue;
            }
            const targetRect = normalizedRectFromBBox(targetOutput.bbox);
            if (!targetRect) {
              continue;
            }
            const connector = shortestConnectorBetweenRects(captionRect, targetRect);
            const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
            line.setAttribute("x1", `${(connector.source.x * 100).toFixed(3)}%`);
            line.setAttribute("y1", `${(connector.source.y * 100).toFixed(3)}%`);
            line.setAttribute("x2", `${(connector.target.x * 100).toFixed(3)}%`);
            line.setAttribute("y2", `${(connector.target.y * 100).toFixed(3)}%`);
            line.setAttribute("stroke", "#496f98");
            line.setAttribute("stroke-opacity", isActiveCaption ? "0.92" : "0.56");
            line.setAttribute("stroke-width", isActiveCaption ? "2.2" : "1.6");
            line.setAttribute("marker-end", "url(#source-bind-arrowhead)");
            sourceBindLinesLayer.appendChild(line);
          }
        }
      }

      function applySelectedStyles() {
        const selectedId = Number(state.selectedLayoutId);
        renderSourceCaptionBindingLines();
        for (const box of sourceOverlay.querySelectorAll(".box[data-layout-id]")) {
          box.classList.toggle("layout-selected", Number(box.dataset.layoutId) === selectedId);
        }
        for (const item of reconstructionSurface.querySelectorAll(".recon-item[data-layout-id]")) {
          item.classList.toggle("recon-selected", Number(item.dataset.layoutId) === selectedId);
        }
        for (const label of sourceLabelLayer.querySelectorAll(".box-label[data-layout-id]")) {
          const layoutId = Number(label.dataset.layoutId);
          if (layoutId === selectedId) {
            label.style.visibility = "";
            sourceSelectedLabelLayer.appendChild(label);
          }
        }
        for (const label of sourceSelectedLabelLayer.querySelectorAll(".box-label[data-layout-id]")) {
          const layoutId = Number(label.dataset.layoutId);
          if (layoutId !== selectedId) {
            sourceLabelLayer.appendChild(label);
          }
        }
        updateSourceLabelVisibilityForOverlap();
        applyReextractHoverStyles();
        applyLineStatusHighlights();
        applyLineHoverHighlights();
        applyFocusedStripOverlay();
        if (state.viewMode === "line_by_line") {
          syncHoveredLineFromLineReviewCursor(state.selectedLayoutId);
        } else {
          setHoveredLine(null, null, { source: "view_mode" });
        }
        renderLineReviewPanel();
      }

      function rectsIntersect(a, b) {
        if (!a || !b) {
          return false;
        }
        return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
      }

      function updateSourceLabelVisibilityForOverlap() {
        const overlayBoxes = Array.from(sourceOverlay.querySelectorAll(".box[data-layout-id]"))
          .map((box) => ({
            layoutId: Number(box.dataset.layoutId),
            rect: box.getBoundingClientRect(),
          }))
          .filter(
            (entry) =>
              Number.isInteger(entry.layoutId) &&
              entry.layoutId > 0 &&
              entry.rect &&
              entry.rect.width > 0 &&
              entry.rect.height > 0,
          );
        if (overlayBoxes.length === 0) {
          return;
        }
        for (const label of sourceLabelLayer.querySelectorAll(".box-label[data-layout-id]")) {
          const labelId = Number(label.dataset.layoutId);
          if (!Number.isInteger(labelId) || labelId <= 0) {
            label.style.visibility = "";
            continue;
          }
          const labelRect = label.getBoundingClientRect();
          const overlapsOtherBox = overlayBoxes.some(
            (entry) => entry.layoutId !== labelId && rectsIntersect(labelRect, entry.rect),
          );
          label.style.visibility = overlapsOtherBox ? "hidden" : "";
        }
      }

      function scrollViewportToLayout(
        layoutId,
        viewport,
        content,
        { preferVerticalCenter = false } = {},
      ) {
        if (!viewport || !content) {
          return false;
        }
        const output = outputByLayoutId(layoutId);
        return scrollViewportToBBox(output?.bbox, viewport, content, { preferVerticalCenter });
      }

      function lineBBoxForOutputBand(output, lineBand) {
        const rect = normalizeBBoxRect(output?.bbox);
        if (!rect || !lineBand) {
          return null;
        }
        const topRatio = Math.max(0, Math.min(1, Number(lineBand.topRatio)));
        const heightRatio = Math.max(0, Math.min(1 - topRatio, Number(lineBand.heightRatio)));
        if (heightRatio <= 0) {
          return null;
        }
        const bboxHeight = rect.bottom - rect.top;
        if (!(bboxHeight > 0)) {
          return null;
        }
        const y1 = rect.top + bboxHeight * topRatio;
        const y2 = rect.top + bboxHeight * (topRatio + heightRatio);
        return {
          x1: rect.left,
          y1,
          x2: rect.right,
          y2,
        };
      }

      function scrollViewportToBBox(
        bbox,
        viewport,
        content,
        { preferVerticalCenter = false } = {},
      ) {
        if (!viewport || !content || !bbox) {
          return false;
        }
        const target = computeViewportAutoCenterTarget({
          bbox,
          contentWidth: content.clientWidth,
          contentHeight: content.clientHeight,
          viewportWidth: viewport.clientWidth,
          viewportHeight: viewport.clientHeight,
          currentLeft: viewport.scrollLeft,
          currentTop: viewport.scrollTop,
          horizontalMarginRatio: 0.2,
          verticalMarginRatio: preferVerticalCenter ? 0.3 : 0.22,
          maxMarginPx: 240,
          preferVerticalCenter,
          centerThresholdPx: 10,
        });
        if (!target) return false;
        viewport.scrollLeft = target.left;
        viewport.scrollTop = target.top;
        return true;
      }

      function scrollVisiblePreviewToLayout(layoutId, { preferVerticalCenter = false } = {}) {
        let changed = false;
        if (state.panelVisibility.source) {
          changed =
            scrollViewportToLayout(layoutId, sourceViewport, sourceWrap, { preferVerticalCenter }) || changed;
        }
        if (state.panelVisibility.reconstructed) {
          changed =
            scrollViewportToLayout(layoutId, reconstructedViewport, reconstructedWrap, {
              preferVerticalCenter,
            }) || changed;
        }
        return changed;
      }

      function scrollVisiblePreviewToFocusedLine(layoutId, lineBand, { preferVerticalCenter = true } = {}) {
        const output = outputByLayoutId(layoutId);
        const lineBBox = lineBBoxForOutputBand(output, lineBand);
        if (!lineBBox) {
          return false;
        }
        let changed = false;
        if (state.panelVisibility.source) {
          changed =
            scrollViewportToBBox(lineBBox, sourceViewport, sourceWrap, { preferVerticalCenter }) || changed;
        }
        if (state.panelVisibility.reconstructed) {
          changed =
            scrollViewportToBBox(lineBBox, reconstructedViewport, reconstructedWrap, {
              preferVerticalCenter,
            }) || changed;
        }
        return changed;
      }

      function ensureLayoutVisible(layoutId, retries = 8, { preferVerticalCenter = false } = {}) {
        if (scrollVisiblePreviewToLayout(layoutId, { preferVerticalCenter })) return;
        if (retries <= 0) return;
        requestAnimationFrame(() => {
          ensureLayoutVisible(layoutId, retries - 1, { preferVerticalCenter });
        });
      }

      function ensureFocusedLineVisible(layoutId, lineBand, retries = 8, { preferVerticalCenter = true } = {}) {
        if (scrollVisiblePreviewToFocusedLine(layoutId, lineBand, { preferVerticalCenter })) {
          return;
        }
        if (retries <= 0) {
          return;
        }
        requestAnimationFrame(() => {
          ensureFocusedLineVisible(layoutId, lineBand, retries - 1, { preferVerticalCenter });
        });
      }

      function selectOutput(layoutId, { scrollImageToLayout = false, isUserSelection = false } = {}) {
        const normalized = Number(layoutId);
        if (!Number.isInteger(normalized) || normalized <= 0) return;
        const output = outputByLayoutId(normalized);
        if (!output) return;
        state.selectedLayoutId = normalized;
        if (isUserSelection) {
          state.explicitSelectedLayoutId = normalized;
        }
        if (lineReviewRequiredOutput(output) && !Number.isInteger(Number(state.lineCursorByLayoutId[String(normalized)]))) {
          setLineReviewCursor(normalized, firstUnapprovedLineIndex(normalized), { persist: false });
        }
        applySelectedStyles();
        const preferVerticalCenter = state.viewMode === "line_by_line";
        const shouldAutoCenter = scrollImageToLayout || (isUserSelection && preferVerticalCenter);
        if (shouldAutoCenter) {
          ensureLayoutVisible(normalized, 8, { preferVerticalCenter });
        }
      }

      function boxStyle(bbox) {
        return {
          left: `${Number(bbox.x1) * 100}%`,
          top: `${Number(bbox.y1) * 100}%`,
          width: `${(Number(bbox.x2) - Number(bbox.x1)) * 100}%`,
          height: `${(Number(bbox.y2) - Number(bbox.y1)) * 100}%`,
        };
      }

      function appendPlainContent(container, content, className) {
        const block = document.createElement("div");
        block.className = `recon-item-content ${className}`;
        block.textContent = String(content ?? "");
        container.appendChild(block);
        return block;
      }

      function isPictureOutput(output) {
        const className = String(output?.class_name || "").trim().toLowerCase();
        return className === "picture";
      }

      function appendPictureCropContent(container, output) {
        const cropStyle = computeReconstructedImageCropStyle(output?.bbox);
        const sourceUrl = String(pageImage.currentSrc || pageImage.src || "");
        if (!cropStyle || !sourceUrl) {
          return appendPlainContent(container, "Picture region.", "skip");
        }
        const block = document.createElement("div");
        block.className = "recon-item-content picture-crop";
        const image = document.createElement("img");
        image.className = "recon-item-crop-image";
        image.src = sourceUrl;
        image.alt = "";
        image.draggable = false;
        image.style.width = `${cropStyle.widthPercent}%`;
        image.style.height = `${cropStyle.heightPercent}%`;
        image.style.left = `${cropStyle.leftPercent}%`;
        image.style.top = `${cropStyle.topPercent}%`;
        block.appendChild(image);
        container.appendChild(block);
        return block;
      }

      function scheduleReconstructionRefit() {
        if (reconstructionRefitScheduled) {
          return;
        }
        reconstructionRefitScheduled = true;
        requestAnimationFrame(() => {
          reconstructionRefitScheduled = false;
          refitReconstructedContent();
        });
      }

      function cloneAllowedTableNode(node) {
        const allowedTags = new Set(["table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption"]);
        if (!(node instanceof Element)) {
          return null;
        }
        const tagName = node.tagName.toLowerCase();
        if (!allowedTags.has(tagName)) {
          return null;
        }
        const cloned = document.createElement(tagName);
        for (const child of Array.from(node.childNodes)) {
          if (child.nodeType === Node.TEXT_NODE) {
            cloned.appendChild(document.createTextNode(child.textContent || ""));
            continue;
          }
          if (!(child instanceof Element)) {
            continue;
          }
          const clonedChild = cloneAllowedTableNode(child);
          if (clonedChild) {
            cloned.appendChild(clonedChild);
          } else {
            cloned.appendChild(document.createTextNode(child.textContent || ""));
          }
        }
        return cloned;
      }

      function appendStructuredContent(container, output) {
        const format = String(output.output_format || "").toLowerCase();
        const content = String(output.content ?? "");
        if (isPictureOutput(output)) {
          return appendPictureCropContent(container, output);
        }
        if (format === "skip") {
          return appendPlainContent(container, "Skipped region (no text extraction).", "skip");
        }
        if (format === "html") {
          const parser = new DOMParser();
          const doc = parser.parseFromString(`<body>${content}</body>`, "text/html");
          const table = doc.body.querySelector("table");
          if (table) {
            const wrapper = document.createElement("div");
            wrapper.className = "recon-item-content html";
            const safeTable = cloneAllowedTableNode(table);
            if (safeTable) {
              wrapper.appendChild(safeTable);
              container.appendChild(wrapper);
              return wrapper;
            }
          }
          return appendPlainContent(container, content, "html");
        }
        if (format === "latex") {
          const block = appendPlainContent(container, content, "latex");
          renderLatexInto(block, content, { onRendered: scheduleReconstructionRefit });
          return block;
        }
        if (format === "markdown") {
          const mode = normalizeReconstructedRenderMode(state.reconstructedRenderMode);
          const className = mode === "markdown" ? "markdown" : "markdown raw-view";
          const block = appendPlainContent(container, content, className);
          const hasMarkdownTable = containsMarkdownTable(content);
          if (hasMarkdownTable) {
            container.classList.add("markdown-table-warning");
            container.title = "Markdown table detected in OCR output. Re-extract this layout.";
            const badge = document.createElement("span");
            badge.className = "recon-warning-badge";
            badge.textContent = "TABLE MD";
            container.appendChild(badge);
          }
          const lookalikeCount = Number(output.lookalike_warning_count || 0);
          if (lookalikeCount > 0) {
            container.classList.add("lookalike-warning");
            const badge = document.createElement("span");
            badge.className = "recon-warning-badge lookalike";
            badge.textContent = `LOOK ${lookalikeCount}`;
            badge.title = `${lookalikeCount} suspicious lookalike token(s) detected`;
            container.appendChild(badge);
          }
          if (mode === "markdown") {
            renderMarkdownInto(block, content, { onRendered: scheduleReconstructionRefit });
          }
          return block;
        }
        return appendPlainContent(container, content, "markdown");
      }

      function contentFitsInItem(contentNode, availableWidth, availableHeight) {
        const maxWidth = Math.ceil(availableWidth + 1);
        const maxHeight = Math.ceil(availableHeight + 1);
        return contentNode.scrollWidth <= maxWidth && contentNode.scrollHeight <= maxHeight;
      }

      function measureIntrinsicContentWidth(contentNode) {
        if (!contentNode) {
          return 0;
        }
        const previousWidth = contentNode.style.width;
        const previousMaxWidth = contentNode.style.maxWidth;
        contentNode.style.width = "max-content";
        contentNode.style.maxWidth = "none";
        const measured = Number(contentNode.scrollWidth);
        contentNode.style.width = previousWidth;
        contentNode.style.maxWidth = previousMaxWidth;
        if (!Number.isFinite(measured) || measured <= 0) {
          return 0;
        }
        return measured;
      }

      function lineHeightForContentNode(contentNode) {
        if (!contentNode) {
          return null;
        }
        const computed = window.getComputedStyle(contentNode);
        const parsed = Number.parseFloat(computed.lineHeight);
        if (Number.isFinite(parsed) && parsed > 0) {
          return parsed;
        }
        const fallback = Number.parseFloat(computed.fontSize) * 1.25;
        if (Number.isFinite(fallback) && fallback > 0) {
          return fallback;
        }
        return null;
      }

      function updateHoveredLineFromPointer(contentNode, layoutId, clientY) {
        if (!contentNode) {
          return;
        }
        const rect = contentNode.getBoundingClientRect();
        if (!rect || rect.height <= 0) {
          return;
        }
        const offsetY = Number(clientY) - rect.top;
        const lineHeight = lineHeightForContentNode(contentNode);
        let band = null;
        if (lineHeight) {
          band = computeApproxLineBand({
            offsetY,
            contentHeight: rect.height,
            lineHeight,
            minLineHeight: 6,
          });
        }
        if (!band) {
          const totalLines = outputLineCount(layoutId);
          const safeOffsetY = Math.max(0, Math.min(rect.height - 0.001, offsetY));
          const roughIndex = Math.floor((safeOffsetY / rect.height) * totalLines);
          band = resolveLineBandForLayout(layoutId, roughIndex);
        }
        setHoveredLine(layoutId, band, { source: "reconstructed" });
      }

      function isInteractiveTextTarget(target) {
        if (!(target instanceof Element)) {
          return false;
        }
        return Boolean(target.closest("textarea, input, select, [contenteditable='true'], [role='textbox']"));
      }

      function moveHoveredLineWithKeyboard(step) {
        const delta = Number(step);
        if (!Number.isInteger(delta) || delta === 0) {
          return false;
        }
        const hoveredLayoutId = Number(state.hoveredLine?.layoutId);
        const selectedLayoutId = Number(state.selectedLayoutId);
        const candidateLayoutId =
          Number.isInteger(hoveredLayoutId) && hoveredLayoutId > 0 ? hoveredLayoutId : selectedLayoutId;
        if (!Number.isInteger(candidateLayoutId) || candidateLayoutId <= 0) {
          return false;
        }
        const output = outputByLayoutId(candidateLayoutId);
        if (!output || !isLineSyncEnabledOutputFormat(output.output_format)) {
          return false;
        }
        const contentNode = reconstructedContentNodeByLayout(candidateLayoutId);
        if (!contentNode) {
          return false;
        }
        const rect = contentNode.getBoundingClientRect();
        const lineHeight = lineHeightForContentNode(contentNode);
        if (!rect || rect.height <= 0 || !lineHeight) {
          return false;
        }

        const currentIndex =
          state.hoveredLine && Number(state.hoveredLine.layoutId) === candidateLayoutId
            ? Number(state.hoveredLine.lineIndex)
            : 0;
        const nextBand = computeApproxLineBandByIndex({
          lineIndex: (Number.isInteger(currentIndex) ? currentIndex : 0) + delta,
          contentHeight: rect.height,
          lineHeight,
          minLineHeight: 6,
        });
        if (!nextBand) {
          return false;
        }
        setHoveredLine(candidateLayoutId, nextBand, { source: "keyboard" });
        return true;
      }

      function fitReconstructedContent(item, contentNode, output) {
        if (!item || !contentNode || !output) {
          return;
        }
        const format = String(output.output_format || "").toLowerCase();
        if (format === "skip") {
          return;
        }

        const availableWidth = Math.max(1, item.clientWidth - 2);
        const availableHeight = Math.max(1, item.clientHeight - 2);
        if (availableWidth <= 4 || availableHeight <= 4) {
          return;
        }

        contentNode.style.width = `${availableWidth}px`;
        contentNode.style.height = `${availableHeight}px`;
        contentNode.style.transform = "scaleX(1)";
        contentNode.style.wordSpacing = "0px";
        contentNode.style.letterSpacing = "0px";

        const lineHeight = reconstructionLineHeight(format);
        contentNode.style.lineHeight = String(lineHeight);

        const maxFontSize = Math.max(6, Math.min(availableWidth, availableHeight));
        const finalSize = findMaxFittingFontSize({
          minFontSize: 6,
          maxFontSize,
          iterations: 14,
          fitsAtFontSize(fontSize) {
            contentNode.style.fontSize = `${fontSize}px`;
            return contentFitsInItem(contentNode, availableWidth, availableHeight);
          },
        });
        contentNode.style.fontSize = `${finalSize}px`;
        contentNode.style.lineHeight = String(lineHeight);

        if (format === "markdown") {
          const spacesCount = countStretchableSpaces(String(output.content ?? ""));
          const intrinsicWidth = measureIntrinsicContentWidth(contentNode);
          const maxWordSpacing = reconstructionWordSpacing({
            measuredContentWidth: intrinsicWidth,
            availableWidth,
            spacesCount,
            maxWordSpacing: 3.5,
            minGainRatio: 0.01,
          });
          if (maxWordSpacing > 0) {
            let low = 0;
            let high = maxWordSpacing;
            let best = 0;
            for (let index = 0; index < 10; index += 1) {
              const mid = (low + high) / 2;
              contentNode.style.wordSpacing = `${mid}px`;
              if (contentFitsInItem(contentNode, availableWidth, availableHeight)) {
                best = mid;
                low = mid;
              } else {
                high = mid;
              }
            }
            contentNode.style.wordSpacing = `${best}px`;
          }

          const glyphsCount = countStretchableGlyphs(String(output.content ?? ""));
          const intrinsicAfterWordSpacing = measureIntrinsicContentWidth(contentNode);
          const maxLetterSpacing = reconstructionLetterSpacing({
            measuredContentWidth: intrinsicAfterWordSpacing,
            availableWidth,
            glyphsCount,
            maxLetterSpacing: 0.8,
            minGainRatio: 0.004,
          });
          if (maxLetterSpacing > 0) {
            let low = 0;
            let high = maxLetterSpacing;
            let best = 0;
            for (let index = 0; index < 10; index += 1) {
              const mid = (low + high) / 2;
              contentNode.style.letterSpacing = `${mid}px`;
              if (contentFitsInItem(contentNode, availableWidth, availableHeight)) {
                best = mid;
                low = mid;
              } else {
                high = mid;
              }
            }
            contentNode.style.letterSpacing = `${best}px`;
          }
        }

        if (format !== "html") {
          const intrinsicWidth = measureIntrinsicContentWidth(contentNode);
          const horizontalScale = reconstructionHorizontalScale({
            measuredContentWidth: intrinsicWidth,
            availableWidth,
            maxScale: 1.12,
            minGainRatio: 0.01,
          });
          contentNode.style.transform = `scaleX(${horizontalScale})`;
        } else {
          contentNode.style.transform = "scaleX(1)";
        }
      }

      function refitReconstructedContent() {
        if (!state.outputs.length) {
          return;
        }
        const outputsById = new Map(state.outputs.map((output) => [Number(output.layout_id), output]));
        for (const item of reconstructionSurface.querySelectorAll(".recon-item[data-layout-id]")) {
          const layoutId = Number(item.dataset.layoutId);
          const output = outputsById.get(layoutId);
          if (!output) {
            continue;
          }
          const contentNode = item.querySelector(".recon-item-content");
          if (!contentNode) {
            continue;
          }
          fitReconstructedContent(item, contentNode, output);
        }
      }

      function renderReconstruction() {
        state.hoveredLine = null;
        reconstructionSurface.innerHTML = "";
        for (const output of state.outputs) {
          const color = colorForClass(output.class_name);
          const item = document.createElement("div");
          item.className = "recon-item";
          item.dataset.layoutId = String(output.layout_id);
          const style = boxStyle(output.bbox);
          item.style.left = style.left;
          item.style.top = style.top;
          item.style.width = style.width;
          item.style.height = style.height;
          item.style.borderColor = hexToRgba(color, 0.6);
          item.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) return;
            selectOutput(output.layout_id, { isUserSelection: true });
          });
          item.addEventListener("dblclick", (event) => {
            event.preventDefault();
            openExpandedEditor(output.layout_id);
          });

          const showRestore = hasLocalDraftForLayout(state.localEditsByLayoutId, output.layout_id);
          if (showRestore) {
            const restoreBtn = document.createElement("button");
            restoreBtn.className = "secondary recon-restore-btn";
            restoreBtn.type = "button";
            restoreBtn.textContent = "↺";
            restoreBtn.title = "Restore value";
            restoreBtn.setAttribute("aria-label", "Restore value");
            restoreBtn.disabled = isReconstructedRestoreDisabled({
              reviewSubmitInProgress: state.reviewSubmitInProgress,
              reextractInProgress: state.reextractInProgress,
              outputFormat: output.output_format,
            });
            restoreBtn.addEventListener("pointerdown", (event) => {
              event.stopPropagation();
            });
            restoreBtn.addEventListener("click", (event) => {
              event.stopPropagation();
              restoreOutputByLayoutId(output.layout_id);
            });
            item.appendChild(restoreBtn);
          }

          const contentNode = appendStructuredContent(item, output);
          const warningLineIndexes = outputLookalikeLineIndexes(output.layout_id);
          if (warningLineIndexes.length > 0) {
            appendLineMarkers(
              item,
              warningLineIndexes,
              outputLineCount(output.layout_id),
              "recon-line-warning",
            );
          }
          if (isLineSyncEnabledOutputFormat(output.output_format)) {
            contentNode.addEventListener("pointermove", (event) => {
              if (lineReviewLockActive()) {
                return;
              }
              updateHoveredLineFromPointer(contentNode, output.layout_id, event.clientY);
            });
            contentNode.addEventListener("pointerleave", () => {
              if (lineReviewLockActive()) {
                return;
              }
              setHoveredLine(null, null, { source: "reconstructed" });
            });
          } else {
            contentNode.addEventListener("pointermove", () => {
              if (lineReviewLockActive()) {
                return;
              }
              setHoveredLine(null, null, { source: "reconstructed" });
            });
            contentNode.addEventListener("pointerleave", () => {
              if (lineReviewLockActive()) {
                return;
              }
              setHoveredLine(null, null, { source: "reconstructed" });
            });
          }
          contentNode.addEventListener("dblclick", (event) => {
            const token = extractReconstructedTokenAtPoint(contentNode, event.clientX, event.clientY);
            if (!token) {
              return;
            }
            event.preventDefault();
            event.stopPropagation();
            const preferredLineIndex =
              state.hoveredLine && Number(state.hoveredLine.layoutId) === Number(output.layout_id)
                ? Number(state.hoveredLine.lineIndex)
                : null;
            openExpandedEditor(output.layout_id);
            selectTokenInExpandedEditorWithRetry(output.layout_id, token, preferredLineIndex);
          });
          reconstructionSurface.appendChild(item);
          fitReconstructedContent(item, contentNode, output);
        }
        applySelectedStyles();
      }

      function renderOverlay() {
        sortOutputsInPlace();
        sourceBindLinesLayer.innerHTML = "";
        sourceLabelLayer.innerHTML = "";
        sourceSelectedLabelLayer.innerHTML = "";
        sourceOverlay.innerHTML = "";
        const selectedId = Number(state.selectedLayoutId);
        for (const output of state.outputs) {
          const color = colorForClass(output.class_name);
          const box = document.createElement("div");
          box.className = "box";
          box.dataset.layoutId = String(output.layout_id);
          const style = boxStyle(output.bbox);
          box.style.left = style.left;
          box.style.top = style.top;
          box.style.width = style.width;
          box.style.height = style.height;
          box.style.borderColor = color;
          box.style.background = hexToRgba(color, 0.16);
          box.addEventListener("pointerdown", (event) => {
            if (event.button !== 0) return;
            selectOutput(output.layout_id, { isUserSelection: true });
          });
          box.addEventListener("dblclick", (event) => {
            event.preventDefault();
            openExpandedEditor(output.layout_id);
          });
          box.addEventListener("pointermove", (event) => {
            if (lineReviewLockActive()) {
              return;
            }
            if (!isLineSyncEnabledOutputFormat(output.output_format)) {
              setHoveredLine(null, null, { source: "source" });
              return;
            }
            const rect = box.getBoundingClientRect();
            if (!rect || rect.height <= 0) {
              return;
            }
            const safeOffsetY = Math.max(0, Math.min(rect.height - 0.001, Number(event.clientY) - rect.top));
            const totalLines = outputLineCount(output.layout_id);
            const roughIndex = Math.floor((safeOffsetY / rect.height) * totalLines);
            const band = resolveLineBandForLayout(output.layout_id, roughIndex);
            setHoveredLine(output.layout_id, band, { source: "source" });
          });
          box.addEventListener("pointerleave", () => {
            if (lineReviewLockActive()) {
              return;
            }
            setHoveredLine(null, null, { source: "source" });
          });

          const label = document.createElement("div");
          label.className = "box-label source-box-label";
          label.style.left = style.left;
          label.style.top = style.top;
          label.style.color = color;
          label.style.borderColor = hexToRgba(color, 0.62);
          label.dataset.layoutId = String(output.layout_id);
          label.textContent = `${output.reading_order}. ${formatClassLabel(output.class_name)}`;
          if (Number(output.layout_id) === selectedId) {
            sourceSelectedLabelLayer.appendChild(label);
          } else {
            sourceLabelLayer.appendChild(label);
          }
          const warningLineIndexes = outputLookalikeLineIndexes(output.layout_id);
          if (warningLineIndexes.length > 0) {
            appendLineMarkers(
              box,
              warningLineIndexes,
              outputLineCount(output.layout_id),
              "box-line-warning",
            );
          }
          sourceOverlay.appendChild(box);
        }
        renderReconstruction();
        applySelectedStyles();
        requestAnimationFrame(() => {
          updateSourceLabelVisibilityForOverlap();
        });
        syncExpandedEditorFromState();
        sourceImageMagnifier.refresh();
      }

      function updateOutputContent(layoutId, nextContent, { source = null } = {}) {
        const output = outputByLayoutId(layoutId);
        if (!output) return;
        const nextDraft = { content: String(nextContent ?? "") };
        output.content = nextDraft.content;
        const baselineOutput = state.serverOutputsByLayoutId[String(layoutId)] || null;
        const baseline = baselineOutput
          ? toDraftShape(baselineOutput)
          : toDraftShape(output);
        if (sameDraft(nextDraft, baseline)) {
          delete state.localEditsByLayoutId[String(layoutId)];
          output.lookalike_warning_count = Number(baselineOutput?.lookalike_warning_count || 0);
          output.lookalike_warning_line_indexes = Array.isArray(baselineOutput?.lookalike_warning_line_indexes)
            ? [...baselineOutput.lookalike_warning_line_indexes]
            : [];
          output.lookalike_warnings = Array.isArray(baselineOutput?.lookalike_warnings)
            ? [...baselineOutput.lookalike_warnings]
            : [];
          setStatus("Draft cleared (matches extracted value).");
        } else {
          state.localEditsByLayoutId[String(layoutId)] = nextDraft;
          output.lookalike_warning_count = 0;
          output.lookalike_warning_line_indexes = [];
          output.lookalike_warnings = [];
          setStatus("Draft saved locally.");
        }
        if (
          Number(state.expandedEditorLayoutId) === Number(layoutId)
        ) {
          if (source !== expandedEditorTextarea && document.activeElement !== expandedEditorTextarea) {
            expandedEditorTextarea.value = nextDraft.content;
          }
          if (source !== "codemirror" && !isCodeMirrorFocused()) {
            setCodeMirrorContent(nextDraft.content);
          }
          renderExpandedEditorValidation();
          refreshExpandedEditorToolbar();
        }
        renderReconstruction();
        persistDraftState();
      }

      function updateOutputFromInput(layoutId, textarea) {
        const content = textarea?.value ?? "";
        updateOutputContent(layoutId, content, { source: textarea });
        const text = String(content);
        const caretOffset = Number.isInteger(textarea?.selectionStart) ? textarea.selectionStart : text.length;
        const lineIndex = lineIndexFromTextOffset(text, caretOffset);
        approveLine(layoutId, lineIndex, { approved: true, persist: false });
        setLineReviewCursor(layoutId, lineIndex, { persist: false });
        persistDraftState();
      }

      function restoreOutputByLayoutId(layoutId) {
        const normalized = Number(layoutId);
        if (!Number.isInteger(normalized) || normalized <= 0) {
          return;
        }
        const output = outputByLayoutId(normalized);
        if (!output || String(output.output_format || "").toLowerCase() === "skip") {
          return;
        }
        const baselineOutput = state.serverOutputsByLayoutId[String(normalized)];
        const baseline = baselineOutput ? toDraftShape(baselineOutput) : { content: "" };
        updateOutputContent(normalized, baseline.content);
      }

      function updateHistoryControls() {
        const targets = historyNavigationTargets({
          history: state.history,
          historyIndex: state.historyIndex,
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
            noBackTitle: "No previous reviewed page in history.",
            backTitle: "Open previous reviewed page",
            forwardHistoryTitle: "Open next reviewed page in history.",
            forwardQueueTitle: "Open next page for OCR review.",
            noForwardTitle: "No next page for OCR review.",
          },
        });
      }

      function storeHistoryState() {
        persistReviewHistoryState({
          writeStorage,
          historyKey: STORAGE_KEYS.history,
          historyIndexKey: STORAGE_KEYS.historyIndex,
          history: state.history,
          historyIndex: state.historyIndex,
        });
      }

      function loadHistoryState() {
        const normalized = loadReviewHistoryState({
          readStorage,
          historyKey: STORAGE_KEYS.history,
          historyIndexKey: STORAGE_KEYS.historyIndex,
          normalizeReviewHistory,
        });
        state.history = normalized.history;
        state.historyIndex = normalized.index;
      }

      async function sanitizeHistoryAgainstServer() {
        try {
          const payload = await fetchPages();
          const filtered = sanitizeReviewHistoryFromPages({
            history: state.history,
            historyIndex: state.historyIndex,
            pages: payload?.pages,
            currentPageId: state.pageId,
            filterReviewHistory,
          });
          state.history = filtered.history;
          state.historyIndex = filtered.index;
          storeHistoryState();
        } catch {
          // Keep local history when server list is temporarily unavailable.
        }
        updateHistoryControls();
      }

      function updateHistoryOnVisit() {
        const next = registerCurrentPageVisit({
          history: state.history,
          historyIndex: state.historyIndex,
          currentPageId: state.pageId,
          updateReviewHistoryOnVisit,
        });
        state.history = next.history;
        state.historyIndex = next.index;
        storeHistoryState();
        updateHistoryControls();
      }

      async function loadPageData() {
        const [pagePayload, outputsPayload, layoutsPayload] = await Promise.all([
          fetchPageDetails(state.pageId),
          fetchPageOcrOutputs(state.pageId),
          fetchPageLayouts(state.pageId),
        ]);
        state.page = pagePayload.page;
        pageImage.src = pagePayload.image_url;
        state.outputs = outputsPayload.outputs || [];
        state.pageLayouts = Array.isArray(layoutsPayload.layouts) ? layoutsPayload.layouts : [];
        state.serverOutputsByLayoutId = Object.fromEntries(
          state.outputs.map((output) => [String(output.layout_id), { ...output }]),
        );
        loadDraftState();
        applyDraftsToOutputs();
        reconcileLineReviewState();
      }

      async function loadForthAvailability() {
        try {
          const payload = await fetchNextOcrReviewPage(state.pageId);
          state.nextReviewPageId =
            Boolean(payload?.has_next) && Number.isInteger(payload?.next_page_id)
              ? Number(payload.next_page_id)
              : null;
        } catch {
          state.nextReviewPageId = null;
        }
        updateHistoryControls();
      }

      async function markReviewed() {
        if (state.reviewSubmitInProgress) return;
        if (state.reextractInProgress) return;
        if (!reviewProgressSummary().complete) return;
        state.reviewSubmitInProgress = true;
        updateReviewUiState();
        try {
          const changedLayoutIds = Object.keys(state.localEditsByLayoutId)
            .map((value) => Number(value))
            .filter((value) => Number.isInteger(value) && value > 0);
          for (const layoutId of changedLayoutIds) {
            const draft = state.localEditsByLayoutId[String(layoutId)];
            await patchOcrOutput(layoutId, { content: String(draft.content ?? "") });
          }

          const result = await completeOcrReview(state.pageId);
          clearDraftState();
          if (state.page) {
            state.page.status = result.status;
          }
          updateReviewUiState();
          setStatus("OCR review saved.");

          const nextPayload = await fetchNextOcrReviewPage(state.pageId);
          if (nextPayload && nextPayload.has_next && Number.isInteger(nextPayload.next_page_id)) {
            window.location.href = `/static/ocr_review.html?page_id=${nextPayload.next_page_id}`;
            return;
          }
          setStatus("OCR review saved. No next page for OCR review.");
        } catch (error) {
          setStatus(`OCR review failed: ${error.message}`, { isError: true });
        } finally {
          state.reviewSubmitInProgress = false;
          updateReviewUiState();
        }
      }

      async function reextractContent(payloadBody) {
        if (state.reviewSubmitInProgress || state.reextractInProgress) {
          return;
        }

        const selectedLayoutIds = Array.isArray(payloadBody?.layout_ids)
          ? payloadBody.layout_ids
              .map((value) => Number(value))
              .filter((value) => Number.isInteger(value) && value > 0)
          : [];
        if (selectedLayoutIds.length === 0) {
          setStatus("Reextraction failed: Select at least one layout to process.", { isError: true });
          return;
        }

        state.reextractInProgress = true;
        state.reextractProgressCurrent = 0;
        state.reextractProgressTotal = selectedLayoutIds.length;
        setReextractModalBusy(true);
        updateReviewUiState();

        const selectedLayoutId = Number(state.selectedLayoutId);
        let shouldCloseModal = false;
        const summary = {
          extracted: 0,
          skipped: 0,
          requests: 0,
        };
        try {
          for (let index = 0; index < selectedLayoutIds.length; index += 1) {
            const layoutId = selectedLayoutIds[index];
            state.reextractProgressCurrent = index + 1;
            updateReextractModalRunButtonState();
            const result = await reextractPageOcr(state.pageId, {
              ...payloadBody,
              layout_ids: [layoutId],
            });
            summary.extracted += Number(result?.extracted_count || 0);
            summary.skipped += Number(result?.skipped_count || 0);
            summary.requests += Number(result?.requests_count || 0);
          }

          shouldCloseModal = true;
          closeReextractModal(true);

          clearDraftState();
          await loadPageData();
          renderHeaderMeta();
          renderOverlay();

          if (
            Number.isInteger(selectedLayoutId) &&
            selectedLayoutId > 0 &&
            state.outputs.some((output) => Number(output.layout_id) === selectedLayoutId)
          ) {
            selectOutput(selectedLayoutId, { scrollImageToLayout: true });
          } else {
            const preferredOutput = preferredInitialOutput();
            if (preferredOutput) {
              selectOutput(preferredOutput.layout_id, { scrollImageToLayout: true });
            }
          }
          updateReviewUiState();
          await loadForthAvailability();

          setStatus(
            `Reextraction finished. Extracted: ${summary.extracted}, skipped: ${summary.skipped}, requests: ${summary.requests}.`,
          );
        } catch (error) {
          setStatus(`Reextraction failed: ${error.message}`, { isError: true });
        } finally {
          state.reextractInProgress = false;
          state.reextractProgressCurrent = 0;
          state.reextractProgressTotal = 0;
          setReextractModalBusy(false);
          updateReviewUiState();
          if (shouldCloseModal) {
            closeReextractModal();
          }
        }
      }

      function parsePageIdFromUrl() {
        const search = new URLSearchParams(window.location.search);
        const parsed = Number(search.get("page_id"));
        return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
      }

      function renderHeaderMeta() {
        if (!state.page) {
          pageMeta.textContent = "";
          return;
        }
        pageMeta.textContent = `Page #${state.page.id} | ${state.page.rel_path}`;
      }

      async function init() {
        const pageId = parsePageIdFromUrl();
        if (!pageId) {
          setStatus("Missing page_id query parameter.", { isError: true });
          reviewBtn.disabled = true;
          return;
        }

        rebuildZoomPresetOptions();
        applyStoredZoomSettings();
        applyStoredEditorFontSize();
        applyStoredEditorDrawerWidth();
        state.reconstructedRenderMode = normalizeReconstructedRenderMode(
          readStorage(STORAGE_KEYS.reconstructedRenderMode),
        );
        applyRenderModeUi();
        state.viewMode = normalizeReviewViewMode(readStorage(STORAGE_KEYS.reviewViewMode));
        state.panelVisibility = normalizePanelVisibility(readStorage(STORAGE_KEYS.panelVisibility));
        applyPanelVisibility();
        state.pageId = pageId;
        loadHistoryState();
        await sanitizeHistoryAgainstServer();
        updateHistoryOnVisit();

        try {
          await loadPageData();
        } catch (error) {
          setStatus(`Failed to load OCR review page: ${error.message}`, { isError: true });
          reviewBtn.disabled = true;
          return;
        }

        renderHeaderMeta();
        renderOverlay();
        const pendingLineReviewOutput = firstPendingLineReviewOutput();
        if (pendingLineReviewOutput) {
          setLineReviewCursor(pendingLineReviewOutput.layout_id, 0, { persist: false });
          selectOutput(pendingLineReviewOutput.layout_id, { scrollImageToLayout: false });
        } else {
          const preferredOutput = preferredInitialOutput();
          if (preferredOutput) {
            selectOutput(preferredOutput.layout_id, { scrollImageToLayout: false });
          }
        }
        updateReviewUiState();
        notifyReconstructedControlsActivity();
        updateReconstructedFloatingControlsPosition();
        setStatus("Ready.");
        await loadForthAvailability();
      }

      historyBackBtn.addEventListener("click", () => {
        const prevPageId = previousHistoryPageId(state.history, state.historyIndex);
        if (!Number.isInteger(prevPageId) || prevPageId <= 0) return;
        state.historyIndex -= 1;
        storeHistoryState();
        window.location.href = `/static/ocr_review.html?page_id=${prevPageId}`;
      });

      historyForthBtn.addEventListener("click", async () => {
        const forwardPageId = nextHistoryPageId(state.history, state.historyIndex);
        if (Number.isInteger(forwardPageId) && forwardPageId > 0) {
          state.historyIndex = Math.min(state.history.length - 1, Math.max(0, state.historyIndex + 1));
          storeHistoryState();
          window.location.href = `/static/ocr_review.html?page_id=${forwardPageId}`;
          return;
        }

        let queueTarget = Number(state.nextReviewPageId);
        if (!Number.isInteger(queueTarget) || queueTarget <= 0) {
          try {
            await loadForthAvailability();
          } catch {
            // Keep existing disabled state if queue availability check fails.
          }
          queueTarget = Number(state.nextReviewPageId);
        }
        if (!Number.isInteger(queueTarget) || queueTarget <= 0) {
          updateHistoryControls();
          return;
        }
        window.location.href = `/static/ocr_review.html?page_id=${queueTarget}`;
      });

      toggleSourceBtn.addEventListener("click", () => togglePanel("source"));
      toggleReconstructedBtn.addEventListener("click", () => togglePanel("reconstructed"));
      viewTwoPanelsBtn?.addEventListener("click", () => {
        setReviewViewMode("two_panels");
      });
      viewLineByLineBtn?.addEventListener("click", () => {
        setReviewViewMode("line_by_line");
      });
      lineReviewPrevBtn?.addEventListener("click", () => {
        moveLineReviewCursor(-1);
      });
      lineReviewNextBtn?.addEventListener("click", () => {
        moveLineReviewCursor(1);
      });
      lineReviewApproveBtn?.addEventListener("click", () => {
        approveCurrentLineAndAdvance();
      });
      lineReviewApproveBboxBtn?.addEventListener("click", () => {
        approveAllLinesForSelectedBbox();
      });
      lineReviewResetBboxBtn?.addEventListener("click", () => {
        resetLineApprovalsForSelectedBbox();
      });
      const onLineReviewSlotClick = (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        const slot = target.closest(".line-review-slot[data-line-index]");
        if (!(slot instanceof HTMLElement)) {
          return;
        }
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        const nextIndex = Number(slot.dataset.lineIndex);
        if (!Number.isInteger(nextIndex)) {
          return;
        }
        setLineReviewCursor(selectedLayoutId, nextIndex, { persist: true });
        syncHoveredLineFromLineReviewCursor(selectedLayoutId);
        renderLineReviewPanel();
      };
      lineReviewReel?.addEventListener("click", onLineReviewSlotClick);
      lineReviewReel?.addEventListener("dblclick", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) {
          return;
        }
        const currentLine = target.closest(".line-review-slot.current .line-review-gemini-line");
        if (!(currentLine instanceof HTMLElement)) {
          return;
        }
        const slot = currentLine.closest(".line-review-slot[data-line-index]");
        if (!(slot instanceof HTMLElement)) {
          return;
        }
        const selectedLayoutId = Number(state.selectedLayoutId);
        const output = outputByLayoutId(selectedLayoutId);
        if (!output || !lineReviewRequiredOutput(output)) {
          return;
        }
        const lineIndex = Number(slot.dataset.lineIndex);
        if (!Number.isInteger(lineIndex)) {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        openEditorForLine(selectedLayoutId, lineIndex);
      });
      reconstructedViewport.addEventListener("pointermove", () => {
        notifyReconstructedControlsActivity();
      });
      reconstructedViewport.addEventListener("pointerdown", () => {
        notifyReconstructedControlsActivity();
      });
      reconstructedViewport.addEventListener(
        "wheel",
        () => {
          notifyReconstructedControlsActivity();
        },
        { passive: true },
      );
      reconstructedViewport.addEventListener(
        "scroll",
        () => {
          notifyReconstructedControlsActivity();
          syncViewportScroll(reconstructedViewport, sourceViewport);
        },
        { passive: true },
      );
      sourceViewport.addEventListener(
        "scroll",
        () => {
          syncViewportScroll(sourceViewport, reconstructedViewport);
        },
        { passive: true },
      );
      reconstructedViewport.addEventListener(
        "touchstart",
        () => {
          notifyReconstructedControlsActivity();
        },
        { passive: true },
      );
      reconstructedViewport.addEventListener(
        "touchmove",
        () => {
          notifyReconstructedControlsActivity();
        },
        { passive: true },
      );
      reconstructedViewport.addEventListener("mouseenter", () => {
        notifyReconstructedControlsActivity();
      });
      window.addEventListener(
        "scroll",
        () => {
          updateReconstructedFloatingControlsPosition();
          applyFocusedStripOverlay();
          if (state.panelVisibility.reconstructed) {
            notifyReconstructedControlsActivity();
          }
        },
        { passive: true },
      );
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
          altMagnifierPressed = true;
          sourceImageMagnifier.setTemporary(true);
          return;
        }
        if (
          key === "m" &&
          !event.repeat &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          !isInteractiveTextTarget(event.target)
        ) {
          event.preventDefault();
          toggleMagnifier();
          return;
        }
        if (state.panelVisibility.reconstructed) {
          notifyReconstructedControlsActivity();
        }
        if (
          event.key === "Enter" &&
          !event.repeat &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          !event.shiftKey &&
          !isInteractiveTextTarget(event.target) &&
          state.viewMode === "line_by_line" &&
          !lineReviewPanel?.hidden
        ) {
          event.preventDefault();
          openEditorForCurrentLine();
          return;
        }
        if (
          event.key === "ArrowUp" &&
          !event.repeat &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          !event.shiftKey &&
          !isInteractiveTextTarget(event.target) &&
          !lineReviewPanel?.hidden
        ) {
          event.preventDefault();
          moveLineReviewCursor(-1);
          return;
        }
        if (
          event.key === "ArrowDown" &&
          !event.repeat &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          !event.shiftKey &&
          !isInteractiveTextTarget(event.target) &&
          !lineReviewPanel?.hidden
        ) {
          event.preventDefault();
          moveLineReviewCursor(1);
          return;
        }
        if (
          (event.key === "a" || event.key === "A") &&
          !event.repeat &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          !isInteractiveTextTarget(event.target) &&
          !lineReviewPanel?.hidden
        ) {
          event.preventDefault();
          if (event.shiftKey) {
            unapproveCurrentLine();
          } else {
            approveCurrentLineAndAdvance();
          }
          return;
        }
        if (event.key === "ArrowUp" || event.key === "ArrowDown") {
          if (!reextractModal.hidden) {
            return;
          }
          if (isInteractiveTextTarget(event.target)) {
            return;
          }
          const moved = moveHoveredLineWithKeyboard(event.key === "ArrowDown" ? 1 : -1);
          if (moved) {
            event.preventDefault();
            return;
          }
        }
        if (event.key === "Escape") {
          if (!expandedEditor.hidden) {
            closeExpandedEditor();
            return;
          }
          closeZoomMenu();
          closeReextractModal();
        }
      });
      document.addEventListener("keyup", (event) => {
        if (String(event.key || "").toLowerCase() !== "alt") {
          return;
        }
        altMagnifierPressed = false;
        sourceImageMagnifier.setTemporary(false);
      });
      window.addEventListener("blur", () => {
        if (!altMagnifierPressed) {
          return;
        }
        altMagnifierPressed = false;
        sourceImageMagnifier.setTemporary(false);
      });
      magnifierToggleBtn.addEventListener("click", () => {
        toggleMagnifier();
      });

      reextractBtn.addEventListener("click", () => {
        openReextractModal();
      });
      reextractModalSelectAllInput?.addEventListener("change", () => {
        if (state.reextractInProgress) {
          return;
        }
        const checked = Boolean(reextractModalSelectAllInput.checked);
        const checkboxes = reextractModalLayoutsContainer.querySelectorAll('input[name="reextract-layout-id"]');
        for (const checkbox of checkboxes) {
          checkbox.checked = checked;
        }
        updateReextractModalRunButtonState();
      });
      renderMarkdownBtn.addEventListener("click", () => {
        setReconstructedRenderMode("markdown");
        notifyReconstructedControlsActivity();
      });
      renderRawBtn.addEventListener("click", () => {
        setReconstructedRenderMode("raw");
        notifyReconstructedControlsActivity();
      });
      reextractModalRunBtn.addEventListener("click", async () => {
        if (state.reextractInProgress) {
          return;
        }
        let payloadBody;
        try {
          payloadBody = parseReextractPayload();
        } catch (error) {
          setStatus(`Reextraction failed: ${error.message}`, { isError: true });
          return;
        }
        await reextractContent(payloadBody);
      });
      reextractModalCancelBtn.addEventListener("click", () => {
        closeReextractModal();
      });
      reextractModal.addEventListener("pointerdown", (event) => {
        if (shouldCloseOnBackdropPointerDown(event, reextractModal)) {
          closeReextractModal();
        }
      });
      expandedEditorResizeHandle.addEventListener("pointerdown", beginEditorDrawerResize);
      expandedEditorResizeHandle.addEventListener("pointermove", updateEditorDrawerResize);
      expandedEditorResizeHandle.addEventListener("pointerup", endEditorDrawerResize);
      expandedEditorResizeHandle.addEventListener("pointercancel", endEditorDrawerResize);
      expandedEditorResizeHandle.addEventListener("lostpointercapture", endEditorDrawerResize);
      expandedEditorCloseBtn.addEventListener("click", () => {
        closeExpandedEditor();
      });
      editorActionBoldBtn.addEventListener("click", () => {
        applyMarkdownAction("bold");
      });
      editorActionItalicBtn.addEventListener("click", () => {
        applyMarkdownAction("italic");
      });
      editorActionInlineFormulaBtn.addEventListener("click", () => {
        applyMarkdownAction("inline_formula");
      });
      editorActionListItemBtn.addEventListener("click", () => {
        applyMarkdownAction("list_item");
      });
      editorActionOrderedListItemBtn.addEventListener("click", () => {
        applyMarkdownAction("ordered_list_item");
      });
      editorFontSizeDecreaseBtn.addEventListener("click", () => {
        setExpandedEditorFontSize(state.editorFontSize - EDITOR_FONT_SIZE_STEP);
      });
      editorFontSizeIncreaseBtn.addEventListener("click", () => {
        setExpandedEditorFontSize(state.editorFontSize + EDITOR_FONT_SIZE_STEP);
      });
      expandedEditorWrapBtn.addEventListener("click", () => {
        toggleExpandedEditorWrap();
      });
      expandedEditorTextarea.addEventListener("keydown", (event) => {
        const hotkeyAction = resolveExpandedEditorHotkeyAction(event);
        if (hotkeyAction) {
          if (applyMarkdownAction(hotkeyAction)) {
            event.preventDefault();
            return;
          }
        }
        if (event.key !== "Enter") {
          return;
        }
        if (event.ctrlKey || event.metaKey) {
          event.preventDefault();
          const start = Number.isInteger(expandedEditorTextarea.selectionStart)
            ? expandedEditorTextarea.selectionStart
            : expandedEditorTextarea.value.length;
          const end = Number.isInteger(expandedEditorTextarea.selectionEnd)
            ? expandedEditorTextarea.selectionEnd
            : expandedEditorTextarea.value.length;
          expandedEditorTextarea.setRangeText("\n", start, end, "end");
          const layoutId = Number(state.expandedEditorLayoutId);
          if (Number.isInteger(layoutId) && layoutId > 0) {
            updateOutputFromInput(layoutId, expandedEditorTextarea);
          }
          updateExpandedEditorStatusFromTextarea();
          syncHoveredLineFromExpandedEditor({ source: "editor" });
          return;
        }
        event.preventDefault();
        closeExpandedEditor();
      });
      expandedEditorTextarea.addEventListener("input", () => {
        const layoutId = Number(state.expandedEditorLayoutId);
        if (!Number.isInteger(layoutId) || layoutId <= 0) {
          return;
        }
        updateOutputFromInput(layoutId, expandedEditorTextarea);
        updateExpandedEditorStatusFromTextarea();
        syncHoveredLineFromExpandedEditor({ source: "editor" });
      });
      expandedEditorTextarea.addEventListener("click", () => {
        updateExpandedEditorStatusFromTextarea();
        syncHoveredLineFromExpandedEditor({ source: "editor" });
      });
      expandedEditorTextarea.addEventListener("keyup", () => {
        updateExpandedEditorStatusFromTextarea();
        syncHoveredLineFromExpandedEditor({ source: "editor" });
      });
      reviewBtn.addEventListener("click", markReviewed);

      pageImage.addEventListener("load", () => {
        applyZoom();
        renderReconstruction();
        notifyReconstructedControlsActivity();
        updateReconstructedFloatingControlsPosition();
        sourceImageMagnifier.refresh();
        if (state.selectedLayoutId !== null) {
          ensureLayoutVisible(state.selectedLayoutId, 8, {
            preferVerticalCenter: state.viewMode === "line_by_line",
          });
        }
      });

      if (typeof ResizeObserver !== "undefined") {
        const viewportResizeObserver = new ResizeObserver(() => {
          if (state.zoomMode !== "custom") {
            applyZoom();
          }
          updateReconstructedFloatingControlsPosition();
          applyFocusedStripOverlay();
          renderLineReviewPanel();
        });
        viewportResizeObserver.observe(sourceViewport);
        viewportResizeObserver.observe(reconstructedViewport);
      } else {
        window.addEventListener("resize", () => {
          if (state.zoomMode !== "custom") {
            applyZoom();
          }
          updateReconstructedFloatingControlsPosition();
          applyFocusedStripOverlay();
          renderLineReviewPanel();
        });
      }
      window.addEventListener("resize", () => {
        applyExpandedEditorDrawerWidth({ persist: false });
        applyFocusedStripOverlay();
        renderLineReviewPanel();
      });
      window.addEventListener("beforeunload", () => {
        clearReconstructedControlsIdleTimer();
        document.body.classList.remove("editor-resizing");
      });

      sourceImageMagnifier.setEnabled(state.magnifierEnabled);
      setMagnifierZoom(state.magnifierZoom, { persist: false });
      updateMagnifierToggleUi();
      init().catch((error) => {
        setStatus(`Initialization failed: ${error.message}`, { isError: true });
      });
