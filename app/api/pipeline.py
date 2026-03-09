from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..pipeline_runtime import get_activity_snapshot, register_default_handlers

router = APIRouter()


@router.get("/api/pipeline/activity")
def pipeline_activity(limit: int = 30) -> dict[str, object]:
    register_default_handlers()
    return get_activity_snapshot(limit=limit)


@router.get("/api/pipeline/activity/stream")
async def pipeline_activity_stream(request: Request, limit: int = 30) -> StreamingResponse:
    register_default_handlers()
    safe_limit = max(1, min(limit, 200))

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            payload = get_activity_snapshot(limit=safe_limit)
            yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            await asyncio.sleep(2.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
