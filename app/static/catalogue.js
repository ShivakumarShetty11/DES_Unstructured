const datasetGrid = document.getElementById("datasetGrid");
const datasetCount = document.getElementById("datasetCount");
const categorySelect = document.getElementById("categorySelect");
const subCategorySelect = document.getElementById("subCategorySelect");

let _categoryMap = {};   // category → [sub_categories]

categorySelect?.addEventListener("change", () => {
  // Update sub-category options immediately, then reload
  updateSubCategories();
  loadDatasets();
});
subCategorySelect?.addEventListener("change", loadDatasets);
document.getElementById("queryInput")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadDatasets();
});

loadDatasets();

async function loadDatasets() {
  datasetCount.textContent = "Loading…";

  const params = new URLSearchParams();
  const q = String(document.getElementById("queryInput").value || "").trim();
  const category = categorySelect.value;
  const subCategory = subCategorySelect.value;

  if (q) params.set("q", q);
  if (category) params.set("category", category);
  if (subCategory) params.set("sub_category", subCategory);

  try {
    const response = await fetch(`/api/datasets?${params.toString()}`);

    if (!response.ok) {
      const text = await response.text().catch(() => `HTTP ${response.status}`);
      datasetCount.textContent = `Server error (${response.status}) — try again in a moment`;
      datasetGrid.innerHTML = "";
      return;
    }

    const data = await response.json();

    renderFilters(data.filters || {});
    renderDatasets(data.datasets || []);
  } catch (err) {
    datasetCount.textContent = "Error loading datasets";
    datasetGrid.innerHTML = `<p class="muted">${escapeHtml(err.message)}</p>`;
  }
}

function renderFilters(filters) {
  _categoryMap = filters.category_map || {};
  refillSelect(categorySelect, filters.categories || [], "All Categories");
  updateSubCategories();
}

function updateSubCategories() {
  const selectedCat = categorySelect.value;
  const subs = selectedCat
    ? (_categoryMap[selectedCat] || [])
    : Object.values(_categoryMap).flat().filter((v, i, a) => a.indexOf(v) === i).sort();
  refillSelect(subCategorySelect, subs, "All Sub Categories");
}

function refillSelect(select, values, defaultLabel) {
  const active = select.value;
  select.innerHTML = [`<option value="">${defaultLabel}</option>`]
    .concat(values.map((v) => `<option value="${escapeAttr(v)}">${escapeHtml(v)}</option>`))
    .join("");
  if (active && values.includes(active)) select.value = active;
}

function renderDatasets(datasets) {
  const n = datasets.length;
  datasetCount.textContent = `${n} document${n !== 1 ? "s" : ""}`;

  if (!n) {
    datasetGrid.innerHTML = "<p class='muted'>No documents found. Try different search terms or clear the filters.</p>";
    return;
  }

  datasetGrid.innerHTML = datasets.map((d, i) => renderCard(d, i)).join("");
}

