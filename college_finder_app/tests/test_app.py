import pytest

from backend import cache
import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("SCORECARD_API_KEY", "test-key")
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_states_endpoint(client):
    resp = client.get("/api/states")
    assert resp.status_code == 200
    data = resp.get_json()
    assert {"abbr": "TX", "name": "Texas"} in data


def test_fields_endpoint(client):
    resp = client.get("/api/fields")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "categories" in data
    assert "value_labels" in data


def test_colleges_unknown_state(client):
    resp = client.get("/api/colleges?state=ZZ&fields=school.name")
    assert resp.status_code == 400


def test_colleges_no_fields(client):
    resp = client.get("/api/colleges?state=TX&fields=")
    assert resp.status_code == 400


def test_colleges_fetches_and_caches(client, monkeypatch):
    calls = []

    def fake_fetch(state_abbr, fields, api_key, per_page=100):
        calls.append((state_abbr, tuple(fields)))
        return [{"id": 1, "school.name": "Test U"}]

    monkeypatch.setattr(app_module.scorecard, "fetch_schools", fake_fetch)

    resp = client.get("/api/colleges?state=TX&fields=school.name")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["state"] == "TX"
    assert data["count"] == 1
    assert data["schools"][0]["school.name"] == "Test U"
    assert len(calls) == 1

    # Same field, same state -> served from cache, no second fetch.
    resp2 = client.get("/api/colleges?state=TX&fields=school.name")
    assert resp2.status_code == 200
    assert len(calls) == 1


def test_colleges_refresh_forces_refetch(client, monkeypatch):
    calls = []

    def fake_fetch(state_abbr, fields, api_key, per_page=100):
        calls.append(1)
        return [{"id": 1, "school.name": "Test U"}]

    monkeypatch.setattr(app_module.scorecard, "fetch_schools", fake_fetch)
    client.get("/api/colleges?state=TX&fields=school.name")
    client.get("/api/colleges?state=TX&fields=school.name&refresh=1")
    assert len(calls) == 2


def test_colleges_upstream_error(client, monkeypatch):
    def fake_fetch(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module.scorecard, "fetch_schools", fake_fetch)
    resp = client.get("/api/colleges?state=TX&fields=school.name")
    assert resp.status_code == 502


def test_colleges_upstream_error_redacts_api_key(client, monkeypatch):
    api_key = "test-key"

    def fake_fetch(*a, **kw):
        raise RuntimeError(
            f"403 Client Error: Forbidden for url: "
            f"https://api.data.gov/ed/collegescorecard/v1/schools.json?api_key={api_key}"
        )

    monkeypatch.setattr(app_module.scorecard, "fetch_schools", fake_fetch)
    resp = client.get("/api/colleges?state=TX&fields=school.name")
    assert resp.status_code == 502
    body_text = resp.get_data(as_text=True)
    assert api_key not in body_text
    assert "***" in body_text


def test_staff_find_requires_schools(client):
    resp = client.post("/api/staff/find", json={"schools": []})
    assert resp.status_code == 400


def test_staff_find_and_status_synchronous_in_tests(client, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module.staff_jobs.staff_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [
            {"name": "Coach X", "title": "Head Coach", "category": "coach", "sport": "track_field",
             "email": "", "phone": "", "source_url": "", "bio_url": ""}
        ]}

    monkeypatch.setattr(app_module.staff_jobs.staff_finder, "find_staff_for_school", fake_find)

    resp = client.post("/api/staff/find", json={"schools": [{"name": "Example University", "state": "TX"}]})
    assert resp.status_code == 202
    job_id = resp.get_json()["job_id"]

    status_resp = client.get(f"/api/staff/status/{job_id}")
    assert status_resp.status_code == 200
    data = status_resp.get_json()
    assert data["finished"] is True
    assert data["done"] == 1
    assert data["results"][0]["name"] == "Coach X"


def test_staff_status_unknown_job_returns_404(client):
    resp = client.get("/api/staff/status/does-not-exist")
    assert resp.status_code == 404


def test_staff_find_end_to_end_through_staff_finder(client, monkeypatch, tmp_path):
    from backend import llm_provider, tavily_client, wikipedia_lookup

    monkeypatch.setattr(app_module.staff_jobs.staff_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    monkeypatch.setattr(
        tavily_client, "search",
        lambda query, api_key, max_results=5, timeout=30: [{"url": "https://x", "title": "t", "content": "c"}],
    )
    monkeypatch.setattr(
        llm_provider, "pick_url",
        lambda school_name, purpose, results, provider=None: (
            {"url": "https://general.example.com", "confidence": "high", "notes": ""}
            if purpose == "general_athletics" else {"url": None, "confidence": "none", "notes": ""}
        ),
    )
    monkeypatch.setattr(wikipedia_lookup, "find_staff_link", lambda school_name: None)
    monkeypatch.setattr(tavily_client, "extract", lambda url, api_key, timeout=30: "directory text")
    monkeypatch.setattr(
        llm_provider, "extract_staff",
        lambda school_name, page_text, source_url, provider=None: [
            {"name": "Alex AD", "title": "Athletic Director", "category": "admin",
             "sport": "", "email": "alex@ex.edu", "phone": "", "bio_url": ""}
        ],
    )

    resp = client.post("/api/staff/find", json={"schools": [{"name": "Example University", "state": "TX"}]})
    job_id = resp.get_json()["job_id"]
    status = client.get(f"/api/staff/status/{job_id}").get_json()

    assert status["finished"] is True
    assert status["results"][0]["name"] == "Alex AD"
    assert status["results"][0]["category"] == "admin"
    assert status["results"][0]["email"] == "alex@ex.edu"
