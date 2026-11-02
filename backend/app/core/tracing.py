"""Optional OpenTelemetry spans; only explicit operational metadata leaves the app."""
from contextlib import contextmanager
from functools import wraps

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import SpanKind, Status, StatusCode

_provider: TracerProvider | None = None
_noop = trace.NoOpTracerProvider()


def initialise(settings) -> None:
    global _provider
    if not settings.tracing_enabled or _provider is not None:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    provider = TracerProvider(
        resource=Resource.create({"service.name": "trolleymate", "service.version": "0.2.0"}),
        sampler=ParentBased(TraceIdRatioBased(settings.tracing_sample_ratio)),
    )
    provider.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=settings.tracing_endpoint, timeout=2),
        max_queue_size=512, max_export_batch_size=64, schedule_delay_millis=500,
    ))
    _provider = provider


def shutdown() -> None:
    global _provider
    provider, _provider = _provider, None
    if provider is not None:
        provider.shutdown()


@contextmanager
def operation(name: str, attributes: dict | None = None, *, kind=SpanKind.INTERNAL):
    tracer = (_provider or _noop).get_tracer("trolleymate")
    # Automatic exception events include messages/stack traces, which may contain
    # shopper text or provider secrets. Keep only the exception's class instead.
    with tracer.start_as_current_span(name, attributes=attributes, kind=kind,
                                     record_exception=False, set_status_on_exception=False) as span:
        try:
            yield span
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def traced(name: str):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with operation(name):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


class TracingMiddleware:
    """Trace API work, including threadpool child spans, without recording URLs/data."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (_provider is None or scope["type"] != "http" or not path.startswith("/api/")
                or path == "/api/health" or scope["method"] == "OPTIONS"):
            return await self.app(scope, receive, send)
        status = 500
        method = scope["method"] if scope["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"} else "OTHER"
        with operation("HTTP " + method, {"http.request.method": method}, kind=SpanKind.SERVER) as span:
            async def traced_send(message):
                nonlocal status
                if message["type"] == "http.response.start":
                    status = message["status"]
                    context = span.get_span_context()
                    if context.is_valid:
                        message = dict(message)
                        message["headers"] = list(message.get("headers", [])) + [
                            (b"x-trace-id", format(context.trace_id, "032x").encode())]
                await send(message)
            try:
                await self.app(scope, receive, traced_send)
            finally:
                # Use the matched route template; never raw paths, query strings,
                # headers, user ids, request/response bodies or exception messages.
                route = getattr(scope.get("route"), "path", "/api/unmatched")
                span.update_name(f"{method} {route}")
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                if status >= 500:
                    span.set_status(Status(StatusCode.ERROR))
