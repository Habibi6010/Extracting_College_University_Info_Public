import pytest
import requests

from backend import scorecard


def test_normalize_state_accepts_full_name():
    assert scorecard.normalize_state("Texas") == "TX"


def test_normalize_state_accepts_abbreviation():
    assert scorecard.normalize_state("tx") == "TX"


def test_normalize_state_rejects_unknown():
    with pytest.raises(ValueError):
        scorecard.normalize_state("Not A State")


def test_list_states_includes_texas_and_dc():
    states = scorecard.list_states()
    assert {"abbr": "TX", "name": "Texas"} in states
    assert {"abbr": "DC", "name": "District of Columbia"} in states


def test_list_states_sorted_by_name():
    states = scorecard.list_states()
    names = [s["name"] for s in states]
    assert names == sorted(names)


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json


def test_fetch_schools_single_page(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params)
        return FakeResponse({
            "metadata": {"page": 0, "total": 2, "per_page": 100},
            "results": [
                {"id": 1, "school.name": "A", "school.school_url": "a.edu"},
                {"id": 2, "school.name": "B", "school.school_url": "https://b.edu"},
            ],
        })

    monkeypatch.setattr(scorecard.requests, "get", fake_get)
    rows = scorecard.fetch_schools("TX", ["school.name", "school.school_url"], "fake-key")
    assert len(calls) == 1
    assert calls[0]["school.state"] == "TX"
    assert rows[0] == {"id": 1, "school.name": "A", "school.school_url": "https://a.edu"}
    assert rows[1]["school.school_url"] == "https://b.edu"


def test_fetch_schools_paginates(monkeypatch):
    pages = {
        0: {"metadata": {"page": 0, "total": 3, "per_page": 2},
            "results": [{"id": 1, "school.name": "A"}, {"id": 2, "school.name": "B"}]},
        1: {"metadata": {"page": 1, "total": 3, "per_page": 2},
            "results": [{"id": 3, "school.name": "C"}]},
    }
    call_count = {"n": 0}

    def fake_get(url, params, timeout):
        call_count["n"] += 1
        return FakeResponse(pages[params["page"]])

    monkeypatch.setattr(scorecard.requests, "get", fake_get)
    rows = scorecard.fetch_schools("TX", ["school.name"], "fake-key", per_page=2)
    assert [r["id"] for r in rows] == [1, 2, 3]
    assert call_count["n"] == 2


def test_fetch_schools_raises_on_http_error(monkeypatch):
    def fake_get(url, params, timeout):
        return FakeResponse({}, status_code=500)

    monkeypatch.setattr(scorecard.requests, "get", fake_get)
    with pytest.raises(requests.HTTPError):
        scorecard.fetch_schools("TX", ["school.name"], "fake-key")
