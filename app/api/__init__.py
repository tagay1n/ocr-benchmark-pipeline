from .batch_ocr import router as batch_ocr_router
from .benchmark import router as benchmark_router
from .discovery import router as discovery_router
from .pipeline import router as pipeline_router
from .review import router as review_router

__all__ = [
    "batch_ocr_router",
    "benchmark_router",
    "discovery_router",
    "pipeline_router",
    "review_router",
]
