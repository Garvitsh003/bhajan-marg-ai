(() => {
  "use strict";

  const configured = typeof window.BHAJAN_API_BASE === "string";
  const API_BASE = (
    window.BHAJAN_API_BASE ||
    (location.hostname.includes("onrender.com") ? "" : "https://bhajan-marg-ai.onrender.com")
  ).replace(/\/$/, "");

  const NAMES = [
    "राधा","श्री राधा","राधे राधे","राधावल्लभ","श्री हरिवंश",
    "राम","श्री राम","सीता राम","हरि","कृष्ण","श्याम",
    "सांब सदाशिव","महादेव","शिव शिव","राधा नाम"
  ];

  const STAGES = [
    "सत्संग में खोज रहे हैं…",
    "संबंधित वचन चुन रहे हैं…",
    "स्रोत जाँच रहे हैं…",
    "उत्तर को स्रोत से मिला रहे हैं…"
  ];

  const $ = (id) => document.getElementById(id);

  const messages = $("messages");
  const form = $("chatForm");
  const q = $("question");
  const askBtn = $("askBtn");
  const status = $("status");
  const overlay = $("searchOverlay");
  const overlayCount = $("overlayCount");
  const searchTime = $("searchTime");
  const searchStage = $("searchStage");
  const searchJapName = $("searchJapName");
  const japCountEl = $("japCount");
  const japTotalEl = $("japTotal");
  const japRunning = $("japRunning");
  const newChatBtn = $("newChatBtn");
  const japAdd = $("japAdd");
  const japLabel = $("japLabel");
  const japNameSelect = $("japNameSelect");
  const customJapRow = $("customJapRow");
  const customJapName = $("customJapName");
  const saveCustomJap = $("saveCustomJap");
  const toast = $("toast");

  let busy = false;
  let conversationId = storageGet("bm_conversation") || "";
  let currentStorageKey = conversationId || "draft";
  let selectedJapName = storageGet("bm_jap_name") || "राधा";
  let conversationJap = readNumber(japConversationKey(currentStorageKey, selectedJapName));
  let totalJap = readNumber(japTotalKey(selectedJapName));

  let japTimer = null;
  let elapsedTimer = null;
  let stageTimer = null;
  let requestStarted = 0;
  let stageIndex = 0;

  function storageGet(key){
    try { return localStorage.getItem(key); } catch (_) { return null; }
  }

  function storageSet(key, value){
    try { localStorage.setItem(key, value); } catch (_) {}
  }

  function storageRemove(key){
    try { localStorage.removeItem(key); } catch (_) {}
  }

  function readNumber(key){
    const n = Number.parseInt(storageGet(key) || "0", 10);
    return Number.isFinite(n) ? n : 0;
  }

  function safeKey(value){
    return encodeURIComponent(String(value || "राधा").trim());
  }

  function japConversationKey(conversationKey, name){
    return "bm_jap_conversation_" + conversationKey + "_" + safeKey(name);
  }

  function japTotalKey(name){
    return "bm_jap_total_" + safeKey(name);
  }

  function historyKey(key = currentStorageKey){
    return "bm_history_" + key;
  }

  function readHistory(key = currentStorageKey){
    try{
      const raw = JSON.parse(storageGet(historyKey(key)) || "[]");
      return Array.isArray(raw) ? raw : [];
    }catch{
      return [];
    }
  }

  function writeHistory(history, key = currentStorageKey){
    storageSet(historyKey(key), JSON.stringify(history.slice(-20)));
  }

  function pushHistory(item){
    const history = readHistory();
    history.push(item);
    writeHistory(history);
  }

  function setJapName(name){
    const clean = String(name || "").trim();
    if(!clean) return;

    selectedJapName = clean;
    storageSet("bm_jap_name", selectedJapName);

    conversationJap = readNumber(japConversationKey(currentStorageKey, selectedJapName));
    totalJap = readNumber(japTotalKey(selectedJapName));

    japLabel.textContent = selectedJapName + " नाम जप";
    japAdd.textContent = selectedJapName + " +1";

    const builtIn = Array.from(japNameSelect.options).some(
      option => option.value === selectedJapName && option.value !== "__custom__"
    );

    if(builtIn){
      japNameSelect.value = selectedJapName;
      customJapRow.classList.remove("show");
    }else{
      japNameSelect.value = "__custom__";
      customJapName.value = selectedJapName;
      customJapRow.classList.add("show");
    }

    renderJap();
  }

  function saveJap(){
    storageSet(japTotalKey(selectedJapName), String(totalJap));
    storageSet(
      japConversationKey(currentStorageKey, selectedJapName),
      String(conversationJap)
    );
  }

  function renderJap(){
    japCountEl.textContent = conversationJap.toLocaleString("en-IN");
    japTotalEl.textContent = totalJap.toLocaleString("en-IN");
    overlayCount.textContent = conversationJap.toLocaleString("en-IN");

    const completed = conversationJap > 0 && conversationJap % 108 === 0;
    const progress = completed ? 108 : conversationJap % 108;

    document.querySelectorAll(".bead").forEach((bead, i) => {
      bead.classList.toggle("active", i < progress);
    });
  }

  function incrementJap(amount = 1){
    conversationJap += amount;
    totalJap += amount;
    saveJap();
    renderJap();
  }

  function migrateConversationStorage(newId){
    if(!newId || newId === currentStorageKey) return;

    const oldKey = currentStorageKey;
    const oldHistory = readHistory(oldKey);
    const newHistory = readHistory(newId);

    if(oldHistory.length && !newHistory.length){
      writeHistory(oldHistory, newId);
    }

    const newJapKey = japConversationKey(newId, selectedJapName);
    const existingNewCount = readNumber(newJapKey);
    storageSet(newJapKey, String(Math.max(existingNewCount, conversationJap)));

    if(oldKey === "draft"){
      storageRemove(historyKey("draft"));
      storageRemove(japConversationKey("draft", selectedJapName));
    }

    currentStorageKey = newId;
    conversationId = newId;
    storageSet("bm_conversation", newId);
  }

  function startJap(){
    stopJap();

    requestStarted = Date.now();
    stageIndex = 0;
    searchStage.textContent = STAGES[0];
    searchJapName.textContent = selectedJapName;
    overlay.classList.add("show");
    japRunning.classList.add("show");
    renderJap();

    japTimer = setInterval(() => incrementJap(1), 900);

    elapsedTimer = setInterval(() => {
      const sec = Math.floor((Date.now() - requestStarted) / 1000);
      searchTime.textContent = sec + " सेकंड";
    }, 500);

    stageTimer = setInterval(() => {
      stageIndex = (stageIndex + 1) % STAGES.length;
      searchStage.textContent = STAGES[stageIndex];
    }, 4300);
  }

  function stopJap(){
    clearInterval(japTimer);
    clearInterval(elapsedTimer);
    clearInterval(stageTimer);
    japTimer = elapsedTimer = stageTimer = null;
    overlay.classList.remove("show");
    japRunning.classList.remove("show");
  }

  function buildMala(){
    const mala = $("mala");
    mala.innerHTML = "";

    for(let i = 0; i < 108; i++){
      const bead = document.createElement("span");
      bead.className = "bead";
      mala.appendChild(bead);
    }
  }

  function buildAura(){
    const aura = $("aura");
    const count = window.innerWidth < 640 ? 24 : 43;

    for(let i = 0; i < count; i++){
      const node = document.createElement("span");
      node.className = "aura-name";
      node.textContent = NAMES[i % NAMES.length];
      node.style.left = ((i * 37 + 11) % 101) + "%";
      node.style.top = ((i * 23 + 7) % 103) + "%";
      node.style.fontSize = (16 + ((i * 7) % 25)) + "px";
      node.style.transform = "rotate(" + (-20 + ((i * 13) % 41)) + "deg)";
      node.style.animationDelay = "-" + ((i * 1.7) % 15) + "s";
      node.style.animationDuration = (15 + ((i * 2.3) % 13)) + "s";
      aura.appendChild(node);
    }
  }

  function esc(value){
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function makeMessage(role){
    const row = document.createElement("div");
    row.className = "message " + role;

    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = role === "user" ? "आप" : "राधा";

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    row.append(avatar, bubble);
    return {row, bubble};
  }

  function addUser(text, persist = true){
    hideWelcome();

    const {row, bubble} = makeMessage("user");
    bubble.textContent = text;
    messages.appendChild(row);

    if(persist) pushHistory({role:"user", text});
    scrollBottom();

    return row;
  }

  function evidenceLabel(data){
    if(data.answer_status === "source_only"){
      return "स्रोत मिले — साफ़ उत्तर-अंश नहीं मिला";
    }
    if(data.evidence_level === "direct") return "सीधा प्रमाण";
    if(data.evidence_level === "related") return "संबंधित शिक्षा";
    return "पर्याप्त प्रमाण नहीं";
  }

  function splitAnswer(answer){
    const text = String(answer || "").trim();
    const headings = [
      ["🪷 सत्संग से सीधी शिक्षा", "direct-teaching"],
      ["💭 इस शिक्षा को गहराई से समझें", ""],
      ["🌱 सामान्य व्यवहारिक समझ", ""]
    ];

    const found = [];
    for(const [title, cls] of headings){
      const idx = text.indexOf(title);
      if(idx >= 0) found.push({title, cls, idx});
    }
    found.sort((a,b) => a.idx - b.idx);

    if(!found.length){
      return [{
        title:"उत्तर",
        cls:"",
        body:text || "स्रोत मिले हैं, लेकिन साफ़ उत्तर का अंश नहीं मिल पाया।"
      }];
    }

    const sections = [];
    for(let i = 0; i < found.length; i++){
      const cur = found[i];
      const next = found[i + 1];
      const start = cur.idx + cur.title.length;
      const end = next ? next.idx : text.length;

      sections.push({
        title:cur.title,
        cls:cur.cls,
        body:text.slice(start, end).trim()
      });
    }

    const prefix = text.slice(0, found[0].idx).trim();
    if(prefix) sections.unshift({title:"उत्तर", cls:"", body:prefix});

    return sections;
  }

  function safeYoutubeUrl(value){
    if(!value) return "";

    try{
      const parsed = new URL(value);
      if(
        parsed.protocol === "https:" &&
        ["youtube.com", "www.youtube.com", "youtu.be"].includes(parsed.hostname)
      ){
        return parsed.href;
      }
    }catch(_){}

    return "";
  }

  function sourceCard(source){
    const link = document.createElement("a");
    link.className = "source-card";

    const safeUrl = safeYoutubeUrl(source.answer_url || source.url);
    if(safeUrl){
      link.href = safeUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }else{
      link.href = "#";
      link.addEventListener("click", event => event.preventDefault());
    }

    const rel = typeof source.relevance === "number"
      ? Math.round(source.relevance * 100) + "% मेल"
      : "Bhajan Marg";

    const shownStart = source.answer_start || source.start || "स्रोत";
    const shownEnd = source.answer_end || source.end || "";

    link.innerHTML = `
      <div class="source-top">
        <span class="source-time">${esc(shownStart)}</span>
        <span class="source-relevance">${esc(rel)}</span>
      </div>
      <div class="source-title">${esc(source.title || "Bhajan Marg सत्संग")}</div>
      <div class="source-excerpt">${esc(source.transcript_excerpt || source.text || "")}</div>
      <div class="answer-note">${
        shownEnd
          ? `${esc(shownStart)}–${esc(shownEnd)} · `
          : ""
      }यह अंश अपने-आप बने कैप्शन से है; इसमें गलती हो सकती है।</div>
    `;

    return link;
  }

  function addAI(data, persist = true){
    hideWelcome();

    const {row, bubble} = makeMessage("ai");
    const level = data.evidence_level || "none";
    const standalone = data.standalone_query || "";

    const meta = document.createElement("div");
    meta.className = "answer-meta";
    meta.innerHTML = `
      <span class="evidence-badge ${esc(level)}">${esc(evidenceLabel(data))}</span>
      <span class="query-label" title="${esc(standalone)}">${esc(standalone)}</span>
    `;

    const body = document.createElement("div");
    body.className = "answer-body";

    splitAnswer(data.answer || "").forEach(section => {
      const box = document.createElement("section");
      box.className = "answer-section " + section.cls;
      box.innerHTML = `
        <div class="section-title">${esc(section.title)}</div>
        <div class="answer-text">${esc(section.body)}</div>
      `;
      body.appendChild(box);
    });

    if(data.evidence_reason){
      const note = document.createElement("div");
      note.className = "answer-note";
      note.textContent = "स्रोत चुनने का कारण: " + data.evidence_reason;
      body.appendChild(note);
    }

    bubble.append(meta, body);

    if(Array.isArray(data.sources) && data.sources.length){
      const srcWrap = document.createElement("div");
      srcWrap.className = "sources";

      const title = document.createElement("div");
      title.className = "sources-title";
      title.innerHTML = `<span>मूल सत्संग स्रोत</span><span>${data.sources.length} स्रोत</span>`;

      const grid = document.createElement("div");
      grid.className = "source-grid";
      data.sources.forEach(source => grid.appendChild(sourceCard(source)));

      srcWrap.append(title, grid);
      bubble.appendChild(srcWrap);
    }

    messages.appendChild(row);

    if(persist){
      pushHistory({
        role:"ai",
        data:{
          answer:data.answer || "",
          answer_status:data.answer_status || "",
          evidence_level:level,
          evidence_reason:data.evidence_reason || "",
          standalone_query:standalone,
          sources:(data.sources || []).slice(0,3)
        }
      });
    }

    scrollBottom();
  }

  function showWelcome(){
    messages.innerHTML = `
      <div class="welcome" id="welcome">
        <div class="welcome-symbol">राधा</div>
        <h2>मन में जो है, पूछिए</h2>
        <p>
          आपका प्रश्न Bhajan Marg के उपलब्ध सत्संगों में खोजा जाएगा।
          साफ़ स्रोत मिलने पर वीडियो और समय के साथ दिखेगा।
        </p>
        <div class="suggestions">
          <button class="suggestion" type="button">बार-बार क्रोध आए तो क्या करें?</button>
          <button class="suggestion" type="button">भजन में मन नहीं लगता तो क्या करें?</button>
          <button class="suggestion" type="button">भगवान पर विश्वास कैसे बढ़ाएं?</button>
          <button class="suggestion" type="button">मृत्यु का डर कैसे दूर करें?</button>
        </div>
      </div>
    `;

    document.querySelectorAll(".suggestion").forEach(button => {
      button.addEventListener("click", () => {
        q.value = button.textContent.trim();
        q.focus();
        autoSize();
      });
    });
  }

  function hideWelcome(){
    const welcome = $("welcome");
    if(welcome) welcome.remove();
  }

  function restoreHistory(){
    const history = readHistory();

    if(!history.length){
      showWelcome();
      return;
    }

    messages.innerHTML = "";
    history.forEach(item => {
      if(item.role === "user") addUser(item.text || "", false);
      if(item.role === "ai") addAI(item.data || {}, false);
    });
  }

  function scrollBottom(){
    setTimeout(() => {
      window.scrollTo({top:document.body.scrollHeight, behavior:"smooth"});
    }, 40);
  }

  function showToast(message){
    toast.textContent = message;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 2600);
  }

  function autoSize(){
    q.style.height = "auto";
    q.style.height = Math.min(q.scrollHeight, 145) + "px";
  }

  async function askQuestion(text){
    if(!configured && !API_BASE && !location.hostname.includes("onrender.com")){
      throw new Error("Backend URL तय नहीं है।");
    }
    if(configured && API_BASE.includes("REPLACE-ME")){
      throw new Error("web/config.js में Backend URL तय नहीं है।");
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 240000);

    try{
      const response = await fetch(`${API_BASE}/api/chat`, {
        method:"POST",
        signal:controller.signal,
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          question:text,
          conversation_id:conversationId || null
        })
      });

      const data = await response.json().catch(() => null);

      if(!response.ok){
        const trace = data?.error?.request_id || response.headers.get("X-Request-ID");
        const base = data?.error?.message || `सर्वर त्रुटि (${response.status})`;
        throw new Error(base + (trace ? ` · संदर्भ: ${trace}` : ""));
      }

      if(!data || typeof data.answer !== "string" || !data.conversation_id){
        throw new Error("सर्वर से पूरा उत्तर नहीं मिला।");
      }

      return data;
    }finally{
      clearTimeout(timeout);
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();

    const text = q.value.trim();
    if(!text || busy) return;

    busy = true;
    askBtn.disabled = true;
    newChatBtn.disabled = true;

    const userRow = addUser(text);
    q.value = "";
    autoSize();

    status.textContent = "सत्संग में खोज रहे हैं… पहली बार थोड़ा अधिक समय लग सकता है।";
    startJap();

    try{
      const data = await askQuestion(text);

      if(data.conversation_id){
        migrateConversationStorage(data.conversation_id);
      }

      addAI(data);

      status.textContent = data.standalone_query
        ? "खोज: " + data.standalone_query
        : "उत्तर स्रोतों के साथ मिला";
    }catch(error){
      userRow.classList.add("failed");

      if(!q.value.trim()){
        q.value = text;
        autoSize();
      }

      const message = error?.name === "AbortError"
        ? "उत्तर आने में बहुत समय लगा।"
        : error instanceof TypeError
          ? "सर्वर से संपर्क नहीं हो पाया।"
          : (error?.message || "कुछ गड़बड़ हुई।");

      status.textContent = message + " प्रश्न नीचे रखा है; फिर से भेजने के लिए खोजें दबाएं।";
      showToast(message);
    }finally{
      stopJap();
      busy = false;
      askBtn.disabled = false;
      newChatBtn.disabled = false;
      q.focus();
    }
  });

  q.addEventListener("input", autoSize);

  q.addEventListener("keydown", event => {
    if(event.key === "Enter" && !event.shiftKey){
      event.preventDefault();
      form.requestSubmit();
    }
  });

  japAdd.addEventListener("click", () => {
    incrementJap(1);
    showToast(selectedJapName + " नाम जप +1");
  });

  newChatBtn.addEventListener("click", () => {
    if(busy) return;

    stopJap();

    conversationId = "";
    currentStorageKey = "draft";
    storageRemove("bm_conversation");
    storageRemove(historyKey("draft"));
    storageRemove(japConversationKey("draft", selectedJapName));

    conversationJap = 0;
    totalJap = readNumber(japTotalKey(selectedJapName));

    messages.innerHTML = "";
    showWelcome();
    renderJap();

    q.value = "";
    autoSize();
    status.textContent = "नई बातचीत शुरू करें।";
    q.focus();
  });

  japNameSelect.addEventListener("change", () => {
    if(japNameSelect.value === "__custom__"){
      customJapRow.classList.add("show");
      customJapName.focus();
      return;
    }

    customJapRow.classList.remove("show");
    setJapName(japNameSelect.value);
  });

  saveCustomJap.addEventListener("click", () => {
    const value = customJapName.value.trim();

    if(!value){
      showToast("नाम लिखें");
      customJapName.focus();
      return;
    }

    setJapName(value);
    showToast(value + " चुना गया");
  });

  customJapName.addEventListener("keydown", event => {
    if(event.key === "Enter"){
      event.preventDefault();
      saveCustomJap.click();
    }
  });

  buildAura();
  buildMala();
  restoreHistory();
  setJapName(selectedJapName);
  renderJap();
  autoSize();
})();
