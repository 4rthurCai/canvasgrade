"use strict";

// Front end for the local GUI. Talks only to this server, which holds the Canvas token.

const ROLES = [
  ["criterion", "criterion"],
  ["comment", "comment"],
  ["total", "total"],
  ["ratio", "ratio"],
  ["canvas_id", "Canvas id"],
  ["sis_id", "SIS id"],
  ["name", "name"],
  ["team", "team"],
  ["ignore", "ignore"],
];

const state = {
  upload: null,
  columns: [],
  overrides: new Map(),
  plan: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) { /* keep the status line */ }
    throw new Error(detail);
  }
  return response.json();
}

function fatal(message) {
  const box = $("fatal");
  box.textContent = message;
  box.hidden = !message;
}

function busy(element, text) {
  element.innerHTML = text ? `<span class="spinner"></span> ${text}` : "";
}

// ---------------------------------------------------------------- session

async function loadSession() {
  try {
    const info = await api("/api/session");
    $("who").textContent = `${info.user} · ${info.api_url} · profile ${info.profile}`;
    await loadCourses(info.course_id, info.assignment_id);
  } catch (error) {
    $("who").textContent = "not connected";
    fatal(`Could not reach Canvas: ${error.message}`);
  }
}

async function loadCourses(preselectCourse, preselectAssignment) {
  const select = $("course");
  try {
    const courses = await api("/api/courses");
    select.innerHTML = '<option value="">select a course…</option>';
    for (const course of courses) {
      const option = document.createElement("option");
      option.value = course.id;
      option.textContent = course.code ? `${course.name} (${course.code})` : course.name;
      select.append(option);
    }
    if (preselectCourse) {
      select.value = String(preselectCourse);
      await loadAssignments(preselectCourse, preselectAssignment);
    }
  } catch (error) {
    select.innerHTML = '<option value="">failed to load</option>';
    fatal(error.message);
  }
}

async function loadAssignments(courseId, preselect) {
  const select = $("assignment");
  select.disabled = true;
  select.innerHTML = '<option value="">loading…</option>';
  try {
    const assignments = await api(`/api/courses/${courseId}/assignments`);
    select.innerHTML = '<option value="">select an assignment…</option>';
    for (const item of assignments) {
      const option = document.createElement("option");
      option.value = item.id;
      const points = item.points_possible == null ? "?" : item.points_possible;
      option.textContent = `${item.name} — ${points} pts${item.rubric_id ? " · rubric attached" : ""}`;
      option.dataset.points = points;
      option.dataset.rubric = item.rubric_id || "";
      select.append(option);
    }
    select.disabled = false;
    if (preselect) {
      select.value = String(preselect);
      onAssignmentChange();
    }
  } catch (error) {
    select.innerHTML = '<option value="">failed to load</option>';
    fatal(error.message);
  }
}

function onAssignmentChange() {
  const option = $("assignment").selectedOptions[0];
  const info = $("assignment-info");
  if (!option || !option.value) {
    info.textContent = "";
  } else if (option.dataset.rubric) {
    info.textContent = `Rubric ${option.dataset.rubric} is attached to this assignment.`;
    $("rubric-mode").value = "attached";
  } else {
    info.textContent = "No rubric attached yet — pick “Create a new rubric” below.";
    $("rubric-mode").value = "create";
  }
  onRubricModeChange();
  refreshReadiness();
}

// ---------------------------------------------------------------- upload

async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  const sheet = $("sheet").value || "0";
  busy($("preview-status"), "reading the sheet…");
  try {
    const result = await api(`/api/uploads?sheet=${encodeURIComponent(sheet)}`, { method: "POST", body: form });
    state.upload = result;
    state.columns = result.columns;
    state.overrides.clear();
    renderUpload(result);
    fatal("");
  } catch (error) {
    fatal(error.message);
  } finally {
    busy($("preview-status"), "");
  }
}

// The server applies --include patterns for real; this mirrors them so the summary
// updates as you type instead of only after a preview round trip.
function includePatterns() {
  return $("include").value.split(",").map((p) => p.trim()).filter(Boolean);
}

function globToRegExp(pattern) {
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`^${escaped.replace(/\*/g, ".*").replace(/\?/g, ".")}$`, "i");
}

function matchesInclude(name) {
  const patterns = includePatterns();
  if (!patterns.length) return true;
  return patterns.some((pattern) => globToRegExp(pattern).test(name));
}

// What the columns look like once the user's edits are applied - the server does the
// same thing, so the summary stays honest as you type.
function effectiveColumns() {
  return state.columns.map((column) => {
    const override = state.overrides.get(column.name);
    return override ? { ...column, ...override } : column;
  });
}

