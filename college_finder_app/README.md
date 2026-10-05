# College & University Finder

See the [root README](../README.md) for the whole project (setup, `.env`, how to run both steps, where results live).

Local web app for step 1 of a college athletics staff outreach pipeline: pick a US
state, choose which institution fields to see, get a table of every
college/university in that state, and export it to CSV.

## Setup

1. From the repo root, create a virtual environment and install
   dependencies:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r college_finder_app/requirements.txt
   ```

2. Make sure `.env` (repo root) has `SCORECARD_API_KEY` set. Get a free
   key at https://api.data.gov/signup/ if you don't have one.

3. (One-time, already done for this repo) `backend/field_catalog.json` is
   generated from `API_Documentations/CollegeScorecardDataDictionary.xlsx`:

   ```bash
   python API_Documentations/build_field_catalog.py
   ```

   Re-run this only if the Data Dictionary xlsx is updated.

## Run

```bash
python college_finder_app/app.py
```

Open http://127.0.0.1:5000/ in a browser.

## Tests

```bash
pytest college_finder_app/tests
```

## How it works

- `backend/scorecard.py` talks to the College Scorecard API.
- `backend/field_catalog.py` loads the curated field list (see
  `backend/field_catalog.json`) used to populate the field picker and
  decode a handful of coded values (flags, degree level) to readable text.
- `backend/cache.py` caches fetched fields per state in `cache_data/state_schools/`
  (gitignored), so repeat searches — or newly-added fields for a state
  already searched — don't always hit the live API. Use the Refresh
  button to force a clean re-fetch.
- `app.py` wires it together into a small Flask app: `/api/states`,
  `/api/fields`, `/api/colleges`, and the page itself.
- CSV export happens entirely client-side in `static/app.js`, from
  whatever's currently in the table.

## Export every state at once (no web UI)

```bash
python -m scripts.step1_find_colleges
```

Fetches every college/university for all 50 states + DC (using the same
cache as the web app) and writes `exports/all_colleges.csv` and
`.json`. See [scripts/README.md](scripts/README.md) for options
(`--fields`, `--refresh`, `--states`, `--out-dir`).

## Athletics staff finder

Select one or more schools in the results table (checkboxes) and click
"Find Staff for Selected" to look up athletics department staff: track &
field/cross country coaches, athletic administration, sports medicine,
and sports info/media, with email where available. Results are cached
per school in `cache_data/staff/<state>/<school-slug>.json`; check
"Refresh (bypass cache)" to force a fresh lookup.

This uses `TAVILY_API_KEY` and (depending on `LLM_PROVIDER`) either
`OPENAI_API_KEY` or a local Ollama server — same `.env` keys already
required for the college search step, plus two optional additions to
`.env`:

- `LLM_PROVIDER` — `openai` (default) or `ollama`.
- `OLLAMA_HOST` — only used when `LLM_PROVIDER=ollama`; defaults to
  `http://localhost:11434`. Requires a local Ollama server running with
  the model pulled: `ollama pull mistral-small3.1:24` (or set
  `OLLAMA_MODEL` to whatever model you have pulled instead).

Supersedes an earlier prototype that only found a directory URL per school.

## Folder guide

Each folder below has its own README listing every file and what its
functions do:

- [backend/README.md](backend/README.md) — all backend modules (both steps)
- [scripts/README.md](scripts/README.md) — `step1_find_colleges.py` and `step2_find_staff.py`
- [static/README.md](static/README.md) — `app.js` / `style.css`
- [templates/README.md](templates/README.md) — `index.html`
- [tests/README.md](tests/README.md) — the pytest suite, file by file
