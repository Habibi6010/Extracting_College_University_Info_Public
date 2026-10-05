# College Athletics Staff Finder

A two-step pipeline that builds a contact list of **US college athletics
staff** — track & field / cross country coaches, athletic administration,
sports medicine, and sports information — with emails where available.

| Step | What it does | Data source | Output |
|------|--------------|-------------|--------|
| **1 – Find colleges** | Every college/university in all 50 states + DC (name, city, website, ownership, operating status, …) | [College Scorecard API](https://collegescorecard.ed.gov/data/) | `college_finder_app/exports/all_colleges.csv/.json` |
| **2 – Find staff** | For each school, locates the athletics staff directory and extracts staff + emails | [Tavily](https://tavily.com) search/extract + an LLM (OpenAI or local Ollama), Wikipedia as fallback | `college_finder_app/cache_data/staff/<ST>/<school>.json` |

Use it from a **web UI** (Flask) or from **bulk command-line scripts**.

## Repo layout

```
.env.example              copy to .env and add your API keys
API_Documentations/       College Scorecard data dictionary (xlsx), PDFs, and
                          build_field_catalog.py (generates backend/field_catalog.json)
docs/notes/               Ollama remote-GPU tips, data-source links
college_finder_app/
  app.py                  Flask app (web UI + JSON API)
  backend/                Scorecard client, caches, Tavily client, LLM provider, staff pipeline
  scripts/                CLI: step1_find_colleges.py, step2_find_staff.py
  static/ templates/      Web UI (vanilla JS/CSS, one HTML page)
  cache_data/             Generated caches (git-ignored)
  exports/                Generated CSV/JSON (git-ignored)
  tests/                  pytest suite (no network calls)
```

Every folder under `college_finder_app/` has its own README documenting
each file and function.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r college_finder_app/requirements.txt
cp .env.example .env        # then fill in keys (Windows: copy .env.example .env)
```

| `.env` key | Needed for | Notes |
|-----------|-----------|-------|
| `SCORECARD_API_KEY` | Step 1 (only if something must be fetched) | Free: https://api.data.gov/signup/ |
| `TAVILY_API_KEY` | Step 2 | Free tier has a usage cap |
| `LLM_PROVIDER` | Step 2 | `openai` (default) or `ollama` |
| `OPENAI_API_KEY` | Step 2 with `openai` | Uses `gpt-4.1-mini` |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | Step 2 with `ollama` | Defaults `http://localhost:11434` / `mistral-small3.1:24b` |
| `OLLAMA_NUM_CTX`, `MAX_PAGE_TEXT_CHARS` | Optional tuning | Defaults 24576 / 32000 |
| `WIKIPEDIA_USER_AGENT` | Optional | Set a contact URL/email per Wikipedia's policy |

## Usage

Run from `college_finder_app/`:

```bash
cd college_finder_app

# Step 1 – colleges
python -m scripts.step1_find_colleges                  # all states -> exports/
python -m scripts.step1_find_colleges --states TX,CA   # subset
python -m scripts.step1_find_colleges --refresh        # ignore cache
python -m scripts.step1_find_colleges --fields id,school.name,school.city

# Step 2 – staff (needs step 1 run first)
python -m scripts.step2_find_staff                     # every cached school
python -m scripts.step2_find_staff --states TX --limit 50
python -m scripts.step2_find_staff --refresh --include-closed

# Web UI -> http://127.0.0.1:5000/
python app.py

# Tests
pytest -q
```

Step 2 is **resumable**: schools with a good cached result are skipped, so
you can Ctrl-C and re-run. If Tavily or the LLM hits a usage limit, the
script stops with exit code 1 *without* caching that school; re-run after the
limit resets (or swap the key) and it continues where it left off.

## Output format

Each `cache_data/staff/<STATE>/<slug>.json` contains `school_name`, `state`,
`fetched_at`, `cache_version`, and `staff[]` rows:
`name, title, category, sport, email, phone, bio_url, source_url`.
Categories: `coach`, `admin`, `sports_medicine`, `sports_info`.

## How step 2 works (per school)

Tavily search → LLM picks the general-athletics and track & field URLs
(Wikipedia as fallback) → Tavily extract page text → LLM extracts staff rows →
de-dupe → fill missing emails from bio pages.

## Responsible use

Staff data is publicly listed contact information about real people, but you
are responsible for complying with the terms of the APIs used, each site's
terms/robots rules, and applicable laws (e.g. CAN-SPAM) when contacting
anyone. Generated data is git-ignored on purpose — don't commit or publish it.
Never commit `.env`.

## Notes

- `backend/field_catalog.json` is generated; regenerate with
  `python API_Documentations/build_field_catalog.py` (from the repo root).
- `staff_cache.CACHE_VERSION` — bumping it invalidates all cached staff files.
- Test file names `test_export_colleges.py` / `test_find_staff.py` cover
  `step1_find_colleges.py` / `step2_find_staff.py` (named before a rename).