function effectiveCriteria() {
  return effectiveColumns().filter((c) => c.role === "criterion" && matchesInclude(c.name));
}

function renderDetected() {
  const result = state.upload;
  if (!result) return;
  const criteria = effectiveCriteria();
  const total = criteria.reduce((sum, c) => sum + (c.points || 0), 0);
  const teams = result.teams.length ? `, ${result.teams.length} teams` : "";
  const dropped = state.columns.filter((c) => c.role === "criterion").length - criteria.length;
  const note = dropped ? ` · ${dropped} criteria filtered out` : "";
  $("detected").textContent =
    `${result.students} students${teams} · ${criteria.length} criteria worth ${total} points · ` +
    `${result.n_rows} rows in the file${note}`;
}

function renderUpload(result) {
  $("sheet-meta").hidden = false;
  $("options-section").hidden = false;
  $("drop").innerHTML = `<strong>${result.filename}</strong><br /><span>click to choose a different file</span>`;

  const sheetSelect = $("sheet");
  sheetSelect.innerHTML = "";
  const names = result.sheets.length ? result.sheets : ["(single sheet)"];
  names.forEach((name, index) => {
    const option = document.createElement("option");
    option.value = result.sheets.length ? name : String(index);
    option.textContent = name;
    sheetSelect.append(option);
  });
  sheetSelect.value = String(result.sheet);
  sheetSelect.disabled = result.sheets.length < 2;

  renderDetected();
  renderColumns(result.columns);
  refreshReadiness();
}

function renderColumns(columns) {
  const body = $("columns").querySelector("tbody");
  body.innerHTML = "";
  const criteriaNames = columns.filter((c) => c.role === "criterion").map((c) => c.name);

  for (const column of columns) {
    const tr = document.createElement("tr");

    const name = document.createElement("td");
    name.className = "mono";
    name.textContent = column.name;
    tr.append(name);

    const roleCell = document.createElement("td");
    const select = document.createElement("select");
    for (const [value, label] of ROLES) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.append(option);
    }
    select.value = column.role;
    select.addEventListener("change", () => setOverride(column, select.value, criteriaNames));
    roleCell.append(select);
    tr.append(roleCell);

    // The criterion name is what students see; the header is often not phrased for them.
    const nameCell = document.createElement("td");
    if (column.role === "criterion") {
      const rename = document.createElement("input");
      rename.type = "text";
      rename.value = column.description || "";
      rename.addEventListener("change", () =>
        setOverride(column, select.value, criteriaNames, undefined, rename.value)
      );
      nameCell.append(rename);
    } else {
      nameCell.innerHTML = '<span class="muted">—</span>';
    }
    tr.append(nameCell);

    const points = document.createElement("td");
    points.className = "num";
    if (column.role === "criterion" || column.role === "total") {
      const input = document.createElement("input");
      input.type = "number";
      input.step = "0.5";
      input.value = column.points == null ? "" : column.points;
      input.addEventListener("change", () => setOverride(column, select.value, criteriaNames, input.value));
      points.append(input);
    } else {
      points.textContent = "";
    }
    tr.append(points);

    const why = document.createElement("td");
    why.className = "muted";
    why.textContent = column.target ? `${column.reason}` : column.reason;
    tr.append(why);

    body.append(tr);
  }
}

function setOverride(column, role, criteriaNames, points, description) {
  // Overrides replace the detector's answer wholesale, so carry forward whatever the
  // user is not editing right now - otherwise renaming a criterion clears its max.
  const previous = state.overrides.get(column.name) || {};
  const override = { name: column.name, role };

  if (points !== undefined && points !== "") override.points = Number(points);
  else if (previous.points != null) override.points = previous.points;
  else if (column.points != null && (role === "criterion" || role === "total")) override.points = column.points;

  if (description !== undefined) override.description = description.trim() || null;
  else if (previous.description) override.description = previous.description;

  if (role === "comment") override.target = column.target || criteriaNames[0] || null;

  state.overrides.set(column.name, override);
  renderDetected();
  $("plan-section").hidden = true;
  $("result-section").hidden = true;
}

// ---------------------------------------------------------------- options

function onRubricModeChange() {
  const mode = $("rubric-mode").value;
  $("rubric-id-field").hidden = mode !== "existing";
  $("rubric-title-field").hidden = mode !== "create";
  if (mode === "existing") loadRubrics();
}

