"""Expose API processing time without logging credentials or request bodies."""
import logging
from time import perf_counter

logger = logging.getLogger(__name__)


class ResponseTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = perf_counter()
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            elapsed_ms = (perf_counter() - started) * 1000
            timing = f"app;dur={elapsed_ms:.1f}"
            existing = response.get("Server-Timing")
            response["Server-Timing"] = f"{existing}, {timing}" if existing else timing
            if elapsed_ms >= 1000:
                # Use the route pattern, never user input or identifiers.
                match = getattr(request, "resolver_match", None)
                logger.warning("Slow API response: method=%s route=%s status=%s duration_ms=%.1f",
                               request.method, getattr(match, "route", "unresolved"),
                               response.status_code, elapsed_ms)
        return response
