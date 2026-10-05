import csv
import json

import pytest

from backend import cache
from scripts import step1_find_colleges as export_colleges


def test_build_dataset_fetches_missing_fields_and_caches(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(state_abbr, fields, api_key):
        calls.append(state_abbr)
        return [{"id": 1, "school.name": "Texas A"}]

    monkeypatch.setattr(export_colleges.scorecard, "fetch_schools", fake_fetch)

    rows, failed = export_colleges.build_dataset(
        ["school.name"], cache_dir=tmp_path, api_key="fake-key", states=["TX"]
    )

    assert calls == ["TX"]
    assert failed == []
    assert rows == [{"id": 1, "school.name": "Texas A", "state_abbr": "TX", "state_name": "Texas"}]

    saved = cache.load("TX", cache_dir=tmp_path)
    assert saved["fetched_fields"] == {"school.name"}
    assert saved["schools"]["1"]["school.name"] == "Texas A"


def test_build_dataset_skips_fetch_when_all_fields_cached(monkeypatch, tmp_path):
    c = {"fetched_fields": {"school.name"}, "schools": {"1": {"id": 1, "school.name": "Cached U"}}}
    cache.save("TX", c, cache_dir=tmp_path)

    def fail_fetch(state_abbr, fields, api_key):
        raise AssertionError("fetch_schools should not be called when cache is complete")

    monkeypatch.setattr(export_colleges.scorecard, "fetch_schools", fail_fetch)

    rows, failed = export_colleges.build_dataset(
        ["school.name"], cache_dir=tmp_path, api_key="fake-key", states=["TX"]
    )

    assert failed == []
    assert rows == [{"id": 1, "school.name": "Cached U", "state_abbr": "TX", "state_name": "Texas"}]


def test_build_dataset_refresh_forces_fetch_even_when_cached(monkeypatch, tmp_path):
    c = {"fetched_fields": {"school.name"}, "schools": {"1": {"id": 1, "school.name": "Old Name"}}}
    cache.save("TX", c, cache_dir=tmp_path)

    def fake_fetch(state_abbr, fields, api_key):
        return [{"id": 1, "school.name": "New Name"}]

    monkeypatch.setattr(export_colleges.scorecard, "fetch_schools", fake_fetch)

    rows, failed = export_colleges.build_dataset(
        ["school.name"], cache_dir=tmp_path, api_key="fake-key", states=["TX"], refresh=True
    )

    assert failed == []
    assert rows[0]["school.name"] == "New Name"


def test_build_dataset_continues_on_state_fetch_failure_and_reports_it(monkeypatch, tmp_path):
    def fake_fetch(state_abbr, fields, api_key):
        if state_abbr == "TX":
            raise RuntimeError("boom")
        return [{"id": 2, "school.name": "Alabama A"}]

    monkeypatch.setattr(export_colleges.scorecard, "fetch_schools", fake_fetch)

    rows, failed = export_colleges.build_dataset(
        ["school.name"], cache_dir=tmp_path, api_key="fake-key", states=["TX", "AL"]
    )

    assert failed == [{"abbr": "TX", "name": "Texas", "error": "boom"}]
    assert rows == [{"id": 2, "school.name": "Alabama A", "state_abbr": "AL", "state_name": "Alabama"}]


def test_build_dataset_raises_missing_api_key_before_fetching_any_state(monkeypatch, tmp_path):
    def fail_fetch(state_abbr, fields, api_key):
        raise AssertionError("fetch_schools should not be called without an api key")

    monkeypatch.setattr(export_colleges.scorecard, "fetch_schools", fail_fetch)

    with pytest.raises(export_colleges.MissingApiKeyError):
        export_colleges.build_dataset(
            ["school.name"], cache_dir=tmp_path, api_key=None, states=["TX", "AL"]
        )

    assert cache.load("TX", cache_dir=tmp_path)["schools"] == {}
    assert cache.load("AL", cache_dir=tmp_path)["schools"] == {}


def test_build_dataset_states_filter_restricts_to_subset(monkeypatch, tmp_path):
    def fake_fetch(state_abbr, fields, api_key):
        return [{"id": 1, "school.name": f"{state_abbr} U"}]

    monkeypatch.setattr(export_colleges.scorecard, "fetch_schools", fake_fetch)

    rows, _ = export_colleges.build_dataset(
        ["school.name"], cache_dir=tmp_path, api_key="fake-key", states=["WY"]
    )

    assert {r["state_abbr"] for r in rows} == {"WY"}


def test_write_csv_writes_header_and_rows(tmp_path):
    rows = [
        {"state_abbr": "TX", "state_name": "Texas", "id": 1, "school.name": "Texas A"},
        {"state_abbr": "AL", "state_name": "Alabama", "id": 2, "school.name": "Alabama A"},
    ]
    out_path = tmp_path / "out.csv"

    export_colleges.write_csv(rows, ["id", "school.name"], out_path)

    with open(out_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        written = list(reader)

    assert reader.fieldnames == ["state_abbr", "state_name", "id", "school.name"]
    assert written[0] == {"state_abbr": "TX", "state_name": "Texas", "id": "1", "school.name": "Texas A"}
    assert written[1]["state_abbr"] == "AL"


def test_write_json_round_trips(tmp_path):
    rows = [{"state_abbr": "TX", "state_name": "Texas", "id": 1, "school.name": "Texas A"}]
    out_path = tmp_path / "out.json"

    export_colleges.write_json(rows, out_path)

    with open(out_path, encoding="utf-8") as f:
        assert json.load(f) == rows
