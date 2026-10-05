# college_finder_app/scripts/step2_find_staff.py
"""
Standalone script: walk every school already cached in cache_data/state_schools/*.json
(populate that first with `python -m scripts.step1_find_colleges`) and run the
athletics-staff lookup pipeline (backend/staff_finder.py) for each one,
saving results to the same per-school cache the web app uses
(cache_data/staff/<STATE>/<school>.json).

Safe to interrupt and re-run: a school with a usable cached result is
skipped, so a re-run only looks up what's still missing (or errored)
from the previous run.

Tavily and the LLM provider (OpenAI or Ollama) both have usage limits.
staff_finder.py is deliberately resilient to their failures (falling
back to Wikipedia / a raw page fetch, logging a warning rather than
raising) so a single flaky site never aborts a whole run — but that
same resilience means an *exhausted* usage limit would otherwise go
unnoticed and silently degrade every remaining school. This script
watches for that instead: it stops (non-zero exit) the moment a
Tavily/LLM response looks like a usage-limit/quota error, either from
a fully-failed lookup's error row or from staff_finder's own warning
log, and does NOT cache the school it stopped on, so re-running later
retries it fresh.

Usage (from the college_finder_app directory):
    python -m scripts.step2_find_staff
    python -m scripts.step2_find_staff --states TX,CA,NY
    python -m scripts.step2_find_staff --refresh
    python -m scripts.step2_find_staff --limit 100
    python -m scripts.step2_find_staff --include-closed
"""
import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from backend import cache, scorecard, staff_cache, staff_finder

logger = logging.getLogger(__name__)

# Substrings actually seen (in this repo's own error handling/tests) in
# Tavily and OpenAI usage-limit/quota responses. Matched case-insensitively
# against both a failed lookup's error-row notes and staff_finder's log
# warnings.
_LIMIT_SIGNATURES = (
    "usage limit",
    "rate limit",
    "429",
    "432",
    "quota",
    "too many requests",
)


def looks_like_limit_error(text):
    """True if `text` contains a known Tavily/LLM usage-limit signature."""
    if not text:
        return False
    lowered = str(text).lower()
    return any(sig in lowered for sig in _LIMIT_SIGNATURES)


