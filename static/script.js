/* ==========================================================================
   Screen — dashboard frontend logic (vanilla JS, no build step)
   ========================================================================== */

// Any 401 means the session ended: go to the sign-in page.
const _fetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const res = await _fetch(...args);
  if (res.status === 401) { location.href = "/login"; }
  return res;
};

const API = {
  async listJobs() {
    return (await fetch("/api/jobs")).json();
  },
  async createJob(title, description) {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, description }),
    });
    return { ok: res.ok, data: await res.json() };
  },
  async deleteJob(id) {
    return fetch(`/api/jobs/${id}`, { method: "DELETE" });
  },
  async getJob(id) {
    return (await fetch(`/api/jobs/${id}`)).json();
  },
  async listCandidates(jobId) {
    return (await fetch(`/api/jobs/${jobId}/candidates`)).json();
  },
  async uploadResumes(jobId, files) {
    const form = new FormData();
    for (const f of files) form.append("resumes", f);
    const res = await fetch(`/api/jobs/${jobId}/candidates`, { method: "POST", body: form });
    return { ok: res.ok, data: await res.json() };
  },
  async getCandidate(id) {
    return (await fetch(`/api/candidates/${id}`)).json();
  },
  async analyze(files) {
    const form = new FormData();
    for (const f of files) form.append("resumes", f);
    const res = await fetch("/api/analyze", { method: "POST", body: form });
    return { ok: res.ok, data: await res.json() };
  },
  async analyzeDemo() {
    const res = await fetch("/api/demo/analyze");
    return { ok: res.ok, data: await res.json() };
  },
  async json(url, method, body) {
    const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    return { ok: res.ok, data: await res.json() };
  },
  async loadDemo() {
    const res = await fetch("/api/demo/load", { method: "POST" });
    return { ok: res.ok, data: await res.json() };
  },
};

const state = { jobs: [], activeJobId: null, blind: false, candidates: [], compare: new Set() };
const STATUS_LABEL = { selected: "Selected", review: "Under review", rejected: "Rejected" };

function pill(status, source) {
  return `<span class="status-pill st-${status}">${STATUS_LABEL[status]}${source === "recruiter" ? " ·&nbsp;set by you" : ""}</span>`;
}
function shownName(c) { return state.blind ? `Candidate ${c.reference}` : c.name; }
function blindText(text, c) {
  if (!state.blind) return text;
  let out = text.replace(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, "[email hidden]")
    .replace(/\+?\d[\d\s().-]{8,}\d/g, "[phone hidden]");
  for (const part of c.name.split(/\s+/).filter((w) => w.length > 2))
    out = out.replace(new RegExp(part, "gi"), "[name hidden]");
  return out.split("\n").map((l) =>
    /college|university|institute|\biit\b|\bnit\b|\bbits\b|school of/i.test(l) ? "[education hidden]" : l).join("\n");
}

// ----------------------------------------------------------------- Utils --

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch {
    return "";
  }
}

// ------------------------------------------------------------ Panel switch --

const panels = {
  empty: document.getElementById("panelEmpty"),
  newRole: document.getElementById("panelNewRole"),
  role: document.getElementById("panelRole"),
  analyze: document.getElementById("panelAnalyze"),
  about: document.getElementById("panelAbout"),
  outbox: document.getElementById("panelOutbox"),
};

// The app has two separate tools. The sidebar shows only the one in use.
function setMode(mode) {
  const analyze = mode === "analyze";
  document.getElementById("sideRank").classList.toggle("hidden", analyze);
  document.getElementById("sideAnalyze").classList.toggle("hidden", !analyze);
  for (const [id, on] of [["modeRank", !analyze], ["modeAnalyze", analyze]]) {
    const b = document.getElementById(id);
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  }
}

