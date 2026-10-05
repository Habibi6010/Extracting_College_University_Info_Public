import pytest
import requests

from backend import tavily_client


class _FakeResponse:
    def __init__(self, payload, status_ok=True):
        self._payload = payload
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("boom")

    def json(self):
        return self._payload


def test_search_returns_results_list(monkeypatch):
    def fake_post(url, json, timeout):
        assert url == tavily_client.TAVILY_SEARCH_URL
        assert json["query"] == "query"
        return _FakeResponse({"results": [{"url": "https://a", "title": "A", "content": "c"}]})

    monkeypatch.setattr(tavily_client.requests, "post", fake_post)
    results = tavily_client.search("query", "key")
    assert results == [{"url": "https://a", "title": "A", "content": "c"}]


def test_search_missing_results_key_returns_empty_list(monkeypatch):
    monkeypatch.setattr(tavily_client.requests, "post", lambda *a, **kw: _FakeResponse({}))
    assert tavily_client.search("q", "key") == []


def test_search_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(tavily_client.requests, "post", lambda *a, **kw: _FakeResponse({}, status_ok=False))
    with pytest.raises(requests.HTTPError):
        tavily_client.search("q", "key")


def test_extract_returns_raw_content_for_matching_url(monkeypatch):
    def fake_post(url, json, timeout):
        assert url == tavily_client.TAVILY_EXTRACT_URL
        assert json["urls"] == ["https://a"]
        return _FakeResponse({"results": [{"url": "https://a", "raw_content": "hello"}]})

    monkeypatch.setattr(tavily_client.requests, "post", fake_post)
    assert tavily_client.extract("https://a", "key") == "hello"


def test_extract_returns_empty_string_when_url_not_in_results(monkeypatch):
    monkeypatch.setattr(tavily_client.requests, "post", lambda *a, **kw: _FakeResponse({"results": []}))
    assert tavily_client.extract("https://a", "key") == ""
