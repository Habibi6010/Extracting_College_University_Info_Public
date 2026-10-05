const state = {
  fields: null,        // catalog from /api/fields
  selectedFields: new Set(),
  currentSchools: [],
  currentColumns: [],
  selectedSchoolIndexes: new Set(),
  staffPollTimer: null,
  currentStaff: [],
  activeStaffFilters: new Set(),
};

const DEFAULT_FIELDS = new Set([
  "school.name", "school.city", "school.state", "school.school_url",
  "school.ownership", "school.degrees_awarded.highest", "school.locale",
  "latest.student.size", "latest.admissions.admission_rate.overall",
]);

async function loadStates() {
  const resp = await fetch("/api/states");
  const states = await resp.json();
  const select = document.getElementById("state-select");
  select.innerHTML = "";
  for (const s of states) {
    const opt = document.createElement("option");
    opt.value = s.abbr;
    opt.textContent = `${s.name} (${s.abbr})`;
    select.appendChild(opt);
  }
}

async function loadFields() {
  const resp = await fetch("/api/fields");
  state.fields = await resp.json();
  state.selectedFields = new Set(
    state.fields.categories
      .flatMap((c) => c.fields)
      .map((f) => f.api_field)
      .filter((f) => DEFAULT_FIELDS.has(f))
  );
  renderFieldPicker();
}

function renderFieldPicker() {
  const container = document.getElementById("field-categories");
  container.innerHTML = "";
  for (const cat of state.fields.categories) {
    const section = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = cat.label;
    section.appendChild(legend);
    for (const f of cat.fields) {
      const wrapper = document.createElement("label");
      wrapper.className = "field-option";
      wrapper.dataset.label = f.label.toLowerCase();
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.selectedFields.has(f.api_field);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.selectedFields.add(f.api_field);
        else state.selectedFields.delete(f.api_field);
      });
      wrapper.appendChild(checkbox);
      wrapper.append(` ${f.label}`);
      section.appendChild(wrapper);
    }
    container.appendChild(section);
  }
}

function applyFieldFilter() {
  const q = document.getElementById("field-filter").value.trim().toLowerCase();
  document.querySelectorAll(".field-option").forEach((el) => {
    el.hidden = q.length > 0 && !el.dataset.label.includes(q);
  });
}

function showError(message) {
  const banner = document.getElementById("error-banner");
  if (message) {
    banner.textContent = message;
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

function findFieldMeta(apiField) {
  for (const cat of state.fields.categories) {
    const match = cat.fields.find((f) => f.api_field === apiField);
    if (match) return match;
  }
  return null;
}

function updateStaffToolbarVisibility() {
  document.getElementById("staff-toolbar").hidden = state.selectedSchoolIndexes.size === 0;
}

function updateSelectAllCheckbox() {
  const selectAll = document.getElementById("select-all-schools");
  if (!selectAll) return;
  const selectedCount = state.selectedSchoolIndexes.size;
  selectAll.checked = state.currentSchools.length > 0 && selectedCount === state.currentSchools.length;
  selectAll.indeterminate = selectedCount > 0 && selectedCount < state.currentSchools.length;
}

function renderResults(schools, columns) {
  state.currentSchools = schools;
  state.currentColumns = columns;
  state.selectedSchoolIndexes = new Set();
  updateStaffToolbarVisibility();

  const head = document.getElementById("results-head");
  head.innerHTML = "";

  const selectTh = document.createElement("th");
  selectTh.className = "select-column";
  const selectAll = document.createElement("input");
  selectAll.id = "select-all-schools";
  selectAll.type = "checkbox";
  selectAll.title = "Select all rows";
  selectAll.disabled = schools.length === 0;
  selectAll.addEventListener("change", () => {
    state.selectedSchoolIndexes = selectAll.checked
      ? new Set(schools.map((_, index) => index))
      : new Set();
    document.querySelectorAll(".school-select").forEach((checkbox) => {
      checkbox.checked = selectAll.checked;
    });
    updateSelectAllCheckbox();
    updateStaffToolbarVisibility();
  });
  selectTh.appendChild(selectAll);
  head.appendChild(selectTh);

  const rowNumberTh = document.createElement("th");
  rowNumberTh.className = "row-number-column";
  rowNumberTh.textContent = "#";
  head.appendChild(rowNumberTh);

  for (const col of columns) {
    const th = document.createElement("th");
    const meta = findFieldMeta(col);
    th.textContent = meta ? meta.label : col;
    head.appendChild(th);
  }

  const body = document.getElementById("results-body");
  body.innerHTML = "";
  schools.forEach((school, index) => {
    const tr = document.createElement("tr");

    const checkboxTd = document.createElement("td");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "school-select";
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedSchoolIndexes.add(index);
      else state.selectedSchoolIndexes.delete(index);
      updateSelectAllCheckbox();
      updateStaffToolbarVisibility();
    });
    checkboxTd.appendChild(checkbox);
    tr.appendChild(checkboxTd);

    const rowNumberTd = document.createElement("td");
    rowNumberTd.className = "row-number-column";
    rowNumberTd.textContent = String(index + 1);
    tr.appendChild(rowNumberTd);

    for (const col of columns) {
      const td = document.createElement("td");
      const value = school[col];
      const meta = findFieldMeta(col);
      if (meta && meta.is_url && value) {
        const a = document.createElement("a");
        a.href = value;
        a.textContent = value;
        a.target = "_blank";
        a.rel = "noopener";
        td.appendChild(a);
      } else {
        td.textContent = value === null || value === undefined ? "" : value;
      }
      tr.appendChild(td);
    }
    body.appendChild(tr);
  });

  updateSelectAllCheckbox();
  document.getElementById("export-btn").disabled = schools.length === 0;
}