function showPanel(name) {
  Object.values(panels).forEach((p) => p.classList.add("hidden"));
  panels[name].classList.remove("hidden");
  if (name === "analyze") setMode("analyze");
  else if (name !== "about" && name !== "outbox") setMode("rank");
  document.getElementById("btnOutbox").classList.toggle("active", name === "outbox");
  document.getElementById("btnAbout").classList.toggle("active", name === "about");
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------- Sidebar UI --

async function refreshRoleList() {
  state.jobs = await API.listJobs();
  const list = document.getElementById("roleList");
  const emptyHint = document.getElementById("roleListEmpty");

  list.querySelectorAll(".role-item").forEach((n) => n.remove());

  if (state.jobs.length === 0) {
    emptyHint.classList.remove("hidden");
    return;
  }
  emptyHint.classList.add("hidden");

  for (const job of state.jobs) {
    const btn = el(`
      <button class="role-item" data-job-id="${job.id}">
        <div class="role-item-title">${escapeHtml(job.title)}</div>
        <div class="role-item-meta">${job.candidate_count} scored · ${formatDate(job.created_at)}</div>
      </button>
    `);
    btn.addEventListener("click", () => openRole(job.id));
    list.appendChild(btn);
  }
  highlightActiveRole();
}

function highlightActiveRole() {
  document.querySelectorAll(".role-item").forEach((n) => {
    n.classList.toggle("active", Number(n.dataset.jobId) === state.activeJobId);
  });
}

// ----------------------------------------------------------- New role form --

document.getElementById("btnNewRole").addEventListener("click", () => {
  document.getElementById("formNewRole").reset();
  showPanel("newRole");
});

document.getElementById("btnCancelNewRole").addEventListener("click", () => {
  if (state.activeJobId) openRole(state.activeJobId);
  else showPanel("empty");
});

document.getElementById("formNewRole").addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = document.getElementById("jobTitle").value.trim();
  const description = document.getElementById("jobDescription").value.trim();
  const submitBtn = e.target.querySelector('button[type="submit"]');
  submitBtn.disabled = true;
  submitBtn.textContent = "Creating…";

  const { ok, data } = await API.createJob(title, description);
  submitBtn.disabled = false;
  submitBtn.textContent = "Create role";

  if (!ok) {
    alert(data.error || "Could not create role.");
    return;
  }
  await refreshRoleList();
  openRole(data.id);
});

// --------------------------------------------------------------- Role view --

async function openRole(jobId) {
  state.activeJobId = jobId;
  state.lastJobId = jobId;
  highlightActiveRole();
  showPanel("role");

  const job = await API.getJob(jobId);
  document.getElementById("roleTitle").textContent = job.title;
  document.getElementById("roleMeta").textContent = `Created ${formatDate(job.created_at)}`;
  document.getElementById("jdViewer").textContent = job.description;
  document.getElementById("jdViewer").classList.add("hidden");
  document.getElementById("btnToggleJD").textContent = "View description";
  document.getElementById("uploadErrors").classList.add("hidden");
  document.getElementById("selAt").value = job.select_threshold;
  document.getElementById("revAt").value = job.review_threshold;
  document.getElementById("bandsMsg").textContent = "";
  document.getElementById("notifyMsg").textContent = "";
  document.getElementById("btnExport").href = `/api/jobs/${jobId}/export.csv`;

  await refreshCandidates(jobId);
}

document.getElementById("btnToggleJD").addEventListener("click", () => {
  const viewer = document.getElementById("jdViewer");
  const btn = document.getElementById("btnToggleJD");
  viewer.classList.toggle("hidden");
  btn.textContent = viewer.classList.contains("hidden") ? "View description" : "Hide description";
});

document.getElementById("btnDeleteRole").addEventListener("click", async () => {
  if (!state.activeJobId) return;
  if (!confirm("Delete this role and all its scored candidates? This can't be undone.")) return;
  await API.deleteJob(state.activeJobId);
  state.activeJobId = null;
  await refreshRoleList();
  showPanel("empty");
});

// ------------------------------------------- Role fit + skill priority chips --

function roleBars(fits) {
  return fits.slice(0, 4).map((f, i) => `
    <div class="score-row">
      <div class="score-row-label">${escapeHtml(f.role)}</div>
      <div class="score-row-bar"><div class="score-row-fill ${i === 0 ? "" : "teal"}" style="width:${f.percent}%"></div></div>
      <div class="score-row-num">${f.percent.toFixed(0)}%</div>
    </div>`).join("");
}

function priorityChips(priority, limit) {
  return priority.slice(0, limit).map((s) =>
    `<span class="tag lvl-${s.level.toLowerCase()}" title="${s.mentions} mention${s.mentions === 1 ? "" : "s"}">${escapeHtml(s.skill)}<span class="mention-count">${s.mentions}</span></span>`
  ).join("");
}

// ------------------------------------------------------------ Candidates --