// Offering a dropdown rather than a number box is the whole point: nobody should have
// to dig a rubric id out of the browser's dev tools.
async function loadRubrics() {
  const courseId = $("course").value;
  const select = $("rubric-id");
  if (!courseId) {
    select.innerHTML = '<option value="">pick a course first</option>';
    return;
  }
  select.innerHTML = '<option value="">loading…</option>';
  try {
    const rubrics = await api(`/api/courses/${courseId}/rubrics`);
    if (!rubrics.length) {
      select.innerHTML = '<option value="">this course has no rubrics</option>';
      return;
    }
    select.innerHTML = '<option value="">select a rubric…</option>';
    for (const rubric of rubrics) {
      const option = document.createElement("option");
      option.value = rubric.id;
      const points = rubric.points == null ? "?" : rubric.points;
      option.textContent = `${rubric.title} — ${rubric.criteria} criteria, ${points} pts (id ${rubric.id})`;
      select.append(option);
    }
  } catch (error) {
    select.innerHTML = '<option value="">failed to load</option>';
    fatal(error.message);
  }
}

function payload() {
  const rubricMode = $("rubric-mode").value;
  return {
    token: state.upload.token,
    course_id: Number($("course").value),
    assignment_id: Number($("assignment").value),
    sheet: $("sheet").value || 0,
    has_header: true,
    overrides: [...state.overrides.values()],
    include: includePatterns(),
    exclude: [],
    rubric: {
      mode: rubricMode,
      rubric_id: $("rubric-id").value ? Number($("rubric-id").value) : null,
      title: $("rubric-title").value || null,
      use_for_grading: $("use-for-grading").checked,
    },
    options: {
      total: $("total").value,
      strict: $("strict").checked,
      apply_ratio: $("apply-ratio").checked,
      add_comment: $("add-comment").checked,
      missing_as_zero: $("missing-zero").checked,
      clamp: $("clamp").checked,
    },
  };
}

function refreshReadiness() {
  const ready = Boolean(state.upload && $("course").value && $("assignment").value);
  $("preview-btn").disabled = !ready;
}

// ---------------------------------------------------------------- plan

async function preview() {
  busy($("preview-status"), "building the preview…");
  $("push-btn").disabled = true;
  try {
    const plan = await api("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload()),
    });
    state.plan = plan;
    renderPlan(plan);
    fatal("");
  } catch (error) {
    fatal(error.message);
    $("plan-section").hidden = true;
  } finally {
    busy($("preview-status"), "");
  }
}

function renderPlan(plan) {
  $("plan-section").hidden = false;
  $("result-section").hidden = true;

  const notes = $("plan-notes");
  notes.innerHTML = "";
  for (const note of plan.notes) {
    const div = document.createElement("div");
    div.className = "banner info";
    div.textContent = note;
    notes.append(div);
  }

  const errors = plan.issues.filter((i) => i.level === "error").length;
  const warnings = plan.issues.length - errors;
  const totals = plan.entries.map((e) => e.posted_grade);
  const mean = totals.length ? (totals.reduce((a, b) => a + b, 0) / totals.length).toFixed(1) : "-";
  $("plan-summary").innerHTML = [
    stat(plan.entries.length, "students ready", plan.entries.length ? "ok" : "err"),
    stat(plan.skipped.length, "skipped", plan.skipped.length ? "warn" : ""),
    stat(errors, "errors", errors ? "err" : ""),
    stat(warnings, "warnings", warnings ? "warn" : ""),
    stat(mean, "mean total", ""),
    plan.rubric_total != null ? stat(plan.rubric_total, "rubric points", "") : "",
  ].join("");

  renderRubricPreview(plan);

  const head = $("entries").querySelector("thead");
  const body = $("entries").querySelector("tbody");
  const criteria = plan.criteria || [];
  head.innerHTML =
    `<tr><th>Student</th><th class="num">Canvas id</th><th class="num">Total</th>` +
    criteria.map((c) => `<th class="num" title="${escapeHtml(c.description)}">${escapeHtml(short(c.description))}</th>`).join("") +
    `</tr>`;
  body.innerHTML = plan.entries
    .map(
      (entry) =>
        `<tr><td>${escapeHtml(entry.label)}</td><td class="num muted">${entry.user_id}</td>` +
        `<td class="num"><b>${entry.posted_grade}</b></td>` +
        entry.scores.map((score) => `<td class="num">${score}</td>`).join("") +
        `</tr>`
    )
    .join("");

  const issues = $("plan-issues");
  issues.innerHTML = "";
  for (const issue of plan.issues) {
    issues.insertAdjacentHTML(
      "beforeend",
      `<div class="issue"><span class="lvl ${issue.level}">${issue.level}</span>${escapeHtml(issue.message)}</div>`
    );
  }
  if (plan.skipped.length) {
    const rows = plan.skipped
      .map((s) => `<div class="issue muted">row ${s.row_index} · ${escapeHtml(s.label)}: ${escapeHtml(s.reason)}</div>`)
      .join("");
    issues.insertAdjacentHTML(
      "beforeend",
      `<details style="margin-top:8px"><summary>${plan.skipped.length} skipped rows</summary>${rows}</details>`
    );
  }

  $("push-btn").disabled = !plan.pushable;
  $("push-status").textContent = plan.pushable ? "" : "Fix the errors above before pushing.";
}

