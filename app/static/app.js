const ingestForm   = document.getElementById("ingestForm");
const extractBtn   = document.getElementById("extractBtn");
const extractStatus = document.getElementById("extractStatus");
const step1        = document.getElementById("step1");
const step2        = document.getElementById("step2");
const pushBtn      = document.getElementById("pushBtn");
const pushStatus   = document.getElementById("pushStatus");

// Holds the full extract response while the user reviews
let _extracted = null;

if (ingestForm) ingestForm.addEventListener("submit", onExtract);

// ── Step 1: Extract ──────────────────────────────────────────────────────────

async function onExtract(event) {
  event.preventDefault();

  extractStatus.style.display = "block";
  extractStatus.innerHTML = `<span class="muted">&#9679; Extracting text and generating AI summary…</span>`;
  extractBtn.disabled = true;
  extractBtn.textContent = "Extracting…";

  const formData = new FormData(ingestForm);

  const rawTags = String(formData.get("tags") || "[]");
  let parsedTags = [];
  try {
    parsedTags = JSON.parse(rawTags);
    if (!Array.isArray(parsedTags)) throw new Error("Tags must be a JSON array");
  } catch (err) {
    extractStatus.innerHTML = `<span style="color:#dc2626">&#x274C; Invalid tags JSON: ${escapeHtml(err.message)}</span>`;
    extractBtn.disabled = false;
    extractBtn.textContent = "Extract PDF";
    return;
  }
  formData.set("tags", JSON.stringify(parsedTags));

  const fileInput = ingestForm.querySelector("input[name='file']");
  if (!fileInput.files.length) formData.delete("file");

  try {
    const response = await fetch("/api/datasets/extract", { method: "POST", body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Extraction failed");

    _extracted = data;
    showPreview(data);
  } catch (err) {
    extractStatus.innerHTML = `<span style="color:#dc2626">&#x274C; ${escapeHtml(err.message)}</span>`;
  } finally {
    extractBtn.disabled = false;
    extractBtn.textContent = "Extract PDF";
  }
}

function showPreview(data) {
  // Switch to step 2
  step1.style.display = "none";
  step2.style.display = "block";
  pushStatus.style.display = "none";

  document.getElementById("previewTitle").textContent = data.title;

  document.getElementById("previewStats").innerHTML = `
    <div style="background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 12px">
      <div style="font-size:0.68rem;font-weight:800;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">Characters</div>
      <div style="font-weight:700;font-size:1.1rem">${(data.extracted_text_chars || 0).toLocaleString()}</div>
    </div>
    <div style="background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 12px">
      <div style="font-size:0.68rem;font-weight:800;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">Est. Vector Chunks</div>
      <div style="font-weight:700;font-size:1.1rem">${data.estimated_chunks || 0}</div>
    </div>
    <div style="background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 12px">
      <div style="font-size:0.68rem;font-weight:800;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">Category</div>
      <div style="font-weight:700;font-size:0.9rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(data.category || "N/A")}</div>
    </div>
  `;

  document.getElementById("previewSummary").textContent = data.summary || "No summary generated.";
  document.getElementById("previewText").textContent = (data.text_preview || "").slice(0, 1500);
}

function goBack() {
  _extracted = null;
  step2.style.display = "none";
  step1.style.display = "block";
  extractStatus.style.display = "none";
}

// ── Step 2: Push ─────────────────────────────────────────────────────────────

async function pushToCatalogue() {
  if (!_extracted) return;

  pushStatus.style.display = "block";
  pushStatus.innerHTML = `<span class="muted">&#9679; Saving to catalogue and vector database…</span>`;
  pushBtn.disabled = true;
  pushBtn.textContent = "Pushing…";

  try {
    const response = await fetch("/api/datasets/push", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_extracted),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Push failed");

    const d = data.dataset;
    pushStatus.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <span style="font-size:1.4rem">✅</span>
        <div style="flex:1">
          <div style="font-family:'Space Grotesk',sans-serif;font-weight:700">${escapeHtml(d.title)}</div>
          <div style="font-family:monospace;font-size:0.78rem;color:var(--ink-soft)">${escapeHtml(d.dataset_id)}</div>
        </div>
        <a class="btn btn-sm btn-primary" href="/catalogue" target="_blank" rel="noopener">Open Catalogue ↗</a>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px">
        <div style="background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 12px">
          <div style="font-size:0.68rem;font-weight:800;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">Vector Chunks Stored</div>
          <div style="font-weight:700;font-size:1.1rem">${data.vector_chunks}</div>
        </div>
        <div style="background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 12px">
          <div style="font-size:0.68rem;font-weight:800;color:var(--ink-soft);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px">Characters</div>
          <div style="font-weight:700;font-size:1.1rem">${(d.extracted_text_chars || 0).toLocaleString()}</div>
        </div>
      </div>
    `;

    // Disable push button and show ingest another link
    pushBtn.disabled = true;
    pushBtn.textContent = "Pushed ✓";

  } catch (err) {
    pushStatus.innerHTML = `<span style="color:#dc2626">&#x274C; ${escapeHtml(err.message)}</span>`;
    pushBtn.disabled = false;
    pushBtn.textContent = "Push to Catalogue";
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// expose for inline onclick handlers in index.html
window.goBack          = goBack;
window.pushToCatalogue = pushToCatalogue;
