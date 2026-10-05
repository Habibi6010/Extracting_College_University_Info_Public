import json
from pathlib import Path

from backend import cache


def test_default_cache_reads_and_writes_state_schools(tmp_path, monkeypatch):
    # Mirror the configured app-relative path without touching real cached data.
    app_dir = Path(cache.__file__).parent.parent
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / cache.CACHE_DIR.relative_to(app_dir))
    state_dir = tmp_path / "cache_data" / "state_schools"
    state_dir.mkdir(parents=True)
    c = {"fetched_fields": {"school.name"}, "schools": {"1": {"id": 1, "school.name": "Example U"}}}
    (state_dir / "TX.json").write_text(
        json.dumps({"fetched_fields": sorted(c["fetched_fields"]), "schools": c["schools"]}),
        encoding="utf-8",
    )

    assert cache.load("TX") == c
    cache.save("AL", c)
    assert json.loads((state_dir / "AL.json").read_text(encoding="utf-8"))["schools"] == c["schools"]
    assert cache.load("AL") == c
    assert not (tmp_path / "cache_data" / "AL.json").exists()


def test_load_missing_file_returns_empty_structure(tmp_path):
    result = cache.load("TX", cache_dir=tmp_path)
    assert result == {"fetched_fields": set(), "schools": {}}


def test_missing_fields_all_missing_when_nothing_cached():
    empty = {"fetched_fields": set(), "schools": {}}
    assert cache.missing_fields(empty, ["a", "b"]) == ["a", "b"]


def test_missing_fields_only_returns_uncached():
    c = {"fetched_fields": {"a"}, "schools": {}}
    assert cache.missing_fields(c, ["a", "b"]) == ["b"]


def test_merge_rows_adds_schools_and_fields():
    c = {"fetched_fields": set(), "schools": {}}
    rows = [{"id": 1, "a": "x"}, {"id": 2, "a": "y"}]
    cache.merge_rows(c, ["a"], rows)
    assert c["fetched_fields"] == {"a"}
    assert c["schools"]["1"] == {"id": 1, "a": "x"}
    assert c["schools"]["2"] == {"id": 2, "a": "y"}


def test_merge_rows_does_not_clobber_previously_cached_fields():
    c = {"fetched_fields": {"a"}, "schools": {"1": {"id": 1, "a": "x"}}}
    rows = [{"id": 1, "b": "z"}]
    cache.merge_rows(c, ["b"], rows)
    assert c["schools"]["1"] == {"id": 1, "a": "x", "b": "z"}
    assert c["fetched_fields"] == {"a", "b"}


def test_save_then_load_round_trip(tmp_path):
    c = {"fetched_fields": {"a", "b"}, "schools": {"1": {"id": 1, "a": "x", "b": "y"}}}
    cache.save("TX", c, cache_dir=tmp_path)
    loaded = cache.load("TX", cache_dir=tmp_path)
    assert loaded["fetched_fields"] == {"a", "b"}
    assert loaded["schools"] == {"1": {"id": 1, "a": "x", "b": "y"}}


def test_rows_for_fields_reduces_to_requested_fields_with_none_for_missing():
    c = {"fetched_fields": {"a", "b"}, "schools": {"1": {"id": 1, "a": "x", "b": "y"}}}
    rows = cache.rows_for_fields(c, ["a", "c"])
    assert rows == [{"id": 1, "a": "x", "c": None}]
