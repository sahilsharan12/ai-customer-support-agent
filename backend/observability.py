import logging
from collections import defaultdict
from threading import Lock
from time import perf_counter

from fastapi import Request


logger = logging.getLogger("uvicorn.error")
_lock = Lock()
_requests = defaultdict(lambda: {"count": 0, "total_ms": 0.0, "max_ms": 0.0})


async def observe_request(request: Request, call_next):
    started = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.headers.get("authorization") or request.url.path.startswith("/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    finally:
        duration = (perf_counter() - started) * 1000
        route = getattr(request.scope.get("route"), "path", "<unmatched>")
        method = request.method if request.method in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"} else "OTHER"
        with _lock:
            entry = _requests[method, route, status]
            entry["count"] += 1
            entry["total_ms"] += duration
            entry["max_ms"] = max(duration, entry["max_ms"])
        logger.info("method=%s route=%s status=%s duration_ms=%.1f", method, route, status, duration)


def request_metrics():
    with _lock:
        return [
            {
                "method": method, "route": route, "status": status,
                "count": row["count"], "mean_ms": round(row["total_ms"] / row["count"], 2),
                "max_ms": round(row["max_ms"], 2),
            }
            for (method, route, status), row in sorted(_requests.items())
        ]
