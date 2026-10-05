# tests/

pytest suite. `conftest.py` (one directory up, in `college_finder_app/`)
puts the app root on `sys.path` so tests can `import app`/`from backend
import ...`. All Tavily/OpenAI/Ollama/Wikipedia/College Scorecard/network
calls are mocked with `monkeypatch` — the suite makes no live requests.
Run with `pytest -q` from `college_finder_app/` (117 tests, ~2s).

## `test_smoke.py`
`test_smoke()` — trivial "the test runner works" check.

## Step 1 — college search

### `test_scorecard.py` (`backend/scorecard.py`)
- `test_normalize_state_accepts_full_name` / `_accepts_abbreviation` /
  `_rejects_unknown` — `normalize_state()` input handling.
- `test_list_states_includes_texas_and_dc` / `_sorted_by_name` —
  `list_states()` content and ordering.
- `test_fetch_schools_single_page` / `_paginates` / `_raises_on_http_error`
  — `fetch_schools()` against a mocked `requests.get`.

### `test_cache.py` (`backend/cache.py`)
- `test_load_missing_file_returns_empty_structure` — `load()` on a fresh
  `tmp_path`.
- `test_missing_fields_all_missing_when_nothing_cached` /
  `_only_returns_uncached` — `missing_fields()`.
- `test_merge_rows_adds_schools_and_fields` /
  `_does_not_clobber_previously_cached_fields` — `merge_rows()`.
- `test_save_then_load_round_trip` — `save()` + `load()` on disk.
- `test_rows_for_fields_reduces_to_requested_fields_with_none_for_missing`
  — `rows_for_fields()`.

### `test_field_catalog.py` (`backend/field_catalog.py`)
- `test_real_catalog_loads_and_has_expected_categories` /
  `_value_labels_cover_expected_fields` /
  `_every_decodable_field_exists_in_some_category` — sanity checks against
  the actual generated `field_catalog.json`, not a fixture.
- `test_load_catalog_with_explicit_path` — `load_catalog(path=...)`.
- `test_all_fields_flattens_categories` — `all_fields()`.
- `test_decode_row_decodes_known_code_and_passes_through_unknown` —
  `decode_row()`.

## Step 2 — athletics staff finder

### `test_tavily_client.py` (`backend/tavily_client.py`)
- `test_search_returns_results_list` / `_missing_results_key_returns_empty_list`
  / `_raises_on_http_error` — `search()`.
- `test_extract_returns_raw_content_for_matching_url` /
  `_returns_empty_string_when_url_not_in_results` — `extract()`.

### `test_wikipedia_lookup.py` (`backend/wikipedia_lookup.py`)
- `test_find_staff_link_returns_matching_external_link` /
  `_returns_none_when_no_article_found` /
  `_returns_none_when_no_link_matches` — `find_staff_link()` against a
  mocked Wikipedia API.

### `test_llm_provider.py` (`backend/llm_provider.py`)
- `test_get_provider_defaults_to_openai` / `_rejects_unknown` —
  `get_provider()`.
- `test_pick_url_no_results_skips_llm_call` /
  `_openai_parses_response` / `_ollama_parses_response` /
  `_unparseable_response_returns_none` / `_wrong_shape_response_returns_none`
  / `_missing_url_key_returns_none` — `pick_url()` against both providers
  and every malformed-response shape.
- `test_extract_staff_blank_page_text_skips_llm_call` /
  `_parses_and_drops_unknown_category` /
  `_unparseable_response_returns_empty_list` — `extract_staff()`.

### `test_staff_finder.py` (`backend/staff_finder.py`)
Everything here mocks `tavily_client`, `llm_provider`, and
`wikipedia_lookup` — it tests the pipeline's orchestration logic only.
- `test_find_staff_for_school_merges_general_and_track_field_rows` — the
  two-URL search + merge flow.
- `test_find_staff_for_school_falls_back_to_wikipedia_when_no_confident_url`
  — Wikipedia only gets tried when the LLM's `pick_url` comes back empty.
- `test_find_staff_for_school_dedupes_preferring_row_with_email` /
  `_dedup_keeps_coach_category_from_track_field_page` — `_dedupe()`.