function renderCard(d, idx) {
  const tags = (d.tags || []).slice(0, 12);
  const summary = String(d.summary || "No summary available.").slice(0, 620);
  const hasSummaryMore = (d.summary || "").length > 620;
  const apiBase = window.location.origin;
  const panelId = `ep-${idx}`;

  const stats = [
    { label: "Type",       value: d.document_type     || "N/A" },
    { label: "Department", value: d.issuing_department || "N/A" },
    { label: "Year",       value: d.policy_year        || "N/A" },
    { label: "Language",   value: d.source_language    || "N/A" },
  ];

  return `
<article class="ds-card">
  <div class="ds-card-head">
    <h3 class="ds-title">${escapeHtml(d.title)}</h3>
    <span class="id-pill">${escapeHtml(d.dataset_id)}</span>
  </div>

  <div class="badge-row">
    ${d.category    ? `<span class="badge badge-primary">${escapeHtml(d.category)}</span>`    : ""}
    ${d.sub_category? `<span class="badge badge-accent">${escapeHtml(d.sub_category)}</span>` : ""}
    ${d.document_type ? `<span class="badge badge-neutral">${escapeHtml(d.document_type)}</span>` : ""}
  </div>

  <div class="stat-grid">
    ${stats.map((s) => `
      <div class="stat-item">
        <div class="stat-label">${s.label}</div>
        <div class="stat-value" title="${escapeAttr(s.value)}">${escapeHtml(s.value)}</div>
      </div>`).join("")}
  </div>

  <p class="summary-text">${escapeHtml(summary)}${hasSummaryMore ? "…" : ""}</p>

  ${tags.length ? `
  <div class="tag-row">
    ${tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("")}
  </div>` : ""}

  <div class="card-actions">
    <button class="btn btn-sm btn-primary" onclick="downloadDataset('${escapeAttr(d.dataset_id)}')">&#x2B07; Download JSON</button>
    <button class="btn btn-sm btn-primary" onclick="downloadDocument('${escapeAttr(d.dataset_id)}')">&#x2B07; Download Document</button>
    <button class="btn btn-sm" id="toggle-${panelId}" onclick="togglePanel('${panelId}', this)">{} API</button>
    ${d.document_url
      ? `<a class="btn btn-sm" href="${escapeAttr(d.document_url)}" target="_blank" rel="noopener">&#x2197; Source Document</a>`
      : ""}
  </div>

  <div class="accordion-panel" id="${panelId}">
    <p class="panel-label" style="margin-top:0">REST API Endpoint</p>
    <div class="endpoint-list">
      <div class="endpoint-item">
        <span class="method-badge method-get">GET</span>
        <span class="endpoint-url">${apiBase}/api/datasets/${escapeHtml(d.dataset_id)}</span>
        <button class="copy-btn" onclick="copyText('${escapeAttr(apiBase)}/api/datasets/${escapeAttr(d.dataset_id)}', this)">Copy</button>
      </div>
    </div>
  </div>
</article>`;
}

function togglePanel(panelId, btn) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const isOpen = panel.classList.toggle("open");
  btn.textContent = isOpen ? "✕ Close" : "{} API";
}

function downloadDataset(datasetId) {
  window.open(`/api/datasets/${encodeURIComponent(datasetId)}/download`, "_blank", "noopener");
}

function downloadDocument(datasetId) {
  window.open(`/api/datasets/${encodeURIComponent(datasetId)}/document`, "_blank", "noopener");
}

function showMcpModal() {
  const url = `${window.location.origin}/mcp`;
  document.getElementById("mcpUrlText").textContent = url;
  document.getElementById("cliText").textContent = `claude mcp add --transport http des-catalog ${url}`;
  document.getElementById("settingsText").textContent =
    `{\n  "mcpServers": {\n    "des-catalog": {\n      "type": "http",\n      "url": "${url}"\n    }\n  }\n}`;
  document.getElementById("mcpModal").classList.remove("hidden");
}

function hideMcpModal(event) {
  if (!event || event.target === document.getElementById("mcpModal")) {
    document.getElementById("mcpModal").classList.add("hidden");
  }
}

function copyMcpUrl() {
  copyBlock("mcpUrlText", document.querySelector("#mcpUrlBlock .copy-btn"));
}

function copyBlock(elementId, btn) {
  const text = document.getElementById(elementId)?.textContent?.trim() || "";
  navigator.clipboard.writeText(text).then(() => {
    if (!btn) return;
    const orig = btn.textContent;
    btn.textContent = "Copied!";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = orig; btn.classList.remove("copied"); }, 2000);
  });
}

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "Copied!";
    btn.classList.add("copied");
    setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 2000);
  });
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// expose for inline onclick handlers
window.loadDatasets      = loadDatasets;
window.downloadDataset   = downloadDataset;
window.downloadDocument  = downloadDocument;
window.togglePanel       = togglePanel;
window.showMcpModal      = showMcpModal;
window.hideMcpModal      = hideMcpModal;
window.copyMcpUrl        = copyMcpUrl;
window.copyBlock         = copyBlock;
window.copyText          = copyText;