async function renderOverview(jobId) {
  const box = document.getElementById("overview");
  const a = await (await fetch(`/api/jobs/${jobId}/analytics`)).json();
  if (!a.total) { box.innerHTML = ""; return; }
  const max = Math.max(...a.histogram, 1);
  const bars = a.histogram.map((n, i) => {
    const lo = i * 10;
    const cls = lo >= a.select_threshold ? "st-selected" : lo >= a.review_threshold ? "st-review" : "st-rejected";
    return `<div class="hist-col" title="${lo}-${lo + 10}: ${n}"><div class="hist-bar ${cls}" style="height:${(n / max) * 100}%"></div><span>${lo}</span></div>`;
  }).join("");
  const chips = (arr) => arr.length ? arr.map((s) => `<span class="tag missing">${escapeHtml(s.skill)}<span class="mention-count">${s.count}</span></span>`).join("") : '<span class="empty-hint">None</span>';
  box.innerHTML = `
    <div class="ov-grid">
      <div class="ov-tile"><div class="ov-num">${a.total}</div><div class="ov-lbl">Applied</div></div>
      <div class="ov-tile st-review"><div class="ov-num">${a.counts.review}</div><div class="ov-lbl">Under review</div></div>
      <div class="ov-tile st-selected"><div class="ov-num">${a.counts.selected}</div><div class="ov-lbl">Selected</div></div>
      <div class="ov-tile st-rejected"><div class="ov-num">${a.counts.rejected}</div><div class="ov-lbl">Rejected</div></div>
      <div class="ov-tile"><div class="ov-num">${a.average_score}</div><div class="ov-lbl">Average score</div></div>
      <div class="ov-tile"><div class="ov-num">${a.flagged}</div><div class="ov-lbl">Flagged</div></div>
    </div>
    <div class="ov-cols">
      <div><h3>Score spread</h3><div class="hist">${bars}</div></div>
      <div><h3>Most common missing skills</h3><div class="tag-list">${chips(a.top_missing)}</div>
      <h3>Listed but not shown in work</h3><div class="tag-list">${chips(a.top_unproven)}</div></div>
    </div>`;
}

async function refreshCandidates(jobId) {
  const candidates = await API.listCandidates(jobId);
  state.candidates = candidates;
  const table = document.getElementById("candidateTable");
  const emptyHint = document.getElementById("candidatesEmpty");
  const count = document.getElementById("candidateCount");

  table.innerHTML = "";
  count.textContent = candidates.length ? `${candidates.length} scored` : "";
  document.getElementById("btnNotifyAll").disabled = !candidates.length;
  renderOverview(jobId);
  state.compare = new Set([...state.compare].filter((id) => candidates.some((c) => c.id === id)));
  updateCompareBtn();

  if (candidates.length === 0) {
    emptyHint.classList.remove("hidden");
    return;
  }
  emptyHint.classList.add("hidden");

  candidates.forEach((c) => {
    const flag = c.flags.length ? `<span class="flag-mark" title="${escapeHtml(c.flags.map((f) => f.label).join("; "))}">⚑ ${c.flags.length}</span>` : "";
    const told = c.notified_status ? `<span class="told" title="Last told: ${STATUS_LABEL[c.notified_status]}">✉</span>` : "";
    const card = el(`
      <div class="candidate-card" data-candidate-id="${c.id}" tabindex="0" role="button">
        <div class="candidate-rank"><input type="checkbox" class="cmp-box" aria-label="Compare ${escapeHtml(shownName(c))}" ${state.compare.has(c.id) ? "checked" : ""}><span>${String(c.rank).padStart(2, "0")}</span></div>
        <div>
          <div class="candidate-name">${escapeHtml(shownName(c))} ${flag} ${told}</div>
          <div class="candidate-skills-line">
            ${pill(c.status, c.status_source)}
            <span class="tag-matched">${c.matched_skills.length} matched</span>
            &nbsp;·&nbsp;
            <span class="tag-missing">${c.missing_skills.length} missing</span>
          </div>
        </div>
        <div class="candidate-score-bar"><div class="candidate-score-fill" data-target="${c.final_score}"></div></div>
        <div class="candidate-score-num">${c.final_score.toFixed(0)}</div>
      </div>
    `);
    const box = card.querySelector(".cmp-box");
    box.addEventListener("click", (e) => {
      e.stopPropagation();
      if (box.checked) {
        if (state.compare.size >= 3) { box.checked = false; return updateCompareBtn("Pick at most 3 to compare."); }
        state.compare.add(c.id);
      } else state.compare.delete(c.id);
      updateCompareBtn();
    });
    card.addEventListener("click", () => openCandidateDrawer(c.id));
    card.addEventListener("keypress", (e) => { if (e.key === "Enter") openCandidateDrawer(c.id); });
    table.appendChild(card);
  });

  requestAnimationFrame(() => {
    table.querySelectorAll(".candidate-score-fill").forEach((bar) => {
      bar.style.width = `${bar.dataset.target}%`;
    });
  });
}

