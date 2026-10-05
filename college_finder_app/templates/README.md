# templates/

Flask/Jinja2 templates, rendered by `app.py`'s `index()` route.

## `index.html`

The single page the app serves. No client-side routing — everything is
one static shell that `static/app.js` fills in via `fetch()` calls.
Structure, top to bottom:

- **`.controls`** — state `<select id="state-select">`, `#search-btn`,
  `#refresh-btn` (bypasses the step-1 school cache), `#export-btn`
  (disabled until there are results).
- **`#field-picker`** (`<details>`, open by default) — `#field-filter`
  text input, `#field-categories` (filled in by `renderFieldPicker()`
  in `app.js`).
- **`#error-banner`** — hidden `<div class="error">`, shown by `showError()`.
- **`#loading`** — hidden "Loading..." indicator during a search.
- **`#results-table`** — step-1 results; `#results-head`/`#results-body`
  are populated entirely by `renderResults()` in `app.js` (this file only
  declares the empty `<thead>`/`<tbody>` shells).
- **`#staff-toolbar`** (hidden until ≥1 school is checked) —
  `#find-staff-btn`, `#staff-refresh-toggle` checkbox (bypass the staff
  cache), `#staff-progress` status text.
- **`#staff-section`** (hidden until a lookup starts) — `#staff-filters`
  (one `.staff-filter-chip` button per category: `data-category` values
  `coach` / `admin` / `sports_medicine` / `sports_info` / `error`, plus
  `#staff-export-btn`), and `#staff-table` with a fixed 8-column header
  (School, Name, Title, Category, Sport, Email, Phone, Notes) — the body
  `#staff-body` is populated by `renderStaffTable()` in `app.js`.

Element `id`s and `data-category` values here are read directly by
`static/app.js` — if you rename or remove one, update the matching
`document.getElementById`/`dataset.category` reference there too.
