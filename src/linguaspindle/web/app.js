const root = document.querySelector("#app");
const toastRegion = document.querySelector("#toast-region");
let pollTimer = null;

const escapeHtml = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const date = (value) => value ? new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium", timeStyle: "short"
}).format(new Date(value)) : "—";

const bytes = (value) => {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 ** 2).toFixed(1)} MiB`;
};

const badge = (status) => `<span class="badge ${escapeHtml(status)}">${escapeHtml(status.replaceAll("_", " "))}</span>`;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const error = body?.error || body?.detail || { message: String(body) };
    throw new Error(error.message || JSON.stringify(error));
  }
  return body;
}

function toast(message) {
  toastRegion.innerHTML = `<div class="toast">${escapeHtml(message)}</div>`;
  window.setTimeout(() => { toastRegion.innerHTML = ""; }, 3500);
}

function pageHead(eyebrow, title, lede, action = "") {
  return `<header class="page-head"><div><p class="eyebrow">${escapeHtml(eyebrow)}</p><h1>${escapeHtml(title)}</h1><p class="lede">${escapeHtml(lede)}</p></div>${action}</header>`;
}

function setActiveNavigation(route) {
  document.querySelectorAll("[data-nav]").forEach((link) => link.classList.remove("active"));
  const key = route === "/" ? "dashboard" : route === "/projects/new" ? "new" : route.startsWith("/projects") ? "projects" : route === "/settings" ? "settings" : "";
  document.querySelector(`[data-nav="${key}"]`)?.classList.add("active");
}

async function dashboard() {
  const [system, jobs, adapters, providers] = await Promise.all([
    api("/api/system"), api("/api/jobs"), api("/api/adapters"), api("/api/providers")
  ]);
  const availableAdapters = adapters.filter((item) => item.health.available).length;
  const configuredProviders = providers.filter((item) => item.configured).length;
  root.innerHTML = `${pageHead("v0.1.0 workspace", "Translation operations, at a glance", "One durable queue for novels, manga, CLI, and API — with every intermediate result kept as an Artifact.", '<a class="button primary" href="#/projects/new">Create project</a>')}
    <section class="stats" aria-label="System overview">
      <div class="stat"><small>Projects</small><strong>${system.project_count}</strong></div>
      <div class="stat"><small>Active jobs</small><strong>${system.active_job_count}</strong></div>
      <div class="stat"><small>Ready adapters</small><strong>${availableAdapters}/${adapters.length}</strong></div>
      <div class="stat"><small>Providers</small><strong>${configuredProviders}/${providers.length}</strong></div>
    </section>
    <div class="grid-2">
      <section class="card"><div class="card-head"><h2>Recent jobs</h2><a href="#/projects">All projects</a></div>
        <div class="list">${jobs.length ? jobs.slice(0, 8).map((job) => `<div class="list-row"><div><a href="#/jobs/${job.id}">${escapeHtml(job.pipeline_key)}</a><div class="meta"><span>${date(job.requested_at)}</span><span>${Math.round(job.progress * 100)}%</span></div></div>${badge(job.status)}</div>`).join("") : '<div class="empty">No Jobs yet.</div>'}</div>
      </section>
      <section class="card"><div class="card-head"><h2>Capability health</h2><a href="#/settings">Details</a></div>
        <div class="list">${adapters.map((item) => `<div class="list-row"><div><strong>${escapeHtml(item.display_name)}</strong><div class="meta"><span>${escapeHtml(item.health.message)}</span></div></div>${badge(item.health.available ? "available" : "unavailable")}</div>`).join("")}</div>
      </section>
    </div>`;
}

async function projects() {
  const items = await api("/api/projects");
  root.innerHTML = `${pageHead("Library", "Projects", "Long-lived translation workspaces. Sources remain immutable across every rerun.", '<a class="button primary" href="#/projects/new">New project</a>')}
    <section class="card"><div class="list">${items.length ? items.map((item) => `<div class="list-row"><div><a href="#/projects/${item.id}">${escapeHtml(item.name)}</a><div class="meta"><span>${escapeHtml(item.kind)}</span><span>${escapeHtml(item.source_language)} → ${escapeHtml(item.target_language)}</span><span>${date(item.created_at)}</span></div></div>${item.latest_job ? badge(item.latest_job.status) : '<span class="badge">not run</span>'}</div>`).join("") : '<div class="empty">Create a TXT novel or CBZ manga project to begin.</div>'}</div></section>`;
}

async function newProject() {
  root.innerHTML = `${pageHead("Import", "Create a project", "Import bytes are copied into the Artifact store and never overwritten in place.")}
    <section class="card"><form id="project-form">
      <div class="field-grid">
        <label>Project name<input name="name" required maxlength="200" placeholder="The Clockmaker’s Garden" /></label>
        <label>Project type<select name="kind" id="project-kind"><option value="novel">Novel (TXT)</option><option value="manga">Manga (CBZ/ZIP/image)</option></select></label>
        <label>Source language<input name="source_language" required value="en" /></label>
        <label>Target language<input name="target_language" required value="zh-CN" /></label>
      </div>
      <label>Source file<input type="file" name="source" required accept=".txt" id="source-file" /><span class="hint">TXT for novels; CBZ, ZIP, PNG, JPEG, or WebP for manga.</span></label>
      <div class="actions"><button class="button primary" type="submit">Create project</button><a class="button secondary" href="#/projects">Cancel</a></div>
    </form></section>`;
  const kind = document.querySelector("#project-kind");
  const source = document.querySelector("#source-file");
  kind.addEventListener("change", () => { source.accept = kind.value === "novel" ? ".txt" : ".cbz,.zip,.png,.jpg,.jpeg,.webp"; });
  document.querySelector("#project-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button");
    button.disabled = true; button.textContent = "Importing…";
    try {
      const project = await api("/api/projects", { method: "POST", body: new FormData(event.currentTarget) });
      toast("Project created"); window.location.hash = `#/projects/${project.id}`;
    } catch (error) { toast(error.message); button.disabled = false; button.textContent = "Create project"; }
  });
}

async function projectDetail(id) {
  const [project, providers, adapters] = await Promise.all([
    api(`/api/projects/${id}`), api("/api/providers"), api("/api/adapters")
  ]);
  let segments = [];
  try { segments = await api(`/api/projects/${id}/segments`); } catch (_) { /* no results yet */ }
  const projectActions = `<div class="actions"><a class="button secondary" href="#/projects">Back</a><button class="button danger" id="delete-project" type="button">Delete project</button></div>`;
  root.innerHTML = `${pageHead(project.kind, project.name, `${project.source_language} → ${project.target_language}`, projectActions)}
    <div class="grid-2">
      <section class="card"><div class="card-head"><h2>Run pipeline</h2></div><form id="run-form">
        ${project.kind === "novel" ? `<label>Translation Provider<select name="provider_id">${providers.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name)}${item.configured ? "" : " — not configured"}</option>`).join("")}</select></label>` : `<label>Manga Adapter<select name="adapter_id">${adapters.filter((item) => item.capabilities.includes("manga_full_pipeline")).map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.display_name)}${item.health.available ? "" : " — unavailable"}</option>`).join("")}</select></label>`}
        <button class="button primary" type="submit">Create asynchronous Job</button>
      </form></section>
      <section class="card"><div class="card-head"><h2>Source</h2></div>${project.sources.map((source) => `<div><strong>${escapeHtml(source.original_name)}</strong><div class="meta"><span>${escapeHtml(source.kind)}</span><span>${bytes(source.size)}</span><span class="mono">${escapeHtml(source.checksum.slice(0, 12))}</span></div></div>`).join("")}</section>
    </div>
    <section class="card"><div class="card-head"><h2>Job history</h2></div><div class="list">${project.jobs.length ? project.jobs.map((job) => `<div class="list-row"><div><a href="#/jobs/${job.id}">${escapeHtml(job.pipeline_key)}</a><div class="meta"><span>${date(job.requested_at)}</span><span>${Math.round(job.progress * 100)}%</span></div></div>${badge(job.status)}</div>`).join("") : '<div class="empty">No Jobs yet.</div>'}</div></section>
    <section class="card"><div class="card-head"><h2>Artifacts</h2></div><div class="list">${project.artifacts.length ? project.artifacts.map((artifact) => `<div class="list-row"><div><strong>${escapeHtml(artifact.kind)}</strong><div class="meta"><span>${escapeHtml(artifact.filename)}</span><span>${bytes(artifact.size)}</span></div></div><a class="button secondary" href="${artifact.download_url}">Download</a></div>`).join("") : '<div class="empty">No Artifacts.</div>'}</div></section>
    ${segments.length ? `<section class="card"><div class="card-head"><h2>Novel results</h2></div><div class="segments">${segments.map((segment) => `<article class="segment"><div><small>Source · ${segment.sequence + 1}</small>${escapeHtml(segment.source_text)}</div><div><small>Translation · ${escapeHtml(segment.status)}</small>${escapeHtml(segment.translated_text || segment.error?.message || "Pending")}${segment.qa_findings.length ? `<div class="qa">${segment.qa_findings.map((item) => escapeHtml(item.message)).join(" · ")}</div>` : ""}</div></article>`).join("")}</div></section>` : ""}`;
  document.querySelector("#run-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const job = await api(`/api/projects/${id}/jobs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      toast("Job queued"); window.location.hash = `#/jobs/${job.id}`;
    } catch (error) { toast(error.message); }
  });
  document.querySelector("#delete-project").addEventListener("click", async (event) => {
    const impact = `${project.sources.length} Source(s), ${project.jobs.length} Job(s), and ${project.artifacts.length} Artifact(s)`;
    if (!window.confirm(`Delete ${project.name}? This permanently removes ${impact} from this instance.`)) return;
    event.currentTarget.disabled = true;
    try {
      await api(`/api/projects/${id}?confirmed=true`, { method: "DELETE" });
      toast("Project deleted"); window.location.hash = "#/projects";
    } catch (error) { toast(error.message); event.currentTarget.disabled = false; }
  });
}

