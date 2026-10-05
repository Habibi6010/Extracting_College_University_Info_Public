# college_finder_app/tests/test_wikipedia_lookup.py
import requests

from backend import wikipedia_lookup


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_find_staff_link_returns_matching_external_link(monkeypatch):
    def fake_get(url, params, headers, timeout):
        if params.get("list") == "search":
            return _FakeResponse({"query": {"search": [{"title": "Example University Athletics"}]}})
        return _FakeResponse({
            "query": {"pages": {"1": {"extlinks": [
                {"*": "https://example.edu"},
                {"*": "https://exampleathletics.com/staff-directory"},
            ]}}}
        })

    monkeypatch.setattr(wikipedia_lookup.requests, "get", fake_get)
    assert wikipedia_lookup.find_staff_link("Example University") == "https://exampleathletics.com/staff-directory"


def test_find_staff_link_returns_none_when_no_article_found(monkeypatch):
    monkeypatch.setattr(
        wikipedia_lookup.requests, "get",
        lambda *a, **kw: _FakeResponse({"query": {"search": []}}),
    )
    assert wikipedia_lookup.find_staff_link("Nonexistent College") is None


def test_find_staff_link_returns_none_when_no_link_matches(monkeypatch):
    def fake_get(url, params, headers, timeout):
        if params.get("list") == "search":
            return _FakeResponse({"query": {"search": [{"title": "Example University"}]}})
        return _FakeResponse({"query": {"pages": {"1": {"extlinks": [{"*": "https://example.edu"}]}}}})

    monkeypatch.setattr(wikipedia_lookup.requests, "get", fake_get)
    assert wikipedia_lookup.find_staff_link("Example University") is None


def test_find_staff_link_returns_none_when_wikipedia_forbidden(monkeypatch):
    class _ForbiddenResponse:
        def raise_for_status(self):
            raise requests.HTTPError(
                "403 Client Error: Forbidden for url: https://en.wikipedia.org/w/api.php"
            )

    monkeypatch.setattr(
        wikipedia_lookup.requests,
        "get",
        lambda *a, **kw: _ForbiddenResponse(),
    )

    assert wikipedia_lookup.find_staff_link("The University of Texas at Dallas") is None