- `test_find_staff_for_school_fills_missing_email_from_bio_page` /
  `_bio_fill_requires_matching_name` — `_fill_missing_email()`.
- `test_find_staff_for_school_returns_error_row_on_exception` — a raised
  exception anywhere in the pipeline becomes a single `category: "error"`
  row instead of propagating.
- `test_find_staff_for_school_wikipedia_fallback_for_track_field_does_not_force_coach_category`
  — a Wikipedia-sourced track-field URL must NOT force every row on that
  page to `"coach"` (only a Tavily/LLM-confirmed URL does).

### `test_staff_cache.py` (`backend/staff_cache.py`)
- `test_load_missing_file_returns_none` — `load()` with nothing cached yet.
- `test_save_then_load_round_trip` — `save()` + `load()` on disk.
- `test_save_slugifies_school_name_for_filename` /
  `_different_schools_do_not_collide` — `_slugify()` behavior via `save()`.

### `test_staff_jobs.py` (`backend/staff_jobs.py`)
- `test_start_job_processes_schools_synchronously_and_reports_done` —
  `start_job(..., run_in_thread=False)`.
- `test_start_job_uses_cache_when_not_refreshing` /
  `_refresh_bypasses_cache` — the cache-vs-refresh branch in `_run_job`.
- `test_get_status_unknown_job_returns_none` — `get_status()` on an
  unknown `job_id`.
- `test_run_job_survives_a_school_that_raises_and_still_finishes` — a
  per-school exception marks that school `category: "error"` but still
  sets `"finished": True` on the job (never hangs).
- `test_start_job_run_in_thread_true_eventually_finishes` — the real
  `threading.Thread` path (not just the synchronous test path).

### `test_export_colleges.py` (`scripts/step1_find_colleges.py`; file name predates the rename)
- `test_build_dataset_fetches_missing_fields_and_caches` — a state with no
  cache gets fetched and the result written to `cache_data/state_schools/`.
- `test_build_dataset_skips_fetch_when_all_fields_cached` — a fully-cached
  state never calls `fetch_schools` (asserted via a fetch stub that raises
  if invoked).
- `test_build_dataset_refresh_forces_fetch_even_when_cached` — `refresh=True`
  re-fetches regardless of what's cached.
- `test_build_dataset_continues_on_state_fetch_failure_and_reports_it` — one
  state's `fetch_schools` raising doesn't stop the others; the failure is
  returned, not raised.
- `test_build_dataset_raises_missing_api_key_before_fetching_any_state` — no
  `api_key` plus at least one state needing a fetch raises
  `MissingApiKeyError` before any cache is touched.
- `test_build_dataset_states_filter_restricts_to_subset` — `states=[...]`
  narrows which states are processed.
- `test_write_csv_writes_header_and_rows` / `test_write_json_round_trips` —
  the two output writers.

### `test_app.py` (`app.py` routes, both steps)
- `test_index_page_loads` / `test_states_endpoint` / `test_fields_endpoint`
  — the simple GET routes.
- `test_colleges_unknown_state` / `_no_fields` / `_fetches_and_caches` /
  `_refresh_forces_refetch` / `_upstream_error` /
  `_upstream_error_redacts_api_key` — `GET /api/colleges`.
- `test_staff_find_requires_schools` — `POST /api/staff/find` with an
  empty schools list.
- `test_staff_find_and_status_synchronous_in_tests` — the full
  find→poll round trip with `staff_finder.find_staff_for_school` mocked
  (relies on `app.testing=True` making `staff_jobs` run synchronously).
- `test_staff_status_unknown_job_returns_404`.
- `test_staff_find_end_to_end_through_staff_finder` — same round trip, but
  only mocks the outermost calls (`tavily_client.search/extract`,
  `llm_provider.pick_url/extract_staff`, `wikipedia_lookup.find_staff_link`),
  exercising the real `staff_jobs` → `staff_finder` chain.

### `test_find_staff.py` (`scripts/step2_find_staff.py`)
Covers `build_school_list()` (sorting, closed-school filtering, blank
names, state filter, missing cache files), `looks_like_limit_error()`,
`LimitWatchingHandler`, and `run()` (skips cached schools, stops on a
usage-limit hit without caching that school, honors `--limit`/`refresh`).
File name predates the rename to `step2_find_staff`.