function updateCompareBtn(note) {
  const b = document.getElementById("btnCompare");
  b.textContent = state.compare.size ? `Compare (${state.compare.size})` : "Compare";
  b.disabled = state.compare.size < 2;
  b.title = note || "Tick 2 or 3 candidates, then compare";
}

function closeCompare() { document.getElementById("compareBackdrop").classList.add("hidden"); }

document.getElementById("btnCompare").addEventListener("click", () => {
  const picked = state.candidates.filter((c) => state.compare.has(c.id));
  if (picked.length < 2) return;
  const skills = new Set();
  picked.forEach((c) => {
    (c.evidence.proven_skills || []).forEach((s) => skills.add(s));
    (c.evidence.listed_skills || []).forEach((s) => skills.add(s));
    c.missing_skills.forEach((s) => skills.add(s));
  });
  const cell = (c, s) =>
    (c.evidence.proven_skills || []).includes(s) ? '<td class="cmp-yes" title="Shown in projects or experience">✓ shown</td>'
    : (c.evidence.listed_skills || []).includes(s) ? '<td class="cmp-listed" title="Only in the skills list">~ listed</td>'
    : '<td class="cmp-no" title="Not on the resume">✗ missing</td>';
  const best = (get) => Math.max(...picked.map(get));
  const num = (c, get) => `<td class="${get(c) === best(get) ? "cmp-best" : ""}">${get(c).toFixed(0)}</td>`;
  const rows = [
    ["Overall score", (c) => c.final_score],
    ["Skill evidence", (c) => c.skill_coverage_score],
    ["Text similarity", (c) => c.similarity_score],
    ["Depth of work", (c) => c.depth_score],
  ].map(([label, get]) => `<tr><th>${label}</th>${picked.map((c) => num(c, get)).join("")}</tr>`).join("");
  document.getElementById("compareContent").innerHTML = `
    <h2>Compare candidates</h2>
    <div class="cmp-scroll"><table class="cmp-table">
      <thead><tr><th></th>${picked.map((c) => `<th>${escapeHtml(shownName(c))}<div class="hint-inline">Rank ${c.rank}</div></th>`).join("")}</tr></thead>
      <tbody>
        <tr><th>Decision</th>${picked.map((c) => `<td>${pill(c.status, c.status_source)}</td>`).join("")}</tr>
        ${rows}
        <tr><th>Flags</th>${picked.map((c) => `<td>${c.flags.length ? "⚑ " + c.flags.map((f) => escapeHtml(f.label)).join("; ") : "None"}</td>`).join("")}</tr>
        <tr class="cmp-sep"><th colspan="${picked.length + 1}">Skills the role asks for or the resume shows</th></tr>
        ${[...skills].sort().map((s) => `<tr><th>${escapeHtml(s)}</th>${picked.map((c) => cell(c, s)).join("")}</tr>`).join("")}
      </tbody>
    </table></div>`;
  document.getElementById("compareBackdrop").classList.remove("hidden");
});
document.getElementById("compareClose").addEventListener("click", closeCompare);
document.getElementById("compareBackdrop").addEventListener("click", (e) => { if (e.target.id === "compareBackdrop") closeCompare(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeCompare(); });

document.getElementById("blindToggle").addEventListener("change", (e) => {
  state.blind = e.target.checked;
  if (state.activeJobId) refreshCandidates(state.activeJobId);
});

document.getElementById("btnSaveBands").addEventListener("click", async () => {
  const msg = document.getElementById("bandsMsg");
  const { ok, data } = await API.json(`/api/jobs/${state.activeJobId}`, "PATCH", {
    select_threshold: Number(document.getElementById("selAt").value),
    review_threshold: Number(document.getElementById("revAt").value),
  });
  msg.textContent = ok ? "Saved. Decisions updated." : data.error;
  if (ok) await refreshCandidates(state.activeJobId);
});

document.getElementById("btnNotifyAll").addEventListener("click", async () => {
  const msg = document.getElementById("notifyMsg");
  const pending = state.candidates.filter((c) => c.notified_status !== c.status);
  const withMail = pending.filter((c) => c.email);
  if (!pending.length) { msg.textContent = "Every candidate has already been told their current status."; return; }
  const mode = (await (await fetch("/api/mail/mode")).json()).mode;
  const where = mode === "smtp" ? "EMAILS WILL BE SENT" : "Outbox mode: messages are saved, nothing is sent";
  if (!confirm(`${withMail.length} candidate(s) will get a message about their current status (${pending.length - withMail.length} have no email).\n\n${where}.\n\nYou can read each draft first by opening a candidate. Continue?`)) return;
  const jobId = state.activeJobId;
  const { data } = await API.json(`/api/jobs/${jobId}/notify`, "POST");
  msg.textContent = `${data.messaged} message(s) ${data.mode === "smtp" ? "sent" : "saved to the outbox"}, ${data.failed} failed, ${data.no_email} without email, ${data.up_to_date} already up to date.`;
  if (state.activeJobId === jobId) await refreshCandidates(jobId);
});

// ------------------------------------------------------------ File upload --

const uploadZone = document.getElementById("uploadZone");
const fileInput = document.getElementById("fileInput");

document.getElementById("btnBrowse").addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) handleUpload(fileInput.files);
});

