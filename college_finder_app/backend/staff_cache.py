"""Per-school on-disk cache of athletics staff lookup results, mirroring
backend/cache.py's per-state cache pattern."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "cache_data" / "staff"
CACHE_VERSION = 2


def _slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "school"


def _cache_path(state_abbr, school_name, cache_dir):
    return Path(cache_dir) / state_abbr / f"{_slugify(school_name)}.json"


def load(state_abbr, school_name, cache_dir=None):
    """Return the cached {'school_name', 'state', 'fetched_at', 'staff'}
    dict for this school, or None if nothing is cached yet."""
    if cache_dir is None:
        cache_dir = CACHE_DIR
    path = _cache_path(state_abbr, school_name, cache_dir)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(state_abbr, school_name, staff_rows, cache_dir=None):
    """Write the staff lookup result for this school to disk and return
    the saved {'school_name', 'state', 'fetched_at', 'staff'} dict."""
    if cache_dir is None:
        cache_dir = CACHE_DIR
    path = _cache_path(state_abbr, school_name, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "cache_version": CACHE_VERSION,
        "school_name": school_name,
        "state": state_abbr,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "staff": staff_rows,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return record


def is_error_only(staff_rows):
    """True if `staff_rows` is non-empty and every row is a lookup-failure
    row (category='error') — i.e. the lookup produced nothing usable."""
    return bool(staff_rows) and all(row.get("category") == "error" for row in staff_rows)


def is_usable(cached):
    """True if `cached` (as returned by load()) is on the current
    CACHE_VERSION and holds a real (non-error-only) result, so a lookup
    can be skipped in favor of it."""
    return (
        cached is not None
        and cached.get("cache_version") == CACHE_VERSION
        and not is_error_only(cached.get("staff", []))
    )
