"""SourceHttp (the shared HTTP helper), offline: httpx.MockTransport."""
from __future__ import annotations

import httpx
import pytest

from backend.services.sources import base
from backend.services.sources.base import SourceError, SourceHttp


def http_for(handler, **kw) -> SourceHttp:
    return SourceHttp(transport=httpx.MockTransport(handler), **kw)


@pytest.fixture
def no_sleep(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(base.time, "sleep", waits.append)
    return waits


def test_retry_on_503_then_success(no_sleep):
    statuses = iter([503, 503, 200])

    def handler(request):
        code = next(statuses)
        return httpx.Response(code, json={"ok": True} if code == 200 else None)

    with http_for(handler, max_retries=3) as http:
        assert http.get_json("https://example.test/x") == {"ok": True}
    assert no_sleep == [1.0, 2.0]  # exponential backoff


def test_retry_after_honoured_and_capped(no_sleep):
    responses = iter([
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503, headers={"Retry-After": "3600"}),
        httpx.Response(200, text="done"),
    ])
    with http_for(lambda r: next(responses)) as http:
        assert http.get_text("https://example.test/x") == "done"
    assert no_sleep == [7.0, 30.0]


def test_no_retry_on_404(no_sleep):
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404)

    with http_for(handler) as http, pytest.raises(SourceError, match="404"):
        http.get_json("https://example.test/x")
    assert len(calls) == 1 and no_sleep == []


def test_gives_up_with_readable_message(no_sleep):
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with http_for(handler, max_retries=2) as http:
        http.label = "Example"
        with pytest.raises(SourceError) as e:
            http.get_json("https://example.test/x")
    assert str(e.value) == "Example: HTTP 503 after 3 tries"
    assert len(calls) == 3 and len(no_sleep) == 2


def test_zero_retries_means_one_request(no_sleep):
    calls: list[httpx.Request] = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    with http_for(handler, max_retries=0) as http, pytest.raises(SourceError, match="429"):
        http.get_json("https://example.test/x")
    assert len(calls) == 1 and no_sleep == []


def test_network_error_retried(no_sleep):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json=[])

    with http_for(handler) as http:
        assert http.get_json("https://example.test/x") == []
    assert attempts["n"] == 2 and no_sleep == [1.0]


def test_bad_json_is_source_error():
    with http_for(lambda r: httpx.Response(200, text="<html>nope</html>")) as http:
        http.label = "JSearch"
        with pytest.raises(SourceError, match="JSearch: response was not valid JSON"):
            http.get_json("https://example.test/x")


def test_headers_are_sent():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    with http_for(handler) as http:
        http.get_json("https://example.test/x", headers={"X-Test": "1"})
    assert seen[0].headers["X-Test"] == "1"


def test_api_error_message_is_kept():
    body = {"status": "ERROR", "error": {"message": "No active subscription for this API", "code": 404}}
    with http_for(lambda r: httpx.Response(404, json=body)) as http:
        http.label = "JSearch"
        with pytest.raises(SourceError, match=r"not found \(HTTP 404\): No active subscription for this API"):
            http.get_json("https://example.test/x")