["dragenter", "dragover"].forEach((evt) =>
  uploadZone.addEventListener(evt, (e) => {
    e.preventDefault();
    uploadZone.classList.add("drag-over");
  })
);
["dragleave", "drop"].forEach((evt) =>
  uploadZone.addEventListener(evt, (e) => {
    e.preventDefault();
    uploadZone.classList.remove("drag-over");
  })
);
uploadZone.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files);
});

async function handleUpload(fileList) {
  if (!state.activeJobId) return;
  const errorsBox = document.getElementById("uploadErrors");
  errorsBox.classList.add("hidden");
  errorsBox.innerHTML = "";

  uploadZone.querySelector(".upload-title").textContent = `Scoring ${fileList.length} file(s)…`;

  const { data } = await API.uploadResumes(state.activeJobId, fileList);

  uploadZone.querySelector(".upload-title").innerHTML =
    'Drop resumes here, or <button type="button" id="btnBrowse2" class="link-btn">browse files</button>';
  document.getElementById("btnBrowse2").addEventListener("click", () => fileInput.click());
  fileInput.value = "";

  if (data.errors && data.errors.length) {
    errorsBox.classList.remove("hidden");
    errorsBox.innerHTML =
      `<strong>${data.errors.length} file(s) skipped:</strong><ul>` +
      data.errors.map((e) => `<li>${escapeHtml(e.filename || "unknown")} — ${escapeHtml(e.error)}</li>`).join("") +
      `</ul>`;
  }

  await refreshCandidates(state.activeJobId);
  await refreshRoleList();
}

// ------------------------------------------------------- Candidate drawer --

const drawerBackdrop = document.getElementById("drawerBackdrop");
const drawerContent = document.getElementById("drawerContent");

