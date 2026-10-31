"""Tracing must preserve request behaviour and exclude private input."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.core import tracing
from app.core.config import Settings
from app.llm.base import LLMError
from app.llm.service import TASKS, LLMService


@pytest.fixture()
def captured(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_provider", provider)
    yield exporter
    provider.shutdown()


def demo_app():
    app = FastAPI()
    app.add_middleware(tracing.TracingMiddleware)

    @app.post("/api/items/{item_id}")
    def item(item_id: str, request: Request):
        with tracing.operation("basket.optimise"):
            return {"ok": True}

    @app.get("/api/failure")
    def failure():
        raise ValueError("private-error-sentinel")

    return app


def test_request_threadpool_spans_and_private_data(captured):
    with TestClient(demo_app()) as client:
        result = client.post("/api/items/private-id?secret=private-query",
                             json={"prompt": "private-body"},
                             headers={"Authorization": "Bearer private-token"})
    assert result.status_code == 200
    spans = captured.get_finished_spans()
    child, root = spans
    assert child.name == "basket.optimise"
    assert root.name == "POST /api/items/{item_id}"
    assert child.parent.span_id == root.context.span_id
    assert child.context.trace_id == root.context.trace_id
    assert result.headers["x-trace-id"] == format(root.context.trace_id, "032x")
    assert root.attributes["http.response.status_code"] == 200
    assert "private-" not in "".join(s.to_json() for s in spans)


def test_exception_records_type_without_message(captured):
    with TestClient(demo_app(), raise_server_exceptions=False) as client:
        assert client.get("/api/failure").status_code == 500
    span, = captured.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "ValueError"
    assert not span.events
    assert "private-error-sentinel" not in span.to_json()


def test_disabled_tracing_does_not_change_response(monkeypatch):
    monkeypatch.setattr(tracing, "_provider", None)
    with TestClient(demo_app()) as client:
        response = client.post("/api/items/42")
    assert response.json() == {"ok": True}
    assert "x-trace-id" not in response.headers


def test_ai_failure_is_visible_when_fallback_succeeds(captured, monkeypatch):
    task = SimpleNamespace(system="private-system", build_user=lambda ctx: ctx["prompt"],
                           schema=None, mock=lambda ctx: "fallback")
    monkeypatch.setitem(TASKS, "trace_test", task)

    class BrokenProvider:
        name = "test"
        model = "test-model"

        def generate(self, **kwargs):
            raise LLMError("private-provider-error")

    service = LLMService(Settings(_env_file=None, llm_provider="mock", llm_fallback_to_mock=True))
    service.provider = BrokenProvider()
    result = service.run("trace_test", {"prompt": "private-prompt"})
    assert result.fell_back and result.data == "fallback"
    call, task_span = captured.get_finished_spans()
    assert call.status.status_code == StatusCode.ERROR
    assert task_span.attributes["ai.fallback"] is True
    assert call.parent.span_id == task_span.context.span_id
    assert "private-" not in "".join(s.to_json() for s in (call, task_span))


def test_unmatched_route_does_not_record_raw_path(captured):
    with TestClient(demo_app()) as client:
        assert client.get("/api/private-missing-path").status_code == 404
    span, = captured.get_finished_spans()
    assert span.name == "GET /api/unmatched"
    assert "private-missing-path" not in span.to_json()


def test_collector_failure_does_not_fail_request(monkeypatch):
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

    class UnavailableCollector(SpanExporter):
        attempted = False

        def export(self, spans):
            self.attempted = True
            return SpanExportResult.FAILURE

    exporter = UnavailableCollector()
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_provider", provider)
    try:
        with TestClient(demo_app()) as client:
            assert client.post("/api/items/42").json() == {"ok": True}
        provider.force_flush(timeout_millis=2000)
        assert exporter.attempted
    finally:
        provider.shutdown()
