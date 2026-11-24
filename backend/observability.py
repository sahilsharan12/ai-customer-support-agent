import logging
import json
from collections import Counter, defaultdict
from threading import Lock
from time import perf_counter

from fastapi import Request
from opentelemetry import trace

from backend.config import SUPPORT_OTEL_CONSOLE


logger = logging.getLogger("uvicorn.error")
_lock = Lock()
_requests = defaultdict(lambda: {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
_assistant = Counter()
_provider = None


def configure_tracing():
    global _provider
    if SUPPORT_OTEL_CONSOLE and _provider is None:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        _provider = TracerProvider(resource=Resource.create({"service.name": "support-desk"}))
        _provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))


def span(name: str):
    return trace.get_tracer("support_desk", tracer_provider=_provider).start_as_current_span(
        name, record_exception=False, set_status_on_exception=False,
    )


def track(**counts):
    with _lock:
        _assistant.update(counts)


def assistant_metrics():
    with _lock:
        totals = dict(_assistant)
    turns = totals.get("turns", 0)
    calls = totals.get("tool_calls", 0)
    return {
        **totals,
        "human_escalation_rate": totals.get("escalated_turns", 0) / turns if turns else None,
        "tool_execution_success_rate": totals.get("tool_successes", 0) / calls if calls else None,
        "mean_response_ms": round(totals.get("response_ms", 0) / turns, 2) if turns else None,
        "model_error_rate": totals.get("model_errors", 0) / totals["model_attempts"] if totals.get("model_attempts") else None,
    }


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
        logger.info(json.dumps({
            "event": "http_request", "method": method, "route": route,
            "status": status, "duration_ms": round(duration, 2),
        }))


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
