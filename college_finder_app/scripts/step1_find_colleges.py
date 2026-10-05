"""
Standalone script: export every college/university, for every state (+ DC),
to a single CSV and JSON file — no web UI, no picking one state at a time.

Reuses the exact same fetch + on-disk cache (backend/cache.py,
backend/scorecard.py) as the Flask app, so results are cached identically:
run it once to warm the cache (making one College Scorecard API call per
state), run it again and it's instant with zero network calls, and the web
app's per-state cache stays in sync either way.

Usage (from the college_finder_app directory):
    python -m scripts.step1_find_colleges
    python -m scripts.step1_find_colleges --fields id,school.name,school.city
    python -m scripts.step1_find_colleges --refresh
    python -m scripts.step1_find_colleges --states TX,CA,NY
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

# Make `backend` importable whether this is run as `python -m scripts.step1_find_colleges`
# (cwd = college_finder_app, already on sys.path) or as a plain script
# (`python scripts/step1_find_colleges.py`, which only puts scripts/ on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from backend import cache, field_catalog, scorecard

DEFAULT_FIELDS = [
    "id",
    "school.name",
    "school.alias",
    "school.address",
    "school.city",
    "school.state",
    "school.zip",
    "school.school_url",
    "school.ownership",
    "school.operating",
]

DEFAULT_OUT_DIR = Path(__file__).parent.parent / "exports"


class MissingApiKeyError(RuntimeError):
    """Raised when a fetch is needed but no SCORECARD_API_KEY was provided."""


def build_dataset(fields, cache_dir=None, api_key=None, refresh=False, states=None, on_progress=None):
    """
    Ensure every target state's on-disk cache has `fields` cached (fetching
    from College Scorecard for any state that's missing them, or every
    state if `refresh` is true), then return (rows, failed):

    - rows: list of decoded school dicts (field_catalog.decode_row applied),
      each tagged with 'state_abbr' and 'state_name', across every target
      state — including states whose fetch failed, using whatever was
      already cached for them.
    - failed: list of {"abbr", "name", "error"} for states whose fetch
      raised an exception. Processing continues past a failed state.

    `states`, if given, restricts to that list of two-letter abbreviations
    (case-insensitive) instead of all states + DC.

    Raises MissingApiKeyError before touching any state (no fetches, no
    cache writes) if api_key is falsy and at least one target state needs
    a fetch.

    `on_progress`, if given, is called once per state as
    on_progress(abbr, name, total=<schools cached>, new=<freshly fetched>,
    error=<str or None>).
    """
    target_states = scorecard.list_states()
    if states:
        wanted = {s.strip().upper() for s in states}
        target_states = [s for s in target_states if s["abbr"] in wanted]

    caches = {s["abbr"]: cache.load(s["abbr"], cache_dir=cache_dir) for s in target_states}
    needs_fetch = {
        abbr: refresh or bool(cache.missing_fields(c, fields))
        for abbr, c in caches.items()
    }
    if any(needs_fetch.values()) and not api_key:
        raise MissingApiKeyError(
            "SCORECARD_API_KEY is not set but at least one state needs fetching"
        )

    catalog = field_catalog.load_catalog()
    rows = []
    failed = []
    for s in target_states:
        abbr, name = s["abbr"], s["name"]
        school_cache = caches[abbr]
        new_count = 0
        error = None

        if needs_fetch[abbr]:
            try:
                fetched_rows = scorecard.fetch_schools(abbr, fields, api_key)
            except Exception as exc:
                error = str(exc)
                failed.append({"abbr": abbr, "name": name, "error": error})
            else:
                new_count = len(fetched_rows)
                school_cache = cache.merge_rows(school_cache, fields, fetched_rows)
                cache.save(abbr, school_cache, cache_dir=cache_dir)

        for row in cache.rows_for_fields(school_cache, fields):
            decoded = field_catalog.decode_row(row, catalog)
            decoded["state_abbr"] = abbr
            decoded["state_name"] = name
            rows.append(decoded)

        if on_progress:
            on_progress(abbr, name, total=len(school_cache["schools"]), new=new_count, error=error)

    return rows, failed


def write_csv(rows, fields, path):
    """Write rows to `path` as CSV with columns state_abbr, state_name, *fields."""
    columns = ["state_abbr", "state_name"] + list(fields)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c) for c in columns})


def write_json(rows, path):
    """Write rows to `path` as a JSON array."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fields", help="Comma-separated API field names (default: a basic identity/location set)")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch every state, ignoring the cache")
    parser.add_argument("--states", help="Comma-separated two-letter state abbreviations to restrict to")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Directory to write all_colleges.csv/.json into")
    return parser.parse_args(argv)


def main(argv=None):
    load_dotenv()
    args = _parse_args(argv)

    fields = [f.strip() for f in args.fields.split(",")] if args.fields else DEFAULT_FIELDS
    states = [s.strip() for s in args.states.split(",")] if args.states else None
    api_key = os.environ.get("SCORECARD_API_KEY")

    def on_progress(abbr, name, total, new, error):
        if error:
            print(f"  {abbr}: FAILED ({error}) - using cached data ({total} schools)")
        elif new:
            print(f"  {abbr}: {total} schools ({new} newly fetched)")
        else:
            print(f"  {abbr}: {total} schools (cached)")

    try:
        rows, failed = build_dataset(
            fields, api_key=api_key, refresh=args.refresh, states=states, on_progress=on_progress
        )
    except MissingApiKeyError as exc:
        print(f"Error: {exc}. Set SCORECARD_API_KEY in your .env file.", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    csv_path = out_dir / "all_colleges.csv"
    json_path = out_dir / "all_colleges.json"
    write_csv(rows, fields, csv_path)
    write_json(rows, json_path)

    print(f"\nWrote {len(rows)} schools across {len(rows) and len({r['state_abbr'] for r in rows})} states to:")
    print(f"  {csv_path}")
    print(f"  {json_path}")
    if failed:
        print(f"\n{len(failed)} state(s) failed to fetch (cached data, if any, was still included):")
        for f in failed:
            print(f"  {f['abbr']} ({f['name']}): {f['error']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