function columnsInCatalogOrder() {
  return state.fields.categories
    .flatMap((c) => c.fields)
    .map((f) => f.api_field)
    .filter((f) => state.selectedFields.has(f));
}

async function search(refresh) {
  const stateAbbr = document.getElementById("state-select").value;
  const columns = columnsInCatalogOrder();
  if (!stateAbbr || columns.length === 0) {
    showError("Pick a state and at least one field.");
    return;
  }
  showError(null);
  resetStaffResults();
  document.getElementById("loading").hidden = false;
  document.getElementById("search-btn").disabled = true;
  try {
    // Always fetch name/state under the hood so staff lookup works even
    // when the user hasn't checked those columns for display.
    const fetchFields = Array.from(new Set([...columns, "school.name", "school.state"]));
    const params = new URLSearchParams({ state: stateAbbr, fields: fetchFields.join(",") });
    if (refresh) params.set("refresh", "1");
    const resp = await fetch(`/api/colleges?${params}`);
    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || "Search failed.");
      renderResults([], []);
      return;
    }
    renderResults(data.schools, columns);
  } catch (err) {
    showError(`Search failed: ${err.message}`);
  } finally {
    document.getElementById("loading").hidden = true;
    document.getElementById("search-btn").disabled = false;
  }
}

function csvEscape(value) {
  const str = value === null || value === undefined ? "" : String(value);
  if (/[",\n]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function exportCsv() {
  const columns = state.currentColumns;
  const header = ["#", ...columns.map((c) => (findFieldMeta(c) || {}).label || c)]
    .map(csvEscape)
    .join(",");
  const rows = state.currentSchools.map((school, index) =>
    [index + 1, ...columns.map((c) => school[c])].map(csvEscape).join(",")
  );
  const csv = [header, ...rows].join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const stateAbbr = document.getElementById("state-select").value;
  a.href = url;
  a.download = `${stateAbbr}_colleges.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function resetStaffResults() {
  if (state.staffPollTimer) {
    clearInterval(state.staffPollTimer);
    state.staffPollTimer = null;
  }
  state.currentStaff = [];
  document.getElementById("staff-section").hidden = true;
  document.getElementById("staff-progress").textContent = "";
  document.getElementById("find-staff-btn").disabled = false;
  renderStaffTable();
}

async function findStaffForSelected() {
  const stateAbbr = document.getElementById("state-select").value;
  const schools = Array.from(state.selectedSchoolIndexes).sort((a, b) => a - b).map((i) => ({
    name: state.currentSchools[i]["school.name"],
    state: stateAbbr,
  }));
  if (schools.length === 0) return;

  showError(null);
  state.currentStaff = [];
  document.getElementById("staff-section").hidden = false;
  document.getElementById("find-staff-btn").disabled = true;
  document.getElementById("staff-progress").textContent = `0 of ${schools.length} schools done...`;
  renderStaffTable();

  try {
    const refresh = document.getElementById("staff-refresh-toggle").checked;
    const resp = await fetch("/api/staff/find", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ schools, refresh }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || "Staff lookup failed to start.");
      document.getElementById("find-staff-btn").disabled = false;
      return;
    }
    pollStaffStatus(data.job_id);
  } catch (err) {
    showError(`Staff lookup failed: ${err.message}`);
    document.getElementById("find-staff-btn").disabled = false;
  }
}

function pollStaffStatus(jobId) {
  state.staffPollTimer = setInterval(async () => {
    try {
      const resp = await fetch(`/api/staff/status/${jobId}`);
      const data = await resp.json();
      if (!resp.ok) {
        clearInterval(state.staffPollTimer);
        state.staffPollTimer = null;
        showError(data.error || "Lost track of staff lookup job.");
        document.getElementById("find-staff-btn").disabled = false;
        return;
      }
      state.currentStaff = data.results;
      renderStaffTable();
      document.getElementById("staff-progress").textContent =
        `${data.done} of ${data.total} schools done...`;
      if (data.finished) {
        clearInterval(state.staffPollTimer);
        state.staffPollTimer = null;
        document.getElementById("find-staff-btn").disabled = false;
      }
    } catch (err) {
      clearInterval(state.staffPollTimer);
      state.staffPollTimer = null;
      showError(`Staff lookup failed: ${err.message}`);
      document.getElementById("find-staff-btn").disabled = false;
    }
  }, 1500);
}

function toggleStaffFilter(category) {
  if (state.activeStaffFilters.has(category)) state.activeStaffFilters.delete(category);
  else state.activeStaffFilters.add(category);
  document.querySelectorAll(".staff-filter-chip").forEach((btn) => {
    btn.classList.toggle("active", state.activeStaffFilters.has(btn.dataset.category));
  });
  renderStaffTable();
}

function visibleStaffRows() {
  return state.currentStaff.filter(
    (r) => state.activeStaffFilters.size === 0 || state.activeStaffFilters.has(r.category)
  );
}

function referenceLinks(row) {
  return [
    ["Source", row.source_url],
    ["Bio", row.bio_url],
  ].filter(([, url]) => url);
}

function referenceText(row) {
  return referenceLinks(row).map(([label, url]) => `${label}: ${url}`).join(" | ");
}

function renderStaffTable() {
  const rows = visibleStaffRows();
  const body = document.getElementById("staff-body");
  body.innerHTML = "";
  for (const r of rows) {
    const tr = document.createElement("tr");
    for (const field of ["school_name", "name", "title", "category", "sport"]) {
      const td = document.createElement("td");
      td.textContent = r[field] || "";
      tr.appendChild(td);
    }
    const emailTd = document.createElement("td");
    if (r.email) {
      const a = document.createElement("a");
      a.href = `mailto:${r.email}`;
      a.textContent = r.email;
      emailTd.appendChild(a);
    }
    tr.appendChild(emailTd);
    const phoneTd = document.createElement("td");
    phoneTd.textContent = r.phone || "";
    tr.appendChild(phoneTd);
    const referencesTd = document.createElement("td");
    referencesTd.className = "reference-links";
    for (const [label, url] of referenceLinks(r)) {
      const a = document.createElement("a");
      a.href = url;
      a.textContent = label;
      a.target = "_blank";
      a.rel = "noopener";
      referencesTd.appendChild(a);
    }
    tr.appendChild(referencesTd);
    const notesTd = document.createElement("td");
    notesTd.textContent = r.notes || "";
    tr.appendChild(notesTd);
    body.appendChild(tr);
  }
  document.getElementById("staff-export-btn").disabled = state.currentStaff.length === 0;
}

function exportStaffCsv() {
  const columns = ["school_name", "name", "title", "category", "sport", "email", "phone", "reference_links", "notes"];
  const header = columns.join(",");
  const rows = visibleStaffRows().map((r) =>
    columns.map((c) => csvEscape(c === "reference_links" ? referenceText(r) : r[c])).join(",")
  );
  const csv = [header, ...rows].join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "athletics_staff.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function init() {
  document.getElementById("search-btn").addEventListener("click", () => search(false));
  document.getElementById("refresh-btn").addEventListener("click", () => search(true));
  document.getElementById("export-btn").addEventListener("click", exportCsv);
  document.getElementById("field-filter").addEventListener("input", applyFieldFilter);
  document.getElementById("find-staff-btn").addEventListener("click", findStaffForSelected);
  document.getElementById("staff-export-btn").addEventListener("click", exportStaffCsv);
  document.querySelectorAll(".staff-filter-chip").forEach((btn) => {
    btn.addEventListener("click", () => toggleStaffFilter(btn.dataset.category));
  });
  Promise.all([loadStates(), loadFields()]);
}

document.addEventListener("DOMContentLoaded", init);
