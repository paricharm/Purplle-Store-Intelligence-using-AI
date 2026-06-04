from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response


logger = logging.getLogger("store_intelligence")


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")


async def request_logging_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
    request.state.trace_id = trace_id
    started = time.perf_counter()
    status_code = 500
    store_id = request.path_params.get("id")

    response = await call_next(request)
    status_code = response.status_code
    response.headers["x-trace-id"] = trace_id
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    event_count = getattr(request.state, "event_count", None)
    store_id = getattr(request.state, "store_id", store_id)

    logger.info(
        json.dumps(
            {
                "trace_id": trace_id,
                "store_id": store_id,
                "endpoint": request.url.path,
                "latency_ms": latency_ms,
                "event_count": event_count,
                "status_code": status_code,
            },
            sort_keys=True,
        )
    )
    return response
