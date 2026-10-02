const configured = typeof window.BHAJAN_API_BASE === "string";
const API_BASE = (window.BHAJAN_API_BASE || "").replace(/\/$/, "");
const chat = document.getElementById("chat"), form = document.getElementById("form");
const q = document.getElementById("q"), ask = document.getElementById("ask");
const newChat = document.getElementById("new-chat"), status = document.getElementById("status");
let conversationId = null, busy = false;
try { conversationId = localStorage.getItem("bm_conversation") || null; } catch (_) {}
function esc(s) {
  const d = document.createElement("div"); d.textContent = String(s ?? ""); return d.innerHTML;
}
function badge(data) {
  if (data.answer_status === "source_only") return "Sources found — answer excerpt unavailable";
  if (data.evidence_level === "direct") return "Direct corpus evidence";
  if (data.evidence_level === "related") return "Related teaching — not a direct answer";
  return "No sufficient Bhajan Marg citation found";
}
function addUser(text) {
  const item = document.createElement("div"); item.className = "msg user";
  item.textContent = text; chat.appendChild(item); return item;
}
function addAI(data) {
  const cards = (data.sources || []).map((s, i) => {
    let url = "";
    try { const parsed = new URL(s.answer_url || s.url); if (parsed.protocol === "https:" &&
      ["youtube.com", "www.youtube.com", "youtu.be"].includes(parsed.hostname)) url = parsed.href;
    } catch (_) {}
    const title = `स्रोत ${i + 1}: ${s.title || "सत्संग"}`;
    return `<div class="source"><div>${url ? `<a target="_blank" rel="noopener noreferrer" href="${esc(url)}">▶ ${esc(title)}</a>` : esc(title)}</div><div class="small">${s.answer_start ? `Answer starts ${esc(s.answer_start)} · ` : ""}${esc(s.start)}–${esc(s.end)} · relevance ${esc(s.relevance)}</div><div class="excerpt">“${esc(s.transcript_excerpt)}”</div><div class="small">Transcript-derived excerpt; auto-captions may contain recognition errors.</div></div>`;
  }).join("");
  chat.insertAdjacentHTML("beforeend", `<div class="msg ai"><div class="badge">${esc(badge(data))}</div><div>${esc(data.answer)}</div>${cards}</div>`);
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}
newChat.addEventListener("click", () => {
  if (busy) return;
  conversationId = null;
  try { localStorage.removeItem("bm_conversation"); } catch (_) {}
  chat.replaceChildren(); q.value = ""; status.textContent = "नई बातचीत शुरू करें।"; q.focus();
});
form.addEventListener("submit", async (event) => {
  event.preventDefault(); const text = q.value.trim();
  if (!text || busy) return;
  if (!configured || API_BASE.includes("REPLACE-ME")) {
    status.textContent = "Backend URL is not configured in web/config.js"; return;
  }
  busy = true; ask.disabled = true; newChat.disabled = true;
  const bubble = addUser(text); q.value = "";
  status.textContent = "सत्संग संदर्भ खोज रहे हैं… पहली बार थोड़ा अधिक समय लग सकता है।";
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 240000);
  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST", signal: controller.signal, headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text, conversation_id: conversationId }),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const trace = data?.error?.request_id || response.headers.get("X-Request-ID");
      throw new Error((data?.error?.message || `Service error (${response.status})`) +
        (trace ? ` · reference: ${trace}` : ""));
    }
    if (!data || typeof data.answer !== "string" || !data.conversation_id) {
      throw new Error("Service returned an incomplete answer.");
    }
    conversationId = data.conversation_id;
    try { localStorage.setItem("bm_conversation", conversationId); } catch (_) {}
    addAI(data); status.textContent = `Search query: ${data.standalone_query}`;
  } catch (error) {
    bubble.classList.add("failed"); if (!q.value.trim()) q.value = text;
    const message = error.name === "AbortError" ? "उत्तर आने में बहुत समय लगा।" :
      error instanceof TypeError ? "सर्वर से संपर्क नहीं हो पाया।" : error.message;
    status.textContent = `${message} प्रश्न नीचे रखा है; दोबारा भेजने के लिए Ask दबाएं।`;
  } finally {
    clearTimeout(timer); busy = false; ask.disabled = false; newChat.disabled = false;
  }
});
