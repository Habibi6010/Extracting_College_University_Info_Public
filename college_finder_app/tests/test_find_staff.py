# college_finder_app/tests/test_find_staff.py
import logging

import pytest

from backend import cache, staff_cache
from scripts import step2_find_staff as find_staff


def _save_state(cache_dir, abbr, schools):
    """schools: list of (name, operating) tuples."""
    c = {"fetched_fields": {"school.name", "school.state", "school.operating"}, "schools": {}}
    for i, (name, operating) in enumerate(schools):
        c["schools"][str(i)] = {
            "id": i, "school.name": name, "school.state": abbr, "school.operating": operating,
        }
    cache.save(abbr, c, cache_dir=cache_dir)


# ---- build_school_list ----

def test_build_school_list_reads_every_cached_state_sorted(tmp_path):
    _save_state(tmp_path, "TX", [("Texas U", 1)])
    _save_state(tmp_path, "AL", [("Alabama U", 1)])

    schools = find_staff.build_school_list(cache_dir=tmp_path)

    assert schools == [
        {"name": "Alabama U", "state": "AL"},
        {"name": "Texas U", "state": "TX"},
    ]


def test_build_school_list_sorts_by_name_within_a_state(tmp_path):
    _save_state(tmp_path, "TX", [("Zeta College", 1), ("Alpha College", 1)])

    schools = find_staff.build_school_list(cache_dir=tmp_path)

    assert [s["name"] for s in schools] == ["Alpha College", "Zeta College"]


def test_build_school_list_excludes_closed_schools_by_default(tmp_path):
    _save_state(tmp_path, "TX", [("Open U", 1), ("Closed U", 0)])

    schools = find_staff.build_school_list(cache_dir=tmp_path)

    assert [s["name"] for s in schools] == ["Open U"]


def test_build_school_list_include_closed_keeps_them(tmp_path):
    _save_state(tmp_path, "TX", [("Open U", 1), ("Closed U", 0)])

    schools = find_staff.build_school_list(cache_dir=tmp_path, include_closed=True)

    assert {s["name"] for s in schools} == {"Open U", "Closed U"}


def test_build_school_list_skips_blank_names(tmp_path):
    _save_state(tmp_path, "TX", [("", 1), ("Real U", 1)])

    schools = find_staff.build_school_list(cache_dir=tmp_path)

    assert [s["name"] for s in schools] == ["Real U"]


def test_build_school_list_states_filter_restricts_to_subset(tmp_path):
    _save_state(tmp_path, "TX", [("Texas U", 1)])
    _save_state(tmp_path, "AL", [("Alabama U", 1)])

    schools = find_staff.build_school_list(cache_dir=tmp_path, states=["AL"])

    assert schools == [{"name": "Alabama U", "state": "AL"}]


def test_build_school_list_skips_states_with_no_cache_file(tmp_path):
    _save_state(tmp_path, "TX", [("Texas U", 1)])

    # AL has no cache_data/AL.json at all in tmp_path.
    schools = find_staff.build_school_list(cache_dir=tmp_path)

    assert schools == [{"name": "Texas U", "state": "TX"}]


# ---- looks_like_limit_error ----

@pytest.mark.parametrize("text", [
    "432 Client Error: usage limit exceeded",
    "Error code: 429 - rate limit reached",
    "You exceeded your current quota",
    "RateLimitError: Too Many Requests",
])
def test_looks_like_limit_error_matches_known_signatures(text):
    assert find_staff.looks_like_limit_error(text) is True


@pytest.mark.parametrize("text", [
    "",
    "connection reset by peer",
    "404 Not Found",
    "LLM output not parseable",
])
def test_looks_like_limit_error_does_not_match_other_errors(text):
    assert find_staff.looks_like_limit_error(text) is False


# ---- LimitWatchingHandler ----

def test_limit_watching_handler_flags_on_matching_warning():
    handler = find_staff.LimitWatchingHandler()
    logger = logging.getLogger("backend.staff_finder")
    logger.addHandler(handler)
    try:
        logger.warning("Tavily search failed for X (general_athletics); falling back to Wikipedia: %s",
                        "432 Client Error: usage limit exceeded")
    finally:
        logger.removeHandler(handler)

    assert handler.hit is True
    assert "usage limit" in handler.message.lower()


def test_limit_watching_handler_ignores_unrelated_warning():
    handler = find_staff.LimitWatchingHandler()
    logger = logging.getLogger("backend.staff_finder")
    logger.addHandler(handler)
    try:
        logger.warning("Tavily extract failed for %s; falling back to direct fetch: %s", "https://x", "timeout")
    finally:
        logger.removeHandler(handler)

    assert handler.hit is False


# ---- run: the main processing loop ----

def _school(name, state="TX"):
    return {"name": name, "state": state}