async function jobDetail(id) {
  const job = await api(`/api/jobs/${id}`);
  const active = ["queued", "running", "cancelling"].includes(job.status);
  const actions = `<div class="actions">${["queued", "running"].includes(job.status) ? '<button class="button secondary" data-action="pause">Pause</button>' : ""}${job.status === "paused" ? '<button class="button primary" data-action="resume">Resume</button>' : ""}${["queued", "running", "paused", "cancelling"].includes(job.status) ? '<button class="button danger" data-action="cancel">Cancel</button>' : ""}${["failed", "partially_succeeded"].includes(job.status) ? '<button class="button primary" data-action="retry">Retry failed work</button>' : ""}<a class="button secondary" href="#/projects/${job.project_id}">Project</a></div>`;
  root.innerHTML = `${pageHead("Persistent Job", job.pipeline_key, `Requested ${date(job.requested_at)}`, actions)}
    ${job.error ? `<div class="error-card"><strong>${escapeHtml(job.error.code)}</strong><br />${escapeHtml(job.error.message)}</div>` : ""}
    <section class="card"><div class="card-head"><div><h2>${escapeHtml(job.status.replaceAll("_", " "))}</h2><p class="muted">${Math.round(job.progress * 100)}% complete</p></div>${badge(job.status)}</div><div class="progress"><span style="width:${Math.round(job.progress * 100)}%"></span></div></section>
    <section class="card"><div class="card-head"><h2>Steps</h2><span class="muted">Attempts, Artifact links, and durable logs</span></div>${job.steps.map((step) => `<article class="step ${escapeHtml(step.status)}"><div class="card-head"><div><h3>${escapeHtml(step.key.replaceAll("_", " "))}</h3><div class="meta"><span>${escapeHtml(step.capability)}</span><span>attempt ${step.attempt_count}</span><span>${Math.round(step.progress * 100)}%</span></div></div>${badge(step.status)}</div><div class="artifact-links"><div><small>Input Artifacts</small>${step.input_artifact_ids.length ? step.input_artifact_ids.map((value) => `<span class="mono">${escapeHtml(value)}</span>`).join("") : '<span class="muted">none yet</span>'}</div><div><small>Output Artifacts</small>${step.output_artifact_ids.length ? step.output_artifact_ids.map((value) => `<span class="mono">${escapeHtml(value)}</span>`).join("") : '<span class="muted">none yet</span>'}</div></div>${step.error ? `<div class="error-card"><span class="mono">${escapeHtml(step.error.code)}</span> ${escapeHtml(step.error.message)}</div>` : ""}${step.logs.length ? `<div class="logs">${step.logs.map((log) => `<div class="${log.level === "ERROR" ? "log-error" : ""}">${escapeHtml(log.created_at)} ${escapeHtml(log.level)} ${escapeHtml(log.message)}</div>`).join("")}</div>` : ""}</article>`).join("")}</section>
    <section class="card"><div class="card-head"><h2>Job Artifacts</h2></div><div class="list">${job.artifacts.length ? job.artifacts.map((artifact) => `<div class="list-row"><div><strong>${escapeHtml(artifact.kind)}</strong><div class="meta"><span>${escapeHtml(artifact.filename)}</span><span>${bytes(artifact.size)}</span><span class="mono">${escapeHtml(artifact.id.slice(0, 8))}</span></div></div><a class="button secondary" href="${artifact.download_url}">Download</a></div>`).join("") : '<div class="empty">Artifacts appear as Steps complete.</div>'}</div></section>`;
  root.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", async () => {
    button.disabled = true;
    try { await api(`/api/jobs/${id}/${button.dataset.action}`, { method: "POST" }); toast(`${button.dataset.action} requested`); await jobDetail(id); }
    catch (error) { toast(error.message); button.disabled = false; }
  }));
  if (active) pollTimer = window.setTimeout(() => jobDetail(id).catch(showError), 900);
}

