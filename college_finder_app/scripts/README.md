# scripts/

Standalone command-line tools for this app (as opposed to the web UI in
`app.py`). The one-time `build_field_catalog.py` generator lives in the
repo-root `API_Documentations/` folder instead, next to the Data
Dictionary xlsx it reads.

## `step1_find_colleges.py` (step 1)

Exports every college/university, for every US state + DC, to one combined
`all_colleges.csv` and `all_colleges.json` — no need to pick a state in the
web UI one at a time.

Reuses the exact same fetch + on-disk cache as the web app
(`backend/scorecard.py` + `backend/cache.py`), writing to the same
`cache_data/state_schools/<STATE>.json` files: run it once to warm the cache (one College
Scorecard API call per state), run it again and it's instant with zero
network calls, and the web app's cache stays in sync either way.

```bash
python -m scripts.step1_find_colleges                          # all states, default fields
python -m scripts.step1_find_colleges --fields id,school.name,school.city
python -m scripts.step1_find_colleges --refresh                # ignore cache, re-fetch everything
python -m scripts.step1_find_colleges --states TX,CA,NY         # restrict to a subset
python -m scripts.step1_find_colleges --out-dir some/other/dir  # default: exports/
```

Requires `SCORECARD_API_KEY` in `.env` — but only if at least one target
state actually needs fetching; a fully-cached run works without it.

Functions:
- `build_dataset(fields, cache_dir=None, api_key=None, refresh=False, states=None, on_progress=None)`
  — the core logic: ensures each target state's cache has `fields`
  (fetching only what's missing, unless `refresh`), decodes each row via
  `field_catalog.decode_row`, tags it with `state_abbr`/`state_name`, and
  returns `(rows, failed)`. A state whose fetch raises is recorded in
  `failed` (with its error) rather than aborting the run; whatever was
  already cached for it is still included in `rows`. Raises
  `MissingApiKeyError` up front — before any state is touched — if a fetch
  is needed and no `api_key` was given.
- `write_csv(rows, fields, path)` / `write_json(rows, path)` — the two
  output writers.
- `main(argv=None)` — CLI entry point (argument parsing, progress printing,
  wiring the above together). Exit code 1 if `SCORECARD_API_KEY` is missing
  and needed.

## `step2_find_staff.py` (step 2)

Runs the athletics-staff lookup pipeline (`backend/staff_finder.py`) over
every school already cached in `cache_data/state_schools/<STATE>.json` (populate that
first with `step1_find_colleges.py`), saving each result to the same
per-school cache the web app reads/writes
(`cache_data/staff/<STATE>/<school>.json`).

```bash
python -m scripts.step2_find_staff                    # every cached state
python -m scripts.step2_find_staff --states TX,CA,NY   # restrict to a subset
python -m scripts.step2_find_staff --refresh           # ignore the staff cache, re-lookup everyone
python -m scripts.step2_find_staff --limit 100         # stop after 100 fresh (non-cached) lookups
python -m scripts.step2_find_staff --include-closed    # also look up schools marked as closed
```

Requires `TAVILY_API_KEY` in `.env`.

Safe to interrupt and re-run: a school with a usable cached result (real
staff found, current cache version) is skipped, so re-running only picks
up what's still missing or previously errored.

Tavily/the LLM provider both have usage limits, and `staff_finder.py` is
built to quietly degrade (Wikipedia/raw-fetch fallback, a log warning)
rather than raise on a single failure — which would otherwise let an
*exhausted* limit silently degrade every remaining school. This script
watches for that instead and stops the run (non-zero exit) the moment a
lookup looks like a usage-limit/quota response, without caching the
school it stopped on, so a later re-run retries it.

Functions:
- `build_school_list(cache_dir=None, states=None, include_closed=False)`
  — reads every target state's cache (`backend/cache.py`) and returns
  `{'name', 'state'}` dicts, sorted by state name then school name,
  skipping blank names and (unless `include_closed`) schools with
  `school.operating == 0`.
- `looks_like_limit_error(text)` — true if `text` contains a known
  Tavily/OpenAI usage-limit/quota signature (`"usage limit"`,
  `"rate limit"`, `"429"`, `"432"`, `"quota"`, `"too many requests"`).
- `LimitWatchingHandler` — a `logging.Handler` attached to
  `backend.staff_finder`'s logger for the duration of a lookup; flags
  `.hit` the moment a warning it logs (e.g. a Tavily 432 falling back to
  Wikipedia) looks like a usage-limit signature, since that failure path
  never raises and would otherwise go unnoticed.
- `run(schools, tavily_key, cache_dir=None, llm_provider_name=None, refresh=False, limit=None, on_progress=None)`
  — the core loop: skips cached schools, otherwise runs the pipeline and
  saves real (non-error-only) results immediately; stops as soon as
  `LimitWatchingHandler` fires or a fully-failed lookup's error notes
  match `looks_like_limit_error`, without caching that school. Returns a
  `RunResult` (`total`, `skipped_cached`, `looked_up`, `found`,
  `errored`, `stopped_for_limit`, `stopped_at_school`, `limit_message`).
- `main(argv=None)` — CLI entry point. Exit code 1 if `TAVILY_API_KEY` is
  missing, or if the run stopped on a usage-limit hit.