def test_run_skips_schools_with_a_usable_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    staff_cache.save("TX", "Cached U", [{"name": "Coach", "category": "coach"}], cache_dir=tmp_path)

    calls = []

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        calls.append(name)
        return {"school_name": name, "state": state, "staff": [{"name": "New Coach", "category": "coach"}]}

    monkeypatch.setattr(find_staff.staff_finder, "find_staff_for_school", fake_find)

    result = find_staff.run([_school("Cached U")], tavily_key="key", cache_dir=tmp_path)

    assert calls == []
    assert result.skipped_cached == 1
    assert result.looked_up == 0
    assert result.stopped_for_limit is False


def test_run_saves_fresh_lookup_results(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [{"name": "New Coach", "category": "coach"}]}

    monkeypatch.setattr(find_staff.staff_finder, "find_staff_for_school", fake_find)

    result = find_staff.run([_school("Fresh U")], tavily_key="key", cache_dir=tmp_path)

    assert result.looked_up == 1
    assert result.skipped_cached == 0
    loaded = staff_cache.load("TX", "Fresh U", cache_dir=tmp_path)
    assert loaded["staff"][0]["name"] == "New Coach"


def test_run_does_not_cache_error_only_results(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [{"category": "error", "notes": "site down"}]}

    monkeypatch.setattr(find_staff.staff_finder, "find_staff_for_school", fake_find)

    result = find_staff.run([_school("Broken U")], tavily_key="key", cache_dir=tmp_path)

    assert result.looked_up == 1
    assert result.errored == 1
    assert staff_cache.load("TX", "Broken U", cache_dir=tmp_path) is None
    assert result.stopped_for_limit is False


def test_run_stops_when_error_row_looks_like_a_limit_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state,
                "staff": [{"category": "error", "notes": "RateLimitError: You exceeded your current quota"}]}

    monkeypatch.setattr(find_staff.staff_finder, "find_staff_for_school", fake_find)

    result = find_staff.run(
        [_school("School A"), _school("School B")], tavily_key="key", cache_dir=tmp_path
    )

    assert result.stopped_for_limit is True
    assert result.looked_up == 1
    assert result.stopped_at_school == "School A"


def test_run_stops_when_a_limit_warning_is_logged_even_without_an_error_row(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        logging.getLogger("backend.staff_finder").warning(
            "Tavily search failed for %s (general_athletics); falling back to Wikipedia: %s",
            name, "432 Client Error: usage limit exceeded",
        )
        # Pipeline recovered via Wikipedia fallback, so this looks like a normal result.
        return {"school_name": name, "state": state, "staff": [{"name": "Wiki Coach", "category": "coach"}]}

    monkeypatch.setattr(find_staff.staff_finder, "find_staff_for_school", fake_find)

    result = find_staff.run(
        [_school("School A"), _school("School B")], tavily_key="key", cache_dir=tmp_path
    )

    assert result.stopped_for_limit is True
    assert result.stopped_at_school == "School A"
    # The degraded result for School A should not be cached, so a re-run retries it.
    assert staff_cache.load("TX", "School A", cache_dir=tmp_path) is None


def test_run_does_not_process_past_a_limit_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    calls = []

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        calls.append(name)
        return {"school_name": name, "state": state,
                "staff": [{"category": "error", "notes": "429 rate limit"}]}

    monkeypatch.setattr(find_staff.staff_finder, "find_staff_for_school", fake_find)

    find_staff.run([_school("A"), _school("B"), _school("C")], tavily_key="key", cache_dir=tmp_path)

    assert calls == ["A"]


def test_run_honors_limit_argument_for_fresh_lookups(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    calls = []

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        calls.append(name)
        return {"school_name": name, "state": state, "staff": [{"name": "Coach", "category": "coach"}]}

    monkeypatch.setattr(find_staff.staff_finder, "find_staff_for_school", fake_find)

    result = find_staff.run(
        [_school("A"), _school("B"), _school("C")], tavily_key="key", cache_dir=tmp_path, limit=2
    )

    assert calls == ["A", "B"]
    assert result.looked_up == 2
    assert result.stopped_for_limit is False


def test_run_refresh_bypasses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(staff_cache, "CACHE_DIR", tmp_path)
    staff_cache.save("TX", "Cached U", [{"name": "Old Coach", "category": "coach"}], cache_dir=tmp_path)

    def fake_find(name, state, tavily_key, llm_provider_name=None):
        return {"school_name": name, "state": state, "staff": [{"name": "Fresh Coach", "category": "coach"}]}

    monkeypatch.setattr(find_staff.staff_finder, "find_staff_for_school", fake_find)

    result = find_staff.run([_school("Cached U")], tavily_key="key", cache_dir=tmp_path, refresh=True)

    assert result.looked_up == 1
    loaded = staff_cache.load("TX", "Cached U", cache_dir=tmp_path)
    assert loaded["staff"][0]["name"] == "Fresh Coach"