async function settings() {
  const [providers, adapters, pipelines] = await Promise.all([
    api("/api/providers"), api("/api/adapters"), api("/api/pipelines")
  ]);
  root.innerHTML = `${pageHead("Runtime capabilities", "Adapters & Providers", "Secrets remain in the process environment. External tools are installed and licensed separately.")}
    <section class="card"><div class="card-head"><h2>Translation Providers</h2></div><div class="grid-2">${providers.map((item) => `<article><div class="card-head"><h3>${escapeHtml(item.display_name)}</h3>${badge(item.configured ? "available" : "unavailable")}</div><div class="meta"><span>model ${escapeHtml(item.model)}</span>${item.base_url ? `<span>${escapeHtml(item.base_url)}</span>` : ""}</div>${!item.configured ? '<p class="muted">Set LINGUASPINDLE_OPENAI_API_KEY in the runtime environment.</p>' : ""}</article>`).join("")}</div></section>
    <section class="card"><div class="card-head"><h2>External Adapters</h2></div><div class="list">${adapters.map((item) => `<article class="list-row"><div><strong>${escapeHtml(item.display_name)}</strong><div class="meta"><span>${escapeHtml(item.invocation_type)}</span><span>${escapeHtml(item.upstream_license)}</span></div><p class="muted">${escapeHtml(item.health.message)} · ${escapeHtml(item.configuration_help)}</p><div class="meta">${item.capabilities.map((value) => `<span class="badge">${escapeHtml(value)}</span>`).join("")}</div></div>${badge(item.health.available ? "available" : "unavailable")}</article>`).join("")}</div></section>
    <section class="card"><div class="card-head"><h2>Pipeline Presets</h2></div><div class="grid-2">${pipelines.map((item) => `<article><h3>${escapeHtml(item.display_name)}</h3><div class="meta"><span>${escapeHtml(item.project_kind)}</span><span>version ${escapeHtml(item.version)}</span><span>${item.steps.length} ordered Steps</span></div></article>`).join("")}</div></section>`;
}

function showError(error) {
  root.innerHTML = `<div class="error-card"><strong>Could not load this view</strong><p>${escapeHtml(error.message)}</p><a href="#/">Return to dashboard</a></div>`;
}

async function router() {
  if (pollTimer) window.clearTimeout(pollTimer);
  pollTimer = null;
  const route = window.location.hash.slice(1) || "/";
  setActiveNavigation(route);
  root.innerHTML = '<div class="loading-card">Loading…</div>';
  try {
    if (route === "/") await dashboard();
    else if (route === "/projects") await projects();
    else if (route === "/projects/new") await newProject();
    else if (/^\/projects\/[^/]+$/.test(route)) await projectDetail(route.split("/")[2]);
    else if (/^\/jobs\/[^/]+$/.test(route)) await jobDetail(route.split("/")[2]);
    else if (route === "/settings") await settings();
    else root.innerHTML = '<div class="empty">Page not found. <a href="#/">Go home</a></div>';
    root.focus();
  } catch (error) { showError(error); }
}

window.addEventListener("hashchange", router);
router();
