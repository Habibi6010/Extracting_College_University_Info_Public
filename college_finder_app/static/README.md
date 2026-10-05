# static/

Vanilla JS/CSS served as-is by Flask (`app.route("/")` renders
`templates/index.html`, which links these two files) — no framework, no
build step.

## `app.js`

Single global `state` object plus DOM-manipulation functions, wired up in
`init()` at the bottom of the file. Split by the two features it drives:
the step-1 college search/results table, and the step-2 athletics staff
finder built on top of the selected rows.

**Shared / setup**
- `state` — `fields` (catalog from `/api/fields`), `selectedFields`,
  `currentSchools`, `currentColumns`, `selectedSchoolIndexes`,
  `staffPollTimer`, `currentStaff`, `activeStaffFilters`.
- `DEFAULT_FIELDS` — the field set checked by default on first load.
- `init()` — attaches every button/input listener, then kicks off
  `loadStates()` + `loadFields()`.
- `showError(message)` — shows/hides the `#error-banner`; pass `null` to hide.
- `csvEscape(value)` — quotes/escapes one CSV field value.

**College search (step 1)**
- `loadStates()` — populates `#state-select` from `/api/states`.
- `loadFields()` — loads `/api/fields` into `state.fields`, seeds
  `state.selectedFields` from `DEFAULT_FIELDS`, renders the field picker.
- `renderFieldPicker()` — builds the `#field-categories` checkbox groups.
- `applyFieldFilter()` — hides field-picker rows that don't match the
  `#field-filter` text box.
- `findFieldMeta(apiField)` — looks up a field's `{api_field, label, is_url}`
  entry from `state.fields`.
- `columnsInCatalogOrder()` — `state.selectedFields`, ordered to match the
  catalog's category/field order.
- `search(refresh)` — reads the state dropdown + selected columns, always
  adds `school.name`/`school.state` to the fetch (needed for staff lookup
  even if those columns aren't displayed), calls `/api/colleges`, and
  renders the results. Calls `resetStaffResults()` unconditionally first,
  so a new search always clears any stale staff table/poll.
- `renderResults(schools, columns)` — (re)builds the results table,
  including a leading checkbox column that populates
  `state.selectedSchoolIndexes`; renders `*_url` fields as links.
- `updateStaffToolbarVisibility()` — shows `#staff-toolbar` only once
  ≥1 school checkbox is checked.
- `exportCsv()` — downloads `state.currentSchools`/`state.currentColumns`
  as a CSV file.

**Athletics staff finder (step 2)**
- `resetStaffResults()` — clears staff state, stops any active poll timer,
  hides `#staff-section`, and re-enables `#find-staff-btn`. Called both by
  `search()` and at the top of `findStaffForSelected()`.
- `findStaffForSelected()` — builds `{name, state}` for each checked
  school, POSTs to `/api/staff/find` (honoring the `#staff-refresh-toggle`
  checkbox), then starts `pollStaffStatus(job_id)`.
- `pollStaffStatus(jobId)` — polls `GET /api/staff/status/<jobId>` every
  1.5s, updating `state.currentStaff` and the progress text; stops the
  interval once `finished` comes back true (or on error).
- `toggleStaffFilter(category)` — toggles one category in/out of
  `state.activeStaffFilters` and toggles the matching chip's `.active`
  class, then re-renders the table.
- `visibleStaffRows()` — `state.currentStaff` filtered by
  `state.activeStaffFilters` (no filters selected = show everything).
- `renderStaffTable()` — (re)builds `#staff-body` from
  `visibleStaffRows()`; renders `email` as a `mailto:` link.
- `exportStaffCsv()` — downloads the currently *visible* (filtered) staff
  rows as `athletics_staff.csv`.

## `style.css`

Plain CSS, no preprocessor. `:root` sets `color-scheme: light dark` and a
shared `--border` variable. Sections, top to bottom: base body/heading
styles, `.controls` toolbar, `#field-picker`/`#field-categories`/
`.field-option` (step 1's field picker), `#field-filter`, `.error`
banner, shared `table`/`th`/`td` styles (used by both the results table
and the staff table), then `#staff-toolbar`, `#staff-section`,
`#staff-filters`, and `.staff-filter-chip`/`.staff-filter-chip.active`
(step 2's toolbar, filter chips, and staff table container).
