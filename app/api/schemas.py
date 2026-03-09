from __future__ import annotations

from pydantic import BaseModel, Field


class BBoxPayload(BaseModel):
    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    x2: float = Field(ge=0.0, le=1.0)
    y2: float = Field(ge=0.0, le=1.0)


class DetectLayoutsRequest(BaseModel):
    replace_existing: bool = True
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    iou_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    image_size: int | None = Field(default=None, ge=32)
    max_detections: int | None = Field(default=None, ge=1)
    agnostic_nms: bool | None = None


class CreateLayoutRequest(BaseModel):
    class_name: str = Field(min_length=1, max_length=120)
    bbox: BBoxPayload
    reading_order: int | None = Field(default=None, ge=1)


class UpdateLayoutRequest(BaseModel):
    class_name: str | None = Field(default=None, min_length=1, max_length=120)
    reading_order: int | None = Field(default=None, ge=1)
    bbox: BBoxPayload | None = None


class WipeStateRequest(BaseModel):
    confirm: bool = False
    rescan: bool = True


class CaptionBindingPayload(BaseModel):
    caption_layout_id: int = Field(ge=1)
    target_layout_ids: list[int] = Field(default_factory=list)


class ReplaceCaptionBindingsRequest(BaseModel):
    bindings: list[CaptionBindingPayload] = Field(default_factory=list)


class UpdateOcrOutputRequest(BaseModel):
    content: str = ""


class ReextractOcrRequest(BaseModel):
    layout_ids: list[int] | None = None
    prompt_template: str | None = Field(default=None, max_length=20000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_retries_per_layout: int | None = Field(default=None, ge=1, le=10)


class RuntimeOptionsUpdateRequest(BaseModel):
    auto_detect_layouts_after_discovery: bool | None = None
    auto_extract_text_after_layout_review: bool | None = None


class FinalExportRequest(BaseModel):
    confirm: bool = False
