# college_finder_app/tests/test_staff_jobs.py
import time
import json

from backend import staff_cache, staff_finder, staff_jobs


def test_start_job_processes_schools_synchronously_and_reports_done(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [
            {"name": "Coach X", "title": "Head Coach", "category": "coach", "sport": "track_field",
             "email": "", "phone": "", "source_url": "", "bio_url": ""}
        ]}

    monkeypatch.setattr(staff_finder, "find_staff_for_school", fake_find)

    job_id = staff_jobs.start_job(
        [{"name": "Example University", "state": "TX"}], refresh=False, run_in_thread=False
    )
    status = staff_jobs.get_status(job_id)
    assert status["finished"] is True
    assert status["done"] == 1
    assert status["total"] == 1
    assert status["results"][0]["name"] == "Coach X"
    assert status["results"][0]["school_name"] == "Example University"


def test_start_job_uses_cache_when_not_refreshing(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    staff_cache.save("TX", "Example University", [{"name": "Cached Coach", "category": "coach"}])

    calls = []

    def fake_find(*a, **kw):
        calls.append(1)
        return {"school_name": a[0], "state": a[1], "staff": []}

    monkeypatch.setattr(staff_finder, "find_staff_for_school", fake_find)

    job_id = staff_jobs.start_job(
        [{"name": "Example University", "state": "TX"}], refresh=False, run_in_thread=False
    )
    status = staff_jobs.get_status(job_id)
    assert status["results"][0]["name"] == "Cached Coach"
    assert calls == []


def test_start_job_retries_cached_error_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    staff_cache.save("TX", "Example University", [{"category": "error", "notes": "old 403"}])

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [{"name": "Fresh Coach", "category": "coach"}]}

    monkeypatch.setattr(staff_finder, "find_staff_for_school", fake_find)

    job_id = staff_jobs.start_job(
        [{"name": "Example University", "state": "TX"}], refresh=False, run_in_thread=False
    )
    status = staff_jobs.get_status(job_id)

    assert status["results"][0]["name"] == "Fresh Coach"


def test_start_job_retries_old_cache_version(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / "TX" / "example-university.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps({
            "school_name": "Example University",
            "state": "TX",
            "fetched_at": "2026-09-08T00:00:00+00:00",
            "staff": [{"name": "Old Cached Coach", "category": "coach"}],
        }),
        encoding="utf-8",
    )

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [{"name": "Fresh Coach", "category": "coach"}]}

    monkeypatch.setattr(staff_finder, "find_staff_for_school", fake_find)

    job_id = staff_jobs.start_job(
        [{"name": "Example University", "state": "TX"}], refresh=False, run_in_thread=False
    )
    status = staff_jobs.get_status(job_id)

    assert status["results"][0]["name"] == "Fresh Coach"


def test_start_job_does_not_cache_error_only_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [{"category": "error", "notes": "boom"}]}

    monkeypatch.setattr(staff_finder, "find_staff_for_school", fake_find)

    staff_jobs.start_job(
        [{"name": "Example University", "state": "TX"}], refresh=False, run_in_thread=False
    )

    assert staff_cache.load("TX", "Example University") is None


def test_start_job_refresh_bypasses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    staff_cache.save("TX", "Example University", [{"name": "Cached Coach", "category": "coach"}])

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [{"name": "Fresh Coach", "category": "coach"}]}

    monkeypatch.setattr(staff_finder, "find_staff_for_school", fake_find)

    job_id = staff_jobs.start_job(
        [{"name": "Example University", "state": "TX"}], refresh=True, run_in_thread=False
    )
    status = staff_jobs.get_status(job_id)
    assert status["results"][0]["name"] == "Fresh Coach"


def test_get_status_unknown_job_returns_none():
    assert staff_jobs.get_status("does-not-exist") is None


def test_run_job_survives_a_school_that_raises_and_still_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)

    def raising_find(name, state, tavily_key, llm_provider_name=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(staff_finder, "find_staff_for_school", raising_find)

    job_id = staff_jobs.start_job(
        [{"name": "Example University", "state": "TX"}], refresh=False, run_in_thread=False
    )
    status = staff_jobs.get_status(job_id)
    assert status["finished"] is True
    assert status["done"] == 1
    assert status["results"][0]["category"] == "error"
    assert "boom" in status["results"][0]["notes"]


def test_start_job_run_in_thread_true_eventually_finishes(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [
            {"name": "Coach X", "title": "Head Coach", "category": "coach", "sport": "track_field",
             "email": "", "phone": "", "source_url": "", "bio_url": ""}
        ]}

    monkeypatch.setattr(staff_finder, "find_staff_for_school", fake_find)

    job_id = staff_jobs.start_job(
        [{"name": "Example University", "state": "TX"}], refresh=False, run_in_thread=True
    )
    deadline = time.time() + 5
    status = staff_jobs.get_status(job_id)
    while not status["finished"] and time.time() < deadline:
        time.sleep(0.05)
        status = staff_jobs.get_status(job_id)
    assert status["finished"] is True
    assert status["results"][0]["name"] == "Coach X"
