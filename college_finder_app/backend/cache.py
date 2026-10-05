"""Per-state on-disk cache of fetched College Scorecard fields."""
import json
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "cache_data" / "state_schools"


def _cache_path(state_abbr, cache_dir):
    return Path(cache_dir) / f"{state_abbr}.json"


def load(state_abbr, cache_dir=None):
    """
    Return {'fetched_fields': set[str], 'schools': {unitid_str: {field: value}}}
    for a state. Returns an empty structure if no cache file exists yet.
    """
    if cache_dir is None:
        cache_dir = CACHE_DIR
    path = _cache_path(state_abbr, cache_dir)
    if not path.exists():
        return {"fetched_fields": set(), "schools": {}}
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {"fetched_fields": set(raw.get("fetched_fields", [])), "schools": raw.get("schools", {})}


def save(state_abbr, cache, cache_dir=None):
    """Persist `cache` (as returned by load/merge_rows) to disk."""
    if cache_dir is None:
        cache_dir = CACHE_DIR
    path = _cache_path(state_abbr, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "fetched_fields": sorted(cache["fetched_fields"]),
        "schools": cache["schools"],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2)


def missing_fields(cache, requested_fields):
    """Return the subset of requested_fields not yet in cache['fetched_fields']."""
    return [f for f in requested_fields if f not in cache["fetched_fields"]]


def merge_rows(cache, fetched_field_names, rows):
    """
    Merge freshly-fetched `rows` (each a dict with an 'id' key plus the
    fetched field names) into `cache`: unions fetched_field_names into
    cache['fetched_fields'], and updates cache['schools'] keyed by each
    row's 'id' (as a string) without discarding fields previously cached
    for that school. Mutates and returns `cache`.
    """
    cache["fetched_fields"] = set(cache["fetched_fields"]) | set(fetched_field_names)
    for row in rows:
        school_id = str(row["id"])
        existing = cache["schools"].setdefault(school_id, {})
        for field in fetched_field_names:
            existing[field] = row.get(field)
        existing["id"] = row["id"]
    return cache


def rows_for_fields(cache, requested_fields):
    """
    Return cache['schools'] values as a list, each reduced to 'id' plus
    the requested_fields (a field not yet cached for that school becomes
    None).
    """
    out = []
    for school in cache["schools"].values():
        out.append({"id": school.get("id"), **{f: school.get(f) for f in requested_fields}})
    return out