// The rubric is the thing being created on Canvas, so show it as a rubric rather than
// leaving it implied by the column headers of the grades table.
function renderRubricPreview(plan) {
  const wrap = $("rubric-preview-wrap");
  const criteria = plan.criteria || [];
  if (!criteria.length) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;

  const columns = effectiveCriteria();
  const summary = wrap.querySelector("summary");
  const total = plan.rubric_total == null ? "" : ` · ${plan.rubric_total} points`;
  const title = plan.rubric_title ? `“${escapeHtml(plan.rubric_title)}”` : "The rubric";
  const pending = criteria.some((c) => (c.criterion_id || "").startsWith("_preview_"));
  summary.innerHTML =
    `${title} — ${criteria.length} criteria${total}` +
    (pending ? ' <span class="pill">will be created</span>' : ' <span class="pill">already on Canvas</span>');

  const body = $("rubric-preview").querySelector("tbody");
  body.innerHTML =
    criteria
      .map((criterion, index) => {
        const id = criterion.criterion_id || "";
        const shown = id.startsWith("_preview_") ? '<span class="muted">new</span>' : `<code>${escapeHtml(id)}</code>`;
        const from = columns[index] ? escapeHtml(short(columns[index].name)) : "";
        return (
          `<tr><td class="num muted">${index + 1}</td><td>${escapeHtml(criterion.description)}</td>` +
          `<td class="num">${criterion.points}</td><td>${shown}</td>` +
          `<td class="muted" title="${from}">${from}</td></tr>`
        );
      })
      .join("") +
    `<tr><td></td><td><b>total</b></td><td class="num"><b>${plan.rubric_total ?? ""}</b></td><td></td><td></td></tr>`;
}

function stat(value, label, tone) {
  return `<div class="stat ${tone}"><b>${value}</b><span>${label}</span></div>`;
}

function short(text) {
  return text.length > 14 ? `${text.slice(0, 13)}…` : text;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );
}

// ---------------------------------------------------------------- push

async function push() {
  const count = state.plan.entries.length;
  if (!confirm(`Push ${count} grades to Canvas? This writes to student records.`)) return;

  $("push-btn").disabled = true;
  busy($("push-status"), "uploading…");
  try {
    const result = await api("/api/push", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload(), batch_size: 200 }),
    });
    renderResult(result);
    fatal("");
  } catch (error) {
    fatal(error.message);
    $("push-btn").disabled = false;
  } finally {
    busy($("push-status"), "");
  }
}

function renderResult(result) {
  $("result-section").hidden = false;
  const parts = [];
  if (result.ok) {
    parts.push(`<div class="banner ok">Pushed ${result.submitted} grades in ${result.batches} batch(es).</div>`);
  } else {
    parts.push(`<div class="banner err">${result.failures.map(escapeHtml).join("<br />")}</div>`);
  }
  if (result.rubric_id) parts.push(`<div class="muted">Rubric id ${result.rubric_id}</div>`);
  if (result.speedgrader_url) {
    parts.push(`<p><a href="${escapeHtml(result.speedgrader_url)}" target="_blank" rel="noreferrer">Open SpeedGrader</a></p>`);
  }
  $("result").innerHTML = parts.join("");
  $("result-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------------------------------------------------------------- wiring

function wire() {
  const drop = $("drop");
  const input = $("file");

  drop.addEventListener("click", () => input.click());
  input.addEventListener("change", () => input.files[0] && uploadFile(input.files[0]));
  drop.addEventListener("dragover", (event) => {
    event.preventDefault();
    drop.classList.add("over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("over");
    const file = event.dataTransfer.files[0];
    if (file) uploadFile(file);
  });

  $("course").addEventListener("change", (event) => {
    if (event.target.value) loadAssignments(event.target.value);
    refreshReadiness();
  });
  $("assignment").addEventListener("change", onAssignmentChange);
  $("rubric-mode").addEventListener("change", onRubricModeChange);
  $("sheet").addEventListener("change", () => input.files[0] && uploadFile(input.files[0]));
  $("include").addEventListener("input", () => {
    renderDetected();
    $("plan-section").hidden = true;
  });
  $("strict").addEventListener("change", () => {
    $("plan-section").hidden = true;
  });
  $("preview-btn").addEventListener("click", preview);
  $("push-btn").addEventListener("click", push);

  loadSession();
}

wire();
