from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (Index("idx_pages_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rel_path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    file_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")
    layout_order_mode: Mapped[str] = mapped_column(String, nullable=False, default="auto")
    qa_bbox_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    qa_class_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    qa_order_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    qa_ocr_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    last_seen_at: Mapped[str] = mapped_column(String, nullable=False)
    is_missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DuplicateFile(Base):
    __tablename__ = "duplicate_files"
    __table_args__ = (Index("idx_duplicate_files_active", "active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rel_path: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    file_hash: Mapped[str] = mapped_column(String, nullable=False)
    canonical_page_id: Mapped[int] = mapped_column(ForeignKey("pages.id"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    first_seen_at: Mapped[str] = mapped_column(String, nullable=False)
    last_seen_at: Mapped[str] = mapped_column(String, nullable=False)


class Layout(Base):
    __tablename__ = "layouts"
    __table_args__ = (
        Index("idx_layouts_page_order", "page_id", "reading_order"),
        UniqueConstraint("page_id", "reading_order", name="uq_layouts_page_order"),
        CheckConstraint("reading_order >= 1", name="ck_layouts_reading_order_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    class_name: Mapped[str] = mapped_column(String, nullable=False)
    x1: Mapped[float] = mapped_column(Float, nullable=False)
    y1: Mapped[float] = mapped_column(Float, nullable=False)
    x2: Mapped[float] = mapped_column(Float, nullable=False)
    y2: Mapped[float] = mapped_column(Float, nullable=False)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    orientation: Mapped[str] = mapped_column(String, nullable=False, default="horizontal")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class CaptionBinding(Base):
    __tablename__ = "caption_bindings"
    __table_args__ = (
        Index("idx_caption_bindings_caption", "caption_layout_id"),
        Index("idx_caption_bindings_target", "target_layout_id"),
    )

    caption_layout_id: Mapped[int] = mapped_column(
        ForeignKey("layouts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    target_layout_id: Mapped[int] = mapped_column(
        ForeignKey("layouts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class OcrOutput(Base):
    __tablename__ = "ocr_outputs"
    __table_args__ = (Index("idx_ocr_outputs_page", "page_id"),)

    layout_id: Mapped[int] = mapped_column(
        ForeignKey("layouts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    class_name: Mapped[str] = mapped_column(String, nullable=False)
    output_format: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    key_alias: Mapped[str | None] = mapped_column(String, nullable=True)
    extraction_status: Mapped[str] = mapped_column(String, nullable=False, default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class OcrVerificationRun(Base):
    __tablename__ = "ocr_verification_runs"
    __table_args__ = (Index("idx_ocr_verification_runs_status", "status", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    stop_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    total_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


class OcrVerificationTask(Base):
    __tablename__ = "ocr_verification_tasks"
    __table_args__ = (
        UniqueConstraint(
            "layout_id",
            "model_name",
            "evidence_fingerprint",
            name="uq_ocr_verification_task_evidence",
        ),
        Index("idx_ocr_verification_tasks_status_retry", "status", "next_retry_at", "id"),
        Index("idx_ocr_verification_tasks_page_layout", "page_id", "layout_id"),
        Index("idx_ocr_verification_tasks_run_status", "run_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ocr_verification_runs.id", ondelete="SET NULL"), nullable=True
    )
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    layout_id: Mapped[int] = mapped_column(ForeignKey("layouts.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_alias: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


class OcrVerificationFinding(Base):
    __tablename__ = "ocr_verification_findings"
    __table_args__ = (
        Index("idx_ocr_verification_findings_state", "state", "page_id", "layout_id"),
    )

    layout_id: Mapped[int] = mapped_column(
        ForeignKey("layouts.id", ondelete="CASCADE"), primary_key=True
    )
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    evidence_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    comparison_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    comparison_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    baseline_content: Mapped[str] = mapped_column(Text, nullable=False)
    source_model: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    groups_json: Mapped[str] = mapped_column(Text, nullable=False)
    responded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class OcrVerificationResolution(Base):
    __tablename__ = "ocr_verification_resolutions"
    __table_args__ = (Index("idx_ocr_verification_resolutions_layout", "layout_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    layout_id: Mapped[int] = mapped_column(ForeignKey("layouts.id", ondelete="CASCADE"), nullable=False)
    comparison_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    previous_content: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_content: Mapped[str] = mapped_column(Text, nullable=False)
    source_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("ocr_verification_tasks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class PipelineJob(Base):
    __tablename__ = "pipeline_jobs"
    __table_args__ = (
        Index("idx_pipeline_jobs_status_stage", "status", "stage", "id"),
        Index("idx_pipeline_jobs_stage_page_status", "stage", "page_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    __table_args__ = (Index("idx_pipeline_events_stage_ts", "stage", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String, nullable=False)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class LayoutDetectionDefaults(Base):
    __tablename__ = "layout_detection_defaults"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    model_checkpoint: Mapped[str] = mapped_column(String, nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    iou_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    image_size: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_by: Mapped[str] = mapped_column(String, nullable=False, default="system")


class LayoutBenchmarkRun(Base):
    __tablename__ = "layout_benchmark_runs"
    __table_args__ = (
        Index("idx_layout_benchmark_runs_status", "status"),
        Index("idx_layout_benchmark_runs_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    force_full_rerun: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_configs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_page_id: Mapped[int | None] = mapped_column(ForeignKey("pages.id", ondelete="SET NULL"), nullable=True)
    current_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_defaults: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


class LayoutBenchmarkResult(Base):
    __tablename__ = "layout_benchmark_results"
    __table_args__ = (
        UniqueConstraint(
            "page_id",
            "page_fingerprint",
            "model_checkpoint",
            "image_size",
            "confidence_threshold",
            "iou_threshold",
            name="uq_layout_benchmark_results_config",
        ),
        Index("idx_layout_benchmark_results_page", "page_id"),
        Index("idx_layout_benchmark_results_fingerprint", "page_fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), nullable=False)
    page_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    model_checkpoint: Mapped[str] = mapped_column(String, nullable=False)
    image_size: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    iou_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    predictions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