async function openCandidateDrawer(candidateId) {
  const c = await API.getCandidate(candidateId);
  const [rolesRes, draft, qRes] = await Promise.all([
    fetch(`/api/candidates/${candidateId}/other-roles`).then((r) => r.json()),
    fetch(`/api/candidates/${candidateId}/message`).then((r) => r.json()),
    fetch(`/api/candidates/${candidateId}/questions`).then((r) => r.json()),
  ]);
  const ev = c.evidence || {};

  const tagList = (arr, cls) =>
    arr.length
      ? `<div class="tag-list">${arr.map((s) => `<span class="tag ${cls}">${escapeHtml(s)}</span>`).join("")}</div>`
      : `<p class="empty-hint">None</p>`;
  const row = (label, v, teal) => `
      <div class="score-row">
        <div class="score-row-label">${label}</div>
        <div class="score-row-bar"><div class="score-row-fill ${teal ? "teal" : ""}" style="width:${v}%"></div></div>
        <div class="score-row-num">${v.toFixed(0)}</div>
      </div>`;
  const flags = c.flags.length
    ? `<div class="flag-box">${c.flags.map((f) => `<p>⚑ ${escapeHtml(f.label)}</p>`).join("")}</div>` : "";
  const roles = rolesRes.roles.length
    ? rolesRes.roles.map((r) => `<li><strong>${escapeHtml(r.title)}</strong> · ${r.score} ${pill(r.status)}</li>`).join("")
    : "<li class='empty-hint'>No other open role reaches its review band.</li>";
  const best = c.profile && c.profile.best_role ? `${c.profile.best_role} (${c.profile.confidence} confidence)` : "Not available";
  const email = c.email ? escapeHtml(c.email) : "none found on resume";

  drawerContent.innerHTML = `
    <h2>${escapeHtml(shownName(c))}</h2>
    <div class="drawer-filename">${state.blind ? "Identity hidden" : escapeHtml(c.filename) + " · " + email}</div>
    <p class="rank-line">Rank ${c.rank} of ${c.job_candidate_count} · top ${c.top_percent}% · reference ${escapeHtml(c.reference)}</p>

    <div class="summary-box" id="candSummary"><span class="hint-inline">Writing summary…</span></div>

    <div class="decision-box">
      <div>${pill(c.status, c.status_source)} <span class="hint-inline">Score suggests: ${STATUS_LABEL[c.suggested_status]}</span></div>
      <label class="inline">Recruiter decision
        <select id="overrideSel">
          <option value="">Follow the score</option>
          ${["selected", "review", "rejected"].map((s) => `<option value="${s}" ${c.status_source === "recruiter" && c.status === s ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("")}
        </select></label>
    </div>
    ${flags}

    <div class="score-breakdown">
      ${row("Overall match", c.final_score)}
      ${row("Skill evidence (55%)", c.skill_coverage_score, true)}
      ${row("Text similarity (30%)", c.similarity_score, true)}
      <p class="hint-inline">Similarity method: ${ev.similarity_backend === "embeddings" ? "sentence embeddings (meaning)" : "TF-IDF (word overlap)"}</p>
      ${row("Depth of work (15%)", c.depth_score, true)}
    </div>

    <div class="skills-section">
      <h3>Proven in projects or experience (${(ev.proven_skills || []).length})</h3>
      ${tagList(ev.proven_skills || [], "matched")}
    </div>
    <div class="skills-section">
      <h3>Claimed only, listed in skills (${(ev.listed_skills || []).length})</h3>
      ${tagList(ev.listed_skills || [], "claimed")}
    </div>
    <div class="skills-section">
      <h3>Missing skills (${c.missing_skills.length})</h3>
      ${tagList(c.missing_skills, "missing")}
    </div>
    <div class="skills-section">
      <h3>Additional skills on resume (${c.extra_skills.length})</h3>
      ${tagList(c.extra_skills, "extra")}
    </div>

    <div class="skills-section">
      <h3>Other roles this resume fits</h3>
      <p class="hint-inline">Best-fit profile: ${escapeHtml(best)}</p>
      <ul class="role-suggest">${roles}</ul>
    </div>

    <div class="skills-section">
      <h3>Interview questions</h3>
      <p class="hint-inline">Built from this resume's evidence: claims to check first, then gaps, then depth.</p>
      <ol class="qlist">${qRes.questions.map((q) => `<li><span class="qkind q-${q.kind}">${{ prove: "Check claim", gap: "Gap", depth: "Depth", integrity: "Integrity" }[q.kind]}</span> ${escapeHtml(q.question)}</li>`).join("") || "<li class='empty-hint'>No questions.</li>"}</ol>
      <button class="btn-secondary small" id="btnCopyQ" type="button">Copy questions</button>
    </div>

    <div class="skills-section">
      <h3>Message to candidate</h3>
      <p class="hint-inline">${draft.can_send ? `To ${escapeHtml(draft.to)} · ${draft.mode === "smtp" ? "will be emailed" : "outbox mode: saved, not sent"}` : escapeHtml(draft.reason)}</p>
      <div class="resume-preview"><strong>${escapeHtml(draft.subject)}</strong>\n\n${escapeHtml(draft.body)}</div>
      <button class="btn-primary small" id="btnSendOne" type="button" ${draft.can_send ? "" : "disabled"}>Approve and send</button>
      <span class="tool-msg" id="sendMsg" aria-live="polite">${c.notified_status ? "Last told: " + STATUS_LABEL[c.notified_status] : ""}</span>
    </div>

    <div class="skills-section">
      <h3>Resume text${state.blind ? " (identity masked)" : ""}</h3>
      <div class="resume-preview">${escapeHtml(blindText(c.resume_text, c))}</div>
    </div>
  `;

  fetch(`/api/candidates/${c.id}/summary`).then((r) => r.json()).then((s) => {
    const box = document.getElementById("candSummary");
    if (!box) return;
    box.innerHTML = `<p>${escapeHtml(s.text)}</p><span class="hint-inline">${s.source === "llm" ? "Written by an LLM from the evidence below" : "Written from the evidence below"} · does not change the score</span>`;
  });
  document.getElementById("btnCopyQ").addEventListener("click", async (e) => {
    const text = qRes.questions.map((q, i) => `${i + 1}. ${q.question}`).join("\n");
    try { await navigator.clipboard.writeText(text); e.target.textContent = "Copied"; }
    catch { e.target.textContent = "Copy failed"; }
  });
  document.getElementById("overrideSel").addEventListener("change", async (e) => {
    await API.json(`/api/candidates/${c.id}`, "PATCH", { status: e.target.value });
    await refreshCandidates(state.activeJobId);
    openCandidateDrawer(c.id);
  });
  document.getElementById("btnSendOne").addEventListener("click", async () => {
    const m = document.getElementById("sendMsg");
    const { ok, data } = await API.json(`/api/candidates/${c.id}/notify`, "POST");
    m.textContent = ok ? (data.mode === "smtp" ? "Sent." : "Saved to the outbox (nothing was sent).") : data.error;
    if (ok) refreshCandidates(state.activeJobId);
  });

  drawerBackdrop.classList.remove("hidden");
}

document.getElementById("drawerClose").addEventListener("click", () => drawerBackdrop.classList.add("hidden"));
drawerBackdrop.addEventListener("click", (e) => {
  if (e.target === drawerBackdrop) drawerBackdrop.classList.add("hidden");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") drawerBackdrop.classList.add("hidden");
});

// ----------------------------------------------------------- Analyze view --

function renderAnalysis(data, isDemo) {
  const box = document.getElementById("analyzeResults");
  const summary = document.getElementById("analyzeSummary");
  const errorsBox = document.getElementById("analyzeErrors");
  box.innerHTML = "";
  summary.classList.add("hidden");
  errorsBox.classList.add("hidden");

  if (data.errors && data.errors.length) {
    errorsBox.classList.remove("hidden");
    errorsBox.innerHTML = `<strong>${data.errors.length} file(s) skipped:</strong><ul>` +
      data.errors.map((e) => `<li>${escapeHtml(e.filename || "unknown")} — ${escapeHtml(e.error)}</li>`).join("") + "</ul>";
  }
  const results = data.results || [];
  if (!results.length) return;

  // Group by detected role so the page reads as buckets.
  const groups = {};
  results.forEach((r) => { (groups[r.best_role] = groups[r.best_role] || []).push(r); });
  const order = Object.keys(groups).sort((a, b) =>
    (a === "Unclassified") - (b === "Unclassified") || groups[b].length - groups[a].length);

  let summaryHtml = order.map((role) =>
    `<span class="bucket-chip">${escapeHtml(role)} <strong>${groups[role].length}</strong></span>`).join("");
  if (isDemo && data.summary) {
    const s = data.summary;
    summaryHtml += `<p class="summary-note">The demo resumes were written to represent known roles. The detected role matches in <strong>${s.correct} of ${s.labelled}</strong>; where confidence was High or Medium, it matches in <strong>${s.confident_correct} of ${s.confident}</strong>. The rest are mixed profiles flagged Low confidence. These resumes are invented, so treat this as a sanity check rather than a benchmark.</p>`;
  }
  summaryHtml += `<p class="legend summary-legend"><span class="tag lvl-primary">Primary</span><span class="tag lvl-secondary">Secondary</span><span class="tag lvl-mentioned">Mentioned</span> Skills are ranked by how often the resume uses them. The number is the count.</p>`;
  summary.innerHTML = summaryHtml;
  summary.classList.remove("hidden");

  order.forEach((role) => {
    const section = el(`<div class="bucket"><h2>${escapeHtml(role)} <span class="candidate-count">${groups[role].length}</span></h2></div>`);
    groups[role].forEach((r) => {
      const miss = r.matches_expected === false
        ? `<div class="expected-note">Written to represent: ${escapeHtml(r.expected_role)}</div>` : "";
      const fitBlock = r.role_fit.length
        ? `<div class="analyze-fit">${roleBars(r.role_fit.slice(0, 3))}</div>`
        : `<p class="analyze-none">No technical skills found.</p>`;
      section.appendChild(el(`
        <div class="analyze-card">
          <div class="analyze-head">
            <span class="candidate-name">${escapeHtml(r.name)}</span>
            <span class="conf-pill conf-${r.confidence.toLowerCase()}">${r.confidence === "None" ? "No match" : r.confidence + " confidence"}</span>
          </div>
          ${fitBlock}
          ${r.skill_priority.length ? `<div class="tag-list">${priorityChips(r.skill_priority, 9)}</div>` : ""}
          ${miss}
        </div>`));
    });
    box.appendChild(section);
  });
}

async function runAnalyze(files) {
  const title = document.querySelector("#analyzeZone .upload-title");
  const original = title.innerHTML;
  title.textContent = `Reading ${files.length} file(s)…`;
  const { data } = await API.analyze(files);
  title.innerHTML = original;
  document.getElementById("btnAnalyzeBrowse").addEventListener("click", () => analyzeInput.click());
  analyzeInput.value = "";
  renderAnalysis(data, false);
}

const analyzeInput = document.getElementById("analyzeInput");
const analyzeZone = document.getElementById("analyzeZone");
document.getElementById("btnAnalyzeBrowse").addEventListener("click", () => analyzeInput.click());
analyzeInput.addEventListener("change", () => { if (analyzeInput.files.length) runAnalyze(analyzeInput.files); });
["dragenter", "dragover"].forEach((evt) => analyzeZone.addEventListener(evt, (e) => {
  e.preventDefault(); analyzeZone.classList.add("drag-over");
}));
["dragleave", "drop"].forEach((evt) => analyzeZone.addEventListener(evt, (e) => {
  e.preventDefault(); analyzeZone.classList.remove("drag-over");
}));
analyzeZone.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) runAnalyze(e.dataTransfer.files); });

function openAnalyze() {
  state.activeJobId = null;
  highlightActiveRole();
  showPanel("analyze");
}
document.getElementById("modeAnalyze").addEventListener("click", openAnalyze);
document.getElementById("btnEmptyAnalyze").addEventListener("click", openAnalyze);
document.getElementById("modeRank").addEventListener("click", () => {
  // Return to the role the user was last looking at, if it still exists.
  const last = state.jobs.find((j) => j.id === state.lastJobId);
  if (last) openRole(last.id);
  else showPanel("empty");
});
document.getElementById("btnEmptyNew").addEventListener("click", () => document.getElementById("btnNewRole").click());
document.getElementById("btnAbout").addEventListener("click", () => {
  state.activeJobId = null;
  highlightActiveRole();
  showPanel("about");
});

document.getElementById("btnAnalyzeDemo").addEventListener("click", async () => {
  const { data } = await API.analyzeDemo();
  renderAnalysis(data, true);
});

// ------------------------------------------------------------- Demo data --

document.getElementById("btnLoadDemo").addEventListener("click", async () => {
  const btn = document.getElementById("btnLoadDemo");
  const status = document.getElementById("demoStatus");
  btn.disabled = true;
  status.textContent = "Scoring 25 resumes against 5 jobs…";
  const { ok, data } = await API.loadDemo();
  btn.disabled = false;
  if (!ok) { status.textContent = data.error || "Could not load the demo data."; return; }
  status.textContent = data.created_jobs
    ? `Loaded ${data.created_jobs} jobs, each scored against ${data.resumes} resumes. Pick a role on the left.`
    : "Demo data is already loaded. Pick a role on the left.";
  await refreshRoleList();
});

// ------------------------------------------------------------------ Outbox --

async function openOutbox() {
  state.activeJobId = null;
  highlightActiveRole();
  showPanel("outbox");
  const mode = (await (await fetch("/api/mail/mode")).json()).mode;
  document.getElementById("outboxLead").textContent = mode === "smtp"
    ? "Email is connected. Messages here were sent to candidates."
    : "Outbox mode: messages are saved here and nothing leaves the server. Set SMTP_HOST to send real email.";
  const msgs = await (await fetch("/api/messages")).json();
  const box = document.getElementById("outboxList");
  box.innerHTML = msgs.length ? "" : '<p class="empty-hint">No messages yet. Approve one from a candidate, or use Message candidates on a role.</p>';
  msgs.forEach((m) => box.appendChild(el(`
    <div class="outbox-item">
      <div class="outbox-head"><strong>${escapeHtml(m.subject)}</strong>
        <span class="tool-msg">${escapeHtml(m.delivery)} · ${formatDate(m.created_at)}</span></div>
      <div class="hint-inline">To ${escapeHtml(m.to_email)} · ${escapeHtml(m.candidate_name)} · ${escapeHtml(m.job_title)}</div>
      <details><summary>Show message</summary><div class="resume-preview">${escapeHtml(m.body)}</div></details>
    </div>`)));
}
document.getElementById("btnOutbox").addEventListener("click", openOutbox);
fetch("/api/mail/mode").then((r) => r.json()).then((d) => {
  document.getElementById("mailMode").textContent = d.mode === "smtp" ? "(live)" : "(demo)";
});

// -------------------------------------------------------------------- Init --

refreshRoleList().then(() => showPanel("empty"));

// ----------------------------------------------------------------- Sign out --

fetch("/api/auth/me").then((r) => r.json()).then((d) => {
  if (d.user) document.getElementById("whoami").textContent = d.user;
});
document.getElementById("btnSignOut").addEventListener("click", async () => {
  await _fetch("/api/auth/logout", { method: "POST" });
  location.href = "/login";
});