class LimitWatchingHandler(logging.Handler):
    """Attached to backend.staff_finder's logger for the duration of a
    lookup. staff_finder catches Tavily failures itself and falls back
    (to Wikipedia / a raw fetch) rather than raising, only logging a
    warning — so a Tavily usage-limit hit would never show up as an
    error row. This handler catches it at the log line instead, flagging
    .hit the moment a warning's rendered message looks like a
    usage-limit signature."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.hit = False
        self.message = ""

    def emit(self, record):
        text = record.getMessage()
        if looks_like_limit_error(text):
            self.hit = True
            self.message = text

    def reset(self):
        self.hit = False
        self.message = ""


@dataclass
class RunResult:
    total: int = 0
    skipped_cached: int = 0
    looked_up: int = 0
    found: int = 0
    errored: int = 0
    stopped_for_limit: bool = False
    stopped_at_school: Optional[str] = None
    limit_message: str = ""


def build_school_list(cache_dir=None, states=None, include_closed=False):
    """Return every school cached in cache_data/state_schools/<STATE>.json (populated by
    scripts/step1_find_colleges.py) as {'name', 'state'} dicts, sorted by
    state name then school name. `states`, if given, restricts to that
    list of two-letter abbreviations (case-insensitive). Closed schools
    (school.operating == 0) are skipped unless include_closed is set.
    States with no cache file yet are silently skipped (nothing to
    read)."""
    target_states = scorecard.list_states()
    if states:
        wanted = {s.strip().upper() for s in states}
        target_states = [s for s in target_states if s["abbr"] in wanted]

    schools = []
    for s in target_states:
        abbr = s["abbr"]
        state_cache = cache.load(abbr, cache_dir=cache_dir)
        rows = cache.rows_for_fields(state_cache, ["school.name", "school.operating"])

        names = []
        for row in rows:
            name = (row.get("school.name") or "").strip()
            if not name:
                continue
            if not include_closed and row.get("school.operating") == 0:
                continue
            names.append(name)

        for name in sorted(names):
            schools.append({"name": name, "state": abbr})

    return schools


def run(schools, tavily_key, cache_dir=None, llm_provider_name=None, refresh=False, limit=None, on_progress=None, on_school=None):
    """Process `schools` (each {'name', 'state'}) sequentially: skip any
    with a usable cached result (unless refresh), otherwise run the
    staff-lookup pipeline and cache a real (non-error-only) result
    immediately. Stops as soon as a lookup looks like a Tavily/LLM
    usage-limit hit (see module docstring) without caching that school,
    or after `limit` fresh lookups if given. Returns a RunResult.
    `on_progress(result)`, if given, is called after every 100th fresh
    lookup. `on_school(index, total, school)`, if given, is called just
    before each fresh lookup starts."""
    result = RunResult(total=len(schools))

    handler = LimitWatchingHandler()
    watched_logger = logging.getLogger("backend.staff_finder")
    watched_logger.addHandler(handler)
    try:
        for school in schools:
            name = school["name"]
            state = school["state"]

            cached = None if refresh else staff_cache.load(state, name, cache_dir=cache_dir)
            if staff_cache.is_usable(cached):
                result.skipped_cached += 1
                continue

            if limit is not None and result.looked_up >= limit:
                break

            if on_school:
                on_school(result.looked_up + result.skipped_cached + 1, result.total, school)

            handler.reset()
            lookup = staff_finder.find_staff_for_school(name, state, tavily_key, llm_provider_name)
            result.looked_up += 1
            staff_rows = lookup["staff"]

            error_only = staff_cache.is_error_only(staff_rows)
            error_limit_message = next(
                (row.get("notes", "") for row in staff_rows if looks_like_limit_error(row.get("notes", ""))),
                None,
            ) if error_only else None

            if handler.hit or error_limit_message:
                result.stopped_for_limit = True
                result.stopped_at_school = name
                result.limit_message = handler.message or error_limit_message
                break

            if error_only:
                result.errored += 1
            else:
                result.found += 1
                staff_cache.save(state, name, staff_rows, cache_dir=cache_dir)

            if on_progress and result.looked_up % 100 == 0:
                on_progress(result)
    finally:
        watched_logger.removeHandler(handler)

    return result


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--states", help="Comma-separated two-letter state abbreviations to restrict to")
    parser.add_argument("--refresh", action="store_true", help="Re-lookup every school, ignoring the staff cache")
    parser.add_argument("--include-closed", action="store_true", help="Also look up schools marked as closed")
    parser.add_argument("--limit", type=int, default=None, help="Stop after this many fresh (non-cached) lookups")
    return parser.parse_args(argv)


def main(argv=None):
    load_dotenv()
    args = _parse_args(argv)

    tavily_key = os.environ.get("TAVILY_API_KEY")
    if not tavily_key:
        print("Error: TAVILY_API_KEY is not set. Add it to your .env file.", file=sys.stderr)
        return 1

    states = [s.strip() for s in args.states.split(",")] if args.states else None
    schools = build_school_list(states=states, include_closed=args.include_closed)
    if not schools:
        print("No schools found in cache_data/state_schools/ — run `python -m scripts.step1_find_colleges` first.")
        return 0

    print(f"{len(schools)} schools to check" + (f" (states: {args.states})" if args.states else "") + ".")

    def on_progress(result):
        print(
            f"  ...{result.looked_up + result.skipped_cached}/{result.total} checked "
            f"(fresh: {result.looked_up}, cached: {result.skipped_cached}, "
            f"found: {result.found}, errors: {result.errored})"
        )

    def on_school(index, total, school):
        print(f"[{index}/{total}] {school['state']}: {school['name']}", flush=True)

    result = run(
        schools, tavily_key, refresh=args.refresh, limit=args.limit,
        on_progress=on_progress, on_school=on_school,
    )

    print(
        f"\nDone this run: {result.looked_up} looked up fresh "
        f"({result.found} found, {result.errored} errored), "
        f"{result.skipped_cached} already cached, {result.total} schools total."
    )

    if result.stopped_for_limit:
        print(
            f"\nError: stopped at {result.stopped_at_school!r} — this looks like a Tavily/LLM "
            f"usage limit, not a one-off failure:\n  {result.limit_message}\n"
            "That school's result was NOT cached, so re-running this script later "
            "(once the limit resets) will retry it and continue from here.",
            file=sys.stderr,
        )
        return 1

    print("All schools checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
