(() => {
  "use strict";

  const API_BASE = String(
    window.BHAJAN_API_BASE !== undefined
      ? window.BHAJAN_API_BASE
      : (location.hostname.includes("onrender.com") ? "" : "https://bhajan-marg-ai.onrender.com")
  ).replace(/\/$/, "");

  const $ = (id) => document.getElementById(id);
  const state = {
    token: sessionStorage.getItem("bm_admin_token") || "",
    cases: [],
    active: null,
  };

  $("token").value = state.token;

  async function adminApi(path, { method = "GET", body } = {}) {
    const response = await fetch(API_BASE + path, {
      method,
      credentials: "include",
      headers: {
        "X-Admin-Token": state.token,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data?.detail || data?.error?.message || `Request failed (${response.status})`);
    }
    return data;
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function pill(text, cls = "") {
    return `<span class="pill ${cls}">${esc(text)}</span>`;
  }

  async function loadDashboard() {
    const d = await adminApi("/api/admin/mastery-dashboard");
    const metrics = [
      ["Cases", d.quality_cases],
      ["Needs review", d.needs_review],
      ["Resolved", d.resolved],
      ["Golden set", d.golden_cases],
      ["Helpful", d.helpful],
      ["Not helpful", d.not_helpful],
    ];
    $("metrics").innerHTML = metrics.map(([label, value]) => `
      <div class="card metric"><strong>${esc(value)}</strong><span class="muted">${esc(label)}</span></div>
    `).join("");
  }

  function queryString() {
    const p = new URLSearchParams();
    const fields = {
      status: $("status").value,
      rating: $("rating").value,
      language: $("language").value,
      failure_category: $("failure").value,
    };
    Object.entries(fields).forEach(([k, v]) => { if (v) p.set(k, v); });
    p.set("limit", "200");
    return p.toString();
  }

  async function loadCases() {
    state.cases = await adminApi("/api/admin/quality-cases?" + queryString());
    renderCases();
  }

  function renderCases() {
    const box = $("cases");
    if (!state.cases.length) {
      box.innerHTML = '<div class="muted">No matching cases.</div>';
      return;
    }

    box.innerHTML = state.cases.map((item) => {
      const bad = item.feedback_rating === -1 || item.review_status === "needs_review";
      const good = item.feedback_rating === 1;
      return `
        <div class="case ${state.active?.id === item.id ? "active" : ""}" data-id="${esc(item.id)}">
          <div class="q">${esc(item.question)}</div>
          <div>
            ${pill(item.review_status, bad ? "bad" : "")}
            ${item.feedback_rating ? pill(item.feedback_rating === 1 ? "👍 helpful" : "👎 not helpful", good ? "good" : "bad") : ""}
            ${item.response_language ? pill(item.response_language) : ""}
            ${item.failure_category ? pill(item.failure_category, "bad") : ""}
          </div>
          <div class="muted" style="margin-top:6px">${esc(item.feedback_reason || item.evidence_level || "")}</div>
        </div>
      `;
    }).join("");

    box.querySelectorAll(".case").forEach((el) => {
      el.addEventListener("click", () => openCase(el.dataset.id));
    });
  }

  function candidateHtml(c, i) {
    const score = c.rerank_score ?? c.fusion_score ?? "";
    return `
      <div class="candidate">
        <strong>#${i + 1} · ${esc(c.video_id || "")} · ${esc(c.title || "")}</strong>
        <div class="muted">score: ${esc(score)} · ${esc(c.content_type || "")}</div>
        <div style="margin-top:6px">${esc(String(c.text || "").slice(0, 900))}</div>
      </div>
    `;
  }

  async function openCase(id) {
    const c = await adminApi("/api/admin/quality-cases/" + encodeURIComponent(id));
    state.active = c;
    renderCases();

    const trace = c.retrieval_trace || {};
    const candidates = trace.top_candidates || [];
    const sources = c.sources_shown || [];

    $("detail").innerHTML = `
      <div class="section">
        <h2>Question</h2>
        <p>${esc(c.question)}</p>
        <div class="muted">Standalone: ${esc(c.standalone_query || "")}</div>
        <div style="margin-top:7px">
          ${pill(c.response_language || "unknown")}
          ${pill(c.evidence_level || "none")}
          ${pill(c.answer_status || "")}
        </div>
      </div>

      <div class="section">
        <h3>Answer</h3>
        <pre>${esc(c.answer || "")}</pre>
      </div>

      <div class="section">
        <h3>Sources shown</h3>
        <pre>${esc(JSON.stringify(sources, null, 2))}</pre>
      </div>

      <div class="section">
        <h3>Retrieval trace</h3>
        <div class="muted">Candidates: ${esc(trace.candidate_count || 0)} · Judge: ${esc(trace.judge_reason || "")}</div>
        ${candidates.slice(0, 20).map(candidateHtml).join("")}
      </div>

      <div class="section">
        <h3>User feedback</h3>
        <p>${c.feedback_rating === -1 ? "👎" : c.feedback_rating === 1 ? "👍" : "No feedback yet"} ${esc(c.feedback_reason || "")}</p>
        ${c.feedback_comment
          ? `<div class="muted">Written comment</div><pre>${esc(c.feedback_comment)}</pre>`
          : `<div class="muted">Written comment: none</div>`
        }

        ${c.voice_transcript
          ? `<div class="muted">Voice transcript</div><pre>${esc(c.voice_transcript)}</pre>`
          : `<div class="muted">Voice transcript: none captured</div>`
        }
      </div>

      <div class="section">
        <h3>Review</h3>
        <div class="row">
          <select id="reviewStatus">
            ${["unreviewed","needs_review","reviewed","resolved"].map(x => `<option ${c.review_status===x?"selected":""}>${x}</option>`).join("")}
          </select>
          <select id="failureCategory">
            <option value="">Unclassified</option>
            ${["corpus","transcript","chunking","query_understanding","retrieval","reranking","generation","citation","conversation_context","language","other"].map(x => `<option ${c.failure_category===x?"selected":""}>${x}</option>`).join("")}
          </select>
        </div>
        <textarea id="reviewNotes" placeholder="What went wrong / what was good / root cause">${esc(c.review_notes || "")}</textarea>
        <textarea id="expectedSources" placeholder='Expected sources JSON, e.g. [{"video_id":"...","note":"direct answer"}]'>${esc(JSON.stringify(c.expected_sources || [], null, 2))}</textarea>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button id="saveReview">Save review</button>
          <button class="secondary" id="addGolden">Add to Golden Set</button>
        </div>
      </div>

      <div class="section">
        <h3>Versions</h3>
        <pre>${esc(JSON.stringify(c.versions || {}, null, 2))}</pre>
      </div>
    `;

    $("saveReview").addEventListener("click", saveReview);
    $("addGolden").addEventListener("click", addGolden);
  }

  async function saveReview() {
    if (!state.active) return;
    let expected = [];
    try { expected = JSON.parse($("expectedSources").value || "[]"); }
    catch { alert("Expected sources must be valid JSON"); return; }

    await adminApi("/api/admin/quality-cases/" + state.active.id, {
      method: "PATCH",
      body: {
        review_status: $("reviewStatus").value,
        failure_category: $("failureCategory").value || null,
        review_notes: $("reviewNotes").value || null,
        expected_sources: expected,
      },
    });
    await refreshAll();
    await openCase(state.active.id);
  }

  async function addGolden() {
    if (!state.active) return;
    let expected = [];
    try { expected = JSON.parse($("expectedSources").value || "[]"); }
    catch { alert("Expected sources must be valid JSON"); return; }

    const topic = prompt("Expected topic/category (optional):", "") || null;
    const good = prompt("What must a good answer do? Separate points with |", "") || "";
    const bad = prompt("What behavior is unacceptable? Separate points with |", "") || "";

    await adminApi("/api/admin/quality-cases/" + state.active.id + "/golden", {
      method: "POST",
      body: {
        expected_topic: topic,
        expected_sources: expected,
        acceptable_answer: good ? good.split("|").map(x => x.trim()).filter(Boolean) : [],
        unacceptable_behavior: bad ? bad.split("|").map(x => x.trim()).filter(Boolean) : [],
        notes: $("reviewNotes").value || null,
      },
    });
    alert("Added to Golden Set");
    await refreshAll();
  }

  async function refreshAll() {
    await Promise.all([loadDashboard(), loadCases()]);
  }

  $("connect").addEventListener("click", async () => {
    state.token = $("token").value.trim();
    sessionStorage.setItem("bm_admin_token", state.token);
    try {
      await refreshAll();
    } catch (error) {
      alert(error.message);
    }
  });

  $("refresh").addEventListener("click", () => refreshAll().catch(e => alert(e.message)));
  ["status","rating","language","failure"].forEach(id => {
    $(id).addEventListener("change", () => loadCases().catch(e => alert(e.message)));
  });

  if (state.token) refreshAll().catch(() => {});
})();