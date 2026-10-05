(() => {
  "use strict";

  const API_BASE = String(
    window.BHAJAN_API_BASE !== undefined
      ? window.BHAJAN_API_BASE
      : (location.hostname.includes("onrender.com") ? "" : "https://bhajan-marg-ai.onrender.com")
  ).replace(/\/$/, "");

  // V1 product data is owned by the FastAPI backend + PostgreSQL.
  // On Vercel the included rewrite keeps /api same-origin, which lets the
  // backend use an HttpOnly session cookie without exposing auth tokens to JS.
  async function api(path, { method = "GET", body = undefined, signal = undefined } = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      credentials: "include",
      signal,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data?.detail || data?.error?.message || `Request failed (${response.status})`;
      const error = new Error(typeof detail === "string" ? detail : "Request failed");
      error.status = response.status;
      throw error;
    }
    return data;
  }

  const $ = (id) => document.getElementById(id);
  const els = {
    sidebar: $("sidebar"),
    drawerBackdrop: $("drawerBackdrop"),
    mobileMenu: $("mobileMenu"),
    newChatBtn: $("newChatBtn"),
    chatSearch: $("chatSearch"),
    conversationList: $("conversationList"),
    contextTitle: $("contextTitle"),
    messages: $("messages"),
    messagesWrap: $("messagesWrap"),
    chatForm: $("chatForm"),
    question: $("question"),
    askBtn: $("askBtn"),
    status: $("status"),
    languageSelect: $("languageSelect"),
    themeToggle: $("themeToggle"),
    authButton: $("authButton"),
    profileButton: $("profileButton"),
    profileAvatar: $("profileAvatar"),
    profileName: $("profileName"),
    profileEmail: $("profileEmail"),
    searchOverlay: $("searchOverlay"),
    searchTime: $("searchTime"),
    searchStage: $("searchStage"),
    searchJapName: $("searchJapName"),
    overlayCount: $("overlayCount"),
    authModal: $("authModal"),
    authTitle: $("authTitle"),
    authName: $("authName"),
    authEmail: $("authEmail"),
    authPassword: $("authPassword"),
    nameField: $("nameField"),
    emailAuthSubmit: $("emailAuthSubmit"),
    toggleAuthMode: $("toggleAuthMode"),
    forgotPassword: $("forgotPassword"),
    googleSignIn: $("googleSignIn"),
    authStatus: $("authStatus"),
    profileModal: $("profileModal"),
    profileNameInput: $("profileNameInput"),
    profileLanguage: $("profileLanguage"),
    profileTheme: $("profileTheme"),
    saveProfile: $("saveProfile"),
    logoutBtn: $("logoutBtn"),
    feedbackModal: $("feedbackModal"),
    feedbackComment: $("feedbackComment"),
    feedbackVoiceBtn: $("feedbackVoiceBtn"),
    feedbackVoiceStatus: $("feedbackVoiceStatus"),
    submitFeedback: $("submitFeedback"),

    conversationModal: $("conversationModal"),
    conversationModalTitle: $("conversationModalTitle"),
    conversationTitleLabel: $("conversationTitleLabel"),
    conversationTitleInput: $("conversationTitleInput"),
    saveConversationTitle: $("saveConversationTitle"),
    deleteConversationButton: $("deleteConversationButton"),
    conversationActionStatus: $("conversationActionStatus"),

    resetModal: $("resetModal"),
    newPassword: $("newPassword"),
    saveNewPassword: $("saveNewPassword"),
    toast: $("toast"),
    japNameSelect: $("japNameSelect"),
    japAdd: $("japAdd"),
    japLabel: $("japLabel"),
    japCount: $("japCount"),
    customJapRow: $("customJapRow"),
    customJapName: $("customJapName"),
    saveCustomJap: $("saveCustomJap"),
    mala: $("mala"),
  };

  const state = {
    session: null,
    user: null,
    profile: null,
    conversations: [],
    activeConversationId: null,
    activeConversationTitle: "New chat",
    messages: [],
    authMode: "signin",
    busy: false,
    feedbackTarget: null,
    conversationActionId: null,
    conversationDeleteArmed: false,
    theme: localStorage.getItem("bm_theme") || "system",
    language: localStorage.getItem("bm_language") || "auto",
    guestId: localStorage.getItem("bm_guest_id") || crypto.randomUUID(),
    selectedJapName: localStorage.getItem("bm_jap_name") || "राधा",
    japCount: 0,
    searchTimers: [],
    sourceLocalizationCache: new Map(),
    voiceTranscript: "",
    voiceRecognition: null,
  };
  localStorage.setItem("bm_guest_id", state.guestId);

  const SEARCH_STAGES = {
    hi: [
      "संबंधित वचन खोज रहे हैं…",
      "स्रोतों की प्रासंगिकता जाँच रहे हैं…",
      "सीधे उत्तर का अंश चुन रहे हैं…",
      "उत्तर को स्रोतों से मिला रहे हैं…",
    ],
    hinglish: [
      "Sambandhit vachan khoj rahe hain…",
      "Sroton ki prasangikta jaanch rahe hain…",
      "Seedhe uttar ka ansh chun rahe hain…",
      "Uttar ko sroton se mila rahe hain…",
    ],
    en: [
      "Finding related teachings…",
      "Checking source relevance…",
      "Selecting the direct answer span…",
      "Grounding the answer in the sources…",
    ],
  };

  function resolvedUiLanguage() {
    const live = window.BHAJAN_ACTIVE_LANGUAGE?.();
    if (["hi", "hinglish", "en"].includes(live)) return live;
    if (["hi", "hinglish", "en"].includes(state.language)) return state.language;

    const value = safeText(els.question?.value).trim();
    if (/[ऀ-ॿ]/.test(value)) return "hi";

    const lower = value.toLowerCase();
    const hinglishHints = [
      "kya", "kaise", "kyu", "kyun", "mann", "man", "bhagwan",
      "naam", "jap", "gussa", "bhakti", "mujhe", "nahi", "hai", "karu",
    ];
    if (hinglishHints.filter((word) => lower.includes(word)).length >= 2) {
      return "hinglish";
    }
    return "en";
  }

  function searchStatusText() {
    const lang = resolvedUiLanguage();
    if (lang === "hi") return "सभी उपलब्ध सत्संगों में खोज रहे हैं…";
    if (lang === "hinglish") return "Sabhi uplabdh satsangon mein khoj rahe hain…";
    return "Searching all available satsangs…";
  }

  function answerStatusText(data) {
    const lang = resolvedUiLanguage();
    const count = data.sources?.length || 0;

    if (data.evidence_level === "none") {
      if (lang === "hi") return "पर्याप्त सीधा स्रोत नहीं मिला।";
      if (lang === "hinglish") return "Paryapt seedha srot nahi mila.";
      return "No sufficient direct source found.";
    }

    if (lang === "hi") return `${count} स्रोतों के आधार पर उत्तर।`;
    if (lang === "hinglish") return `${count} srot ke aadhar par uttar.`;
    return `Answer grounded with ${count} source${count === 1 ? "" : "s"}.`;
  }

  function conversationUiText(key) {
    const lang = resolvedUiLanguage();
    const copy = {
      hi: {
        options: "चैट विकल्प",
        name: "चैट का नाम",
        save: "नाम सहेजें",
        delete: "चैट हटाएँ",
        deletePermanent: "हाँ, चैट हमेशा के लिए हटाएँ",
        confirmDelete: "यह चैट और इसके सभी संदेश हटा दिए जाएँगे। पुष्टि के लिए नीचे दिए गए लाल बटन को दोबारा दबाएँ।",
        renamed: "चैट का नाम बदल दिया गया",
        deleted: "चैट हटा दी गई",
        emptyName: "चैट का नाम लिखें",
      },
      hinglish: {
        options: "Chat ke vikalp",
        name: "Chat ka naam",
        save: "Naam save karein",
        delete: "Chat hataayein",
        deletePermanent: "Haan, chat hamesha ke liye hataayein",
        confirmDelete: "Yeh chat aur iske saare sandesh hata diye jayenge. Pushti ke liye neeche laal button dobara dabayein.",
        renamed: "Chat ka naam badal diya gaya",
        deleted: "Chat hata di gayi",
        emptyName: "Chat ka naam likhein",
      },
      en: {
        options: "Chat options",
        name: "Chat name",
        save: "Save name",
        delete: "Delete chat",
        deletePermanent: "Yes, delete chat permanently",
        confirmDelete: "This chat and all of its messages will be deleted. Press the red button again to confirm.",
        renamed: "Chat renamed",
        deleted: "Chat deleted",
        emptyName: "Enter a chat name",
      },
    };
    return (copy[lang] || copy.en)[key];
  }

  function safeText(value) {
    return String(value ?? "");
  }

  function esc(value) {
    return safeText(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function showToast(message) {
    els.toast.textContent = message;
    els.toast.classList.add("show");
    setTimeout(() => els.toast.classList.remove("show"), 2400);
  }

  function openModal(el) {
    el?.classList.add("show");
  }

  function closeModal(el) {
    el?.classList.remove("show");
  }

  function closeSidebar() {
    els.sidebar.classList.remove("open");
    els.drawerBackdrop.classList.remove("show");
  }

  function openSidebar() {
    els.sidebar.classList.add("open");
    els.drawerBackdrop.classList.add("show");
  }

  function applyTheme(theme = state.theme) {
    state.theme = theme || "system";
    localStorage.setItem("bm_theme", state.theme);

    const resolved = state.theme === "system"
      ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : state.theme;

    document.documentElement.dataset.theme = resolved;
    els.themeToggle.textContent = resolved === "dark" ? "☀" : "☾";
  }

  function cycleTheme() {
    const resolved = document.documentElement.dataset.theme;
    const next = resolved === "dark" ? "light" : "dark";
    applyTheme(next);
    if (state.user) {
      updateProfileFields({ theme: next }, false);
    }
    track("theme_changed", { theme: next });
  }

  function setLanguage(value, { persist = true } = {}) {
    state.language = ["auto", "hi", "hinglish", "en"].includes(value) ? value : "auto";
    els.languageSelect.value = state.language;
    if (persist) localStorage.setItem("bm_language", state.language);

    if (state.user && persist) {
      updateProfileFields({ preferred_language: state.language }, false);
    }
    if (state.activeConversationId && state.user && persist) {
      api(`/api/conversations/${encodeURIComponent(state.activeConversationId)}`, {
        method: "PATCH",
        body: { preferred_language: state.language },
      }).catch(() => {});
    }

    // Existing source cards are presentation-layer objects. Changing the
    // language should update their displayed caption and YouTube caption
    // preference immediately without rerunning retrieval.
    queueMicrotask(() => refreshSourceLanguages());
  }

  function autoSize() {
    els.question.style.height = "auto";
    els.question.style.height = Math.min(els.question.scrollHeight, 150) + "px";
  }

  function scrollBottom(behavior = "smooth") {
    requestAnimationFrame(() => {
      window.scrollTo({ top: document.body.scrollHeight, behavior });
    });
  }

  function uuidOrNull(value) {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value || "")
      ? value
      : null;
  }

  function guestStore() {
    try {
      const parsed = JSON.parse(localStorage.getItem("bm_guest_conversations_v1") || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function saveGuestStore(conversations) {
    localStorage.setItem("bm_guest_conversations_v1", JSON.stringify(conversations.slice(0, 50)));
  }

  function guestConversation(id) {
    return guestStore().find((item) => item.id === id) || null;
  }

  function persistGuestConversation(conversation) {
    const all = guestStore().filter((item) => item.id !== conversation.id);
    all.unshift(conversation);
    saveGuestStore(all);
  }

  function guestNewConversation() {
    const id = crypto.randomUUID();
    const conversation = {
      id,
      title: "New chat",
      preferred_language: state.language,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      last_message_at: new Date().toISOString(),
      messages: [],
    };
    persistGuestConversation(conversation);
    return conversation;
  }

  function guestDeleteConversation(id) {
    saveGuestStore(guestStore().filter((item) => item.id !== id));
  }

  function guestRenameConversation(id, title) {
    const all = guestStore();
    const item = all.find((x) => x.id === id);
    if (!item) return;
    item.title = title;
    item.updated_at = new Date().toISOString();
    saveGuestStore(all);
  }

  function guestSaveMessage(message) {
    const conv = guestConversation(state.activeConversationId) || guestNewConversation();
    conv.messages = Array.isArray(conv.messages) ? conv.messages : [];
    conv.messages.push(message);
    conv.messages = conv.messages.slice(-80);
    conv.updated_at = new Date().toISOString();
    conv.last_message_at = conv.updated_at;
    persistGuestConversation(conv);
  }

  function authAvailable() {
    return true;
  }

  function displayNameFromUser(user) {
    return state.profile?.name || user?.name || user?.email?.split("@")[0] || "User";
  }

  function avatarInitial(name) {
    return (safeText(name).trim()[0] || "अ").toUpperCase();
  }

  function renderAccount() {
    if (state.user) {
      const name = displayNameFromUser(state.user);
      const avatar = state.profile?.avatar_url || state.user.avatar_url;
      els.profileName.textContent = name;
      els.profileEmail.textContent = state.user.email || "Signed in";
      els.authButton.textContent = name.split(" ")[0] || "Profile";
      els.profileButton.setAttribute(
        "aria-label",
        "Open profile and account settings"
      );
      if (avatar) {
        els.profileAvatar.innerHTML = `<img src="${esc(avatar)}" alt="" style="width:100%;height:100%;object-fit:cover">`;
      } else {
        els.profileAvatar.textContent = avatarInitial(name);
      }
    } else {
      els.profileName.textContent = "Sign in";
      els.profileEmail.textContent = "Save & sync your conversations";
      els.authButton.textContent = "Sign in";
      els.profileAvatar.textContent = "अ";
      els.profileButton.setAttribute(
        "aria-label",
        "Sign in or create account"
      );
    }
  }

  async function loadProfile() {
    if (!state.user) return;
    try {
      const data = await api("/api/auth/me");
      state.user = data.user || state.user;
      state.profile = state.user;
    } catch (error) {
      console.warn("profile load", error);
      return;
    }
    if (state.profile?.preferred_language) {
      setLanguage(state.profile.preferred_language, { persist: true });
    }
    if (state.profile?.theme) {
      state.theme = state.profile.theme;
      applyTheme(state.theme);
    }
    renderAccount();
  }

  async function updateProfileFields(fields, notify = true) {
    if (!state.user) return;
    try {
      const data = await api("/api/profile", { method: "PATCH", body: fields });
      state.user = data.user || state.user;
      state.profile = state.user;
      renderAccount();
      if (notify) showToast("Profile saved");
    } catch (error) {
      if (notify) showToast(error.message || "Profile could not be saved");
      console.warn(error);
    }
  }

  async function initAuth() {
    const params = new URLSearchParams(location.search);
    if (params.get("reset_token")) {
      openModal(els.resetModal);
    }
    if (params.get("auth_error")) {
      showToast("Google sign-in could not be completed");
    }

    try {
      const data = await api("/api/auth/me");
      state.user = data.user || null;
      state.profile = state.user;
    } catch (error) {
      state.user = null;
      state.profile = null;
    }
    await onAuthChanged();
  }

  async function onAuthChanged() {
    renderAccount();

    if (state.user) {
      await loadProfile();
      await loadConversations();

      const remembered = localStorage.getItem("bm_cloud_conversation");
      const target = state.conversations.find((x) => x.id === remembered)?.id || state.conversations[0]?.id;
      if (target) {
        await selectConversation(target, { closeDrawer: false });
      } else {
        await createConversation({ select: true });
      }
      track("session_started", { authenticated: true });
    } else {
      await loadConversations();

      const remembered = localStorage.getItem("bm_guest_active_conversation");
      const target = state.conversations.find((x) => x.id === remembered)?.id || state.conversations[0]?.id;
      if (target) {
        await selectConversation(target, { closeDrawer: false });
      } else {
        await createConversation({ select: true });
      }
      track("session_started", { authenticated: false });
    }
  }

  async function signInGoogle() {
    els.authStatus.textContent = "Opening Google…";
    location.href = `${API_BASE}/api/auth/google/start`;
  }

  async function submitEmailAuth() {
    const email = els.authEmail.value.trim();
    const password = els.authPassword.value;
    const name = els.authName.value.trim();

    if (!email || !password) {
      els.authStatus.textContent = "Enter email and password";
      return;
    }
    if (state.authMode === "signup" && password.length < 8) {
      els.authStatus.textContent = "Use at least 8 characters";
      return;
    }

    els.emailAuthSubmit.disabled = true;
    els.authStatus.textContent = state.authMode === "signup" ? "Creating account…" : "Signing in…";

    try {
      const endpoint = state.authMode === "signup" ? "/api/auth/register" : "/api/auth/login";
      const payload = state.authMode === "signup" ? { email, password, name } : { email, password };
      const result = await api(endpoint, { method: "POST", body: payload });
      state.user = result.user || null;
      state.profile = state.user;
      closeModal(els.authModal);
      els.authStatus.textContent = "";
      await onAuthChanged();
    } catch (error) {
      els.authStatus.textContent = error.message || "Authentication failed";
    } finally {
      els.emailAuthSubmit.disabled = false;
    }
  }

  async function forgotPassword() {
    const email = els.authEmail.value.trim();
    if (!email) {
      els.authStatus.textContent = "Enter your email first";
      return;
    }
    try {
      const result = await api("/api/auth/forgot-password", { method: "POST", body: { email } });
      els.authStatus.textContent = result.message || "If that account exists, a reset link has been sent.";
      if (result.debug_reset_url) {
        console.info("Development reset URL:", result.debug_reset_url);
      }
    } catch (error) {
      els.authStatus.textContent = error.message || "Could not request password reset";
    }
  }

  async function updatePassword() {
    const password = els.newPassword.value;
    if (password.length < 8) return showToast("Use at least 8 characters");
    const token = new URLSearchParams(location.search).get("reset_token");
    if (!token) return showToast("Reset link is missing or expired");

    try {
      await api("/api/auth/reset-password", { method: "POST", body: { token, password } });
      els.newPassword.value = "";
      closeModal(els.resetModal);
      const url = new URL(location.href);
      url.searchParams.delete("reset_token");
      history.replaceState({}, "", url.pathname + url.search + url.hash);
      showToast("Password updated — sign in with your new password");
      openModal(els.authModal);
    } catch (error) {
      showToast(error.message || "Password could not be updated");
    }
  }

  async function logout() {
    try { await api("/api/auth/logout", { method: "POST", body: {} }); } catch {}
    state.session = null;
    state.user = null;
    state.profile = null;
    localStorage.removeItem("bm_cloud_conversation");
    closeModal(els.profileModal);
    await onAuthChanged();
  }

  async function loadConversations() {
    if (state.user) {
      try {
        state.conversations = await api("/api/conversations");
      } catch (error) {
        console.warn(error);
        state.conversations = [];
      }
    } else {
      state.conversations = guestStore()
        .sort((a, b) => safeText(b.last_message_at).localeCompare(safeText(a.last_message_at)))
        .slice(0, 50);
    }

    renderConversationList();
  }

  function renderConversationList(filter = "") {
    const needle = filter.trim().toLowerCase();
    const list = state.conversations.filter((c) => !needle || safeText(c.title).toLowerCase().includes(needle));

    if (!list.length) {
      els.conversationList.innerHTML = `<div class="empty-side">${needle ? "No matching chats." : "Your recent chats will appear here."}</div>`;
      return;
    }

    els.conversationList.innerHTML = "";

    for (const conv of list) {
      const item = document.createElement("div");
      item.className = "conversation-item" + (conv.id === state.activeConversationId ? " active" : "");
      item.dataset.id = conv.id;

      const title = document.createElement("button");
      title.type = "button";
      title.className = "conversation-title";
      title.style.cssText = "border:0;background:transparent;color:inherit;padding:0;text-align:left;cursor:pointer";
      title.textContent = conv.title || "New chat";
      title.addEventListener("click", () => selectConversation(conv.id));

      const menu = document.createElement("button");
      menu.type = "button";
      menu.className = "conversation-menu";
      menu.textContent = "•••";
      menu.title = "Conversation options";
      menu.addEventListener("click", (event) => {
        event.stopPropagation();
        conversationActions(conv);
      });

      item.append(title, menu);
      els.conversationList.appendChild(item);
    }
  }

  function resetConversationActionModal() {
    state.conversationDeleteArmed = false;
    els.conversationActionStatus.textContent = "";
    els.deleteConversationButton.classList.remove("armed");
    els.deleteConversationButton.textContent = conversationUiText("delete");
  }

  function conversationActions(conv) {
    state.conversationActionId = conv.id;
    resetConversationActionModal();

    els.conversationModalTitle.textContent = conversationUiText("options");
    els.conversationTitleLabel.textContent = conversationUiText("name");
    els.saveConversationTitle.textContent = conversationUiText("save");
    els.conversationTitleInput.value = conv.title || "";

    openModal(els.conversationModal);

    setTimeout(() => {
      els.conversationTitleInput.focus();
      els.conversationTitleInput.select();
    }, 0);
  }

  async function saveConversationRename() {
    const id = state.conversationActionId;
    if (!id) return;

    const title = els.conversationTitleInput.value.trim().slice(0, 120);
    if (!title) {
      els.conversationActionStatus.textContent = conversationUiText("emptyName");
      return;
    }

    await renameConversation(id, title);
    closeModal(els.conversationModal);
    state.conversationActionId = null;
    resetConversationActionModal();
    showToast(conversationUiText("renamed"));
  }

  async function handleConversationDelete() {
    const id = state.conversationActionId;
    if (!id) return;

    if (!state.conversationDeleteArmed) {
      state.conversationDeleteArmed = true;
      els.conversationActionStatus.textContent = conversationUiText("confirmDelete");
      els.deleteConversationButton.textContent = conversationUiText("deletePermanent");
      els.deleteConversationButton.classList.add("armed");
      return;
    }

    await deleteConversation(id);
    closeModal(els.conversationModal);
    state.conversationActionId = null;
    resetConversationActionModal();
    showToast(conversationUiText("deleted"));
  }

  async function createConversation({ select = true } = {}) {
    let conv;

    if (state.user) {
      try {
        conv = await api("/api/conversations", {
          method: "POST",
          body: { title: "New chat", preferred_language: state.language },
        });
      } catch (error) {
        console.warn(error);
        showToast("Could not create cloud chat");
        return null;
      }
    } else {
      conv = guestNewConversation();
    }

    state.conversations.unshift(conv);
    renderConversationList(els.chatSearch.value);
    track("conversation_created", {});
    if (select) await selectConversation(conv.id);
    return conv;
  }

  async function renameConversation(id, title) {
    if (state.user) {
      try {
        await api(`/api/conversations/${encodeURIComponent(id)}`, { method: "PATCH", body: { title } });
      } catch (error) {
        return showToast(error.message || "Rename failed");
      }
    } else {
      guestRenameConversation(id, title);
    }

    const conv = state.conversations.find((x) => x.id === id);
    if (conv) conv.title = title;
    if (id === state.activeConversationId) {
      state.activeConversationTitle = title;
      els.contextTitle.textContent = title;
    }
    renderConversationList(els.chatSearch.value);
  }

  async function deleteConversation(id) {
    if (state.user) {
      try {
        await api(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
      } catch (error) {
        return showToast(error.message || "Delete failed");
      }
    } else {
      guestDeleteConversation(id);
    }

    clearJapForConversation(id);
    state.conversations = state.conversations.filter((x) => x.id !== id);
    if (state.activeConversationId === id) {
      state.activeConversationId = null;
      state.messages = [];
      await createConversation({ select: true });
    } else {
      renderConversationList(els.chatSearch.value);
    }
  }

  async function selectConversation(id, { closeDrawer: shouldClose = true } = {}) {
    const conv = state.conversations.find((x) => x.id === id);
    if (!conv) return;

    state.activeConversationId = id;
    state.activeConversationTitle = conv.title || "New chat";
    els.contextTitle.textContent = state.activeConversationTitle;

    // Naam-jap belongs to this conversation. A new chat starts at 0.
    loadJapCount();

    if (state.user) {
      localStorage.setItem("bm_cloud_conversation", id);
      if (conv.preferred_language) setLanguage(conv.preferred_language, { persist: false });
    } else {
      localStorage.setItem("bm_guest_active_conversation", id);
      if (conv.preferred_language) setLanguage(conv.preferred_language, { persist: false });
    }

    if (state.user) {
      try {
        const data = await api(`/api/conversations/${encodeURIComponent(id)}/messages`);
        state.messages = (data || []).map(normalizeStoredMessage);
      } catch (error) {
        console.warn(error);
        state.messages = [];
      }
    } else {
      state.messages = (guestConversation(id)?.messages || []).map(normalizeStoredMessage);
    }

    renderMessages();
    renderConversationList(els.chatSearch.value);
    if (shouldClose) closeSidebar();

    const userTurns = state.messages.filter((m) => m.role === "user").length;
    if (userTurns > 0) track("conversation_returned", { user_turns: userTurns });
  }

  function normalizeStoredMessage(row) {
    const sources = row.message_sources || row.sources || row.data?.sources || [];
    return {
      id: row.id || row.local_id || crypto.randomUUID(),
      role: row.role,
      content: row.content || row.text || row.data?.answer || "",
      standalone_query: row.standalone_query || row.data?.standalone_query || "",
      evidence_level: row.evidence_level || row.data?.evidence_level || "",
      evidence_reason: row.evidence_reason || row.data?.evidence_reason || "",
      answer_status: row.answer_status || row.data?.answer_status || "",
      extraction_status: row.extraction_status || row.data?.extraction_status || "",
      interpretation_status: row.interpretation_status || row.data?.interpretation_status || "",
      response_language: row.response_language || row.data?.response_language || "",
      request_id: row.request_id || row.data?.request_id || "",
      quality_case_id: row.quality_case_id || row.data?.quality_case_id || "",
      elapsed_ms: row.elapsed_ms || row.data?.elapsed_ms || null,
      quotes: row.quotes || row.data?.quotes || [],
      claims: row.claims || row.data?.claims || [],
      sources: sources.sort?.((a, b) => (a.source_index || 0) - (b.source_index || 0)) || sources,
      created_at: row.created_at || new Date().toISOString(),
      question_snapshot: row.question_snapshot || "",
    };
  }

  function showWelcome() {
    els.messages.innerHTML = `
      <div class="welcome" id="welcome">
        <div class="welcome-mark">राधा</div>
        <h1>What would you like to understand today?</h1>
        <p>
          Your question is searched across the available Bhajan Marg satsangs.
          Direct teaching is shown only when the available sources support it. AI interpretation is shown separately.
        </p>
        <div class="suggestions">
          <button class="suggestion" type="button">बार-बार क्रोध आए तो क्या करें?</button>
          <button class="suggestion" type="button">भगवान पर विश्वास कैसे बढ़ाएं?</button>
          <button class="suggestion" type="button">Mann shaant kaise kare?</button>
          <button class="suggestion" type="button">How should I do naam-jap when my mind wanders?</button>
        </div>
      </div>
    `;
    els.messages.querySelectorAll(".suggestion").forEach((button) => {
      button.addEventListener("click", () => {
        els.question.value = button.textContent.trim();
        autoSize();
        els.question.focus();
      });
    });
  }

  function renderMessages() {
    els.messages.innerHTML = "";
    if (!state.messages.length) {
      showWelcome();
      return;
    }

    state.messages.forEach((message, index) => renderMessage(message, index));
    scrollBottom("auto");
  }

  function evidenceLabel(message) {
    if (message.answer_status === "source_only") return "Source found · clean answer span unavailable";
    if (message.evidence_level === "direct") return "Direct satsang evidence";
    if (message.evidence_level === "related") return "Related teaching";
    return "No sufficient source evidence";
  }

  function splitAnswer(answer) {
    const text = safeText(answer).trim();
    const headingSets = [
      ["🪷 सत्संग से सीधी शिक्षा", "Direct teaching from satsang", "direct"],
      ["💭 इस शिक्षा को गहराई से समझें", "Understand this teaching", "explanation"],
      ["🌱 सामान्य व्यवहारिक समझ", "Practical reflection", "practical"],
    ];

    const matches = [];
    for (const [hi, en, key] of headingSets) {
      for (const heading of [hi, en]) {
        const idx = text.indexOf(heading);
        if (idx >= 0) matches.push({ idx, heading, key });
      }
    }

    matches.sort((a, b) => a.idx - b.idx);
    const dedup = matches.filter((item, i) => i === 0 || item.idx !== matches[i - 1].idx);

    if (!dedup.length) {
      return [{ title: "Answer", body: text || "No answer available.", key: "answer" }];
    }

    const sections = [];
    const prefix = text.slice(0, dedup[0].idx).trim();
    if (prefix) sections.push({ title: "Answer", body: prefix, key: "answer" });

    dedup.forEach((item, i) => {
      const end = dedup[i + 1]?.idx ?? text.length;
      sections.push({
        title: item.heading,
        body: text.slice(item.idx + item.heading.length, end).trim(),
        key: item.key,
      });
    });
    return sections;
  }

  function sourceTargetLanguage(message) {
    if (["hi", "hinglish", "en"].includes(state.language)) return state.language;
    if (["hi", "hinglish", "en"].includes(message?.response_language)) return message.response_language;
    return resolvedUiLanguage();
  }

  function sourceUrl(source, targetLanguage = "hi") {
    const direct = source.answer_url || source.url || "";
    let url = null;

    try {
      url = new URL(direct);
      if (url.hostname === "youtu.be") {
        const vid = url.pathname.replace(/^\//, "") || source.video_id || "";
        url = new URL(`https://www.youtube.com/watch?v=${encodeURIComponent(vid)}`);
      }
      if (!["youtube.com", "www.youtube.com", "m.youtube.com"].includes(url.hostname)) {
        return "";
      }
    } catch {
      if (!source.video_id) return "";
      url = new URL(`https://www.youtube.com/watch?v=${encodeURIComponent(source.video_id)}`);
    }

    if (source.video_id) url.searchParams.set("v", source.video_id);

    const seconds = Math.floor(Number(
      source.answer_start_ms ?? source.timestamp_start_ms ?? source.start_ms ?? 0
    ) / 1000);
    if (seconds > 0) url.searchParams.set("t", `${seconds}s`);

    // English questions open the same canonical source with English captions
    // preferred. Hindi and Hinglish prefer Hindi captions. We never pretend
    // this changes Maharaj Ji's original audio.
    const captionLanguage = targetLanguage === "en" ? "en" : "hi";
    url.searchParams.set("hl", captionLanguage);
    url.searchParams.set("cc_lang_pref", captionLanguage);
    url.searchParams.set("cc_load_policy", "1");

    return url.href;
  }

  function sourceStart(source) {
    return source.answer_start || source.timestamp_start || source.start || msToClock(
      source.answer_start_ms ?? source.timestamp_start_ms ?? source.start_ms
    );
  }

  function sourceEnd(source) {
    return source.answer_end || source.timestamp_end || source.end || msToClock(
      source.answer_end_ms ?? source.timestamp_end_ms ?? source.end_ms
    );
  }

  function msToClock(ms) {
    const value = Number(ms);
    if (!Number.isFinite(value) || value < 0) return "";
    const total = Math.floor(value / 1000);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h
      ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
      : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function sourceLocalizationKey(source, targetLanguage) {
    return [
      source.video_id || "",
      source.answer_start_ms ?? source.timestamp_start_ms ?? source.start_ms ?? 0,
      targetLanguage,
      source.transcript_excerpt || source.text || "",
    ].join("|");
  }

  async function localizedSource(source, targetLanguage) {
    const exactExcerpt = source.transcript_excerpt || source.text || "";
    const exactTitle = source.video_title || source.title || "Bhajan Marg satsang";

    if (targetLanguage === "hi") {
      return {
        target_language: "hi",
        display_title: exactTitle,
        display_excerpt: exactExcerpt,
        display_url: sourceUrl(source, "hi"),
        display_label: "मूल हिन्दी स्रोत",
        is_translation: false,
        exact_transcript_excerpt: exactExcerpt,
      };
    }

    const key = sourceLocalizationKey(source, targetLanguage);
    if (state.sourceLocalizationCache.has(key)) {
      return state.sourceLocalizationCache.get(key);
    }

    const promise = api("/api/source-localize", {
      method: "POST",
      body: {
        target_language: targetLanguage,
        source,
      },
    }).catch((error) => {
      console.warn("source localization failed", error);
      return {
        target_language: targetLanguage,
        display_title: exactTitle,
        display_excerpt: exactExcerpt,
        display_url: sourceUrl(source, targetLanguage),
        display_label: targetLanguage === "en"
          ? "Original caption · English rendering unavailable"
          : "Original caption · Hinglish rendering unavailable",
        is_translation: false,
        exact_transcript_excerpt: exactExcerpt,
      };
    });

    state.sourceLocalizationCache.set(key, promise);
    return promise;
  }

  function applySourceCard(card, source, localized, targetLanguage) {
    const start = sourceStart(source) || "Source";
    const end = sourceEnd(source);
    const range = end && end !== start ? `${start} – ${end}` : start;
    const relevance = typeof source.relevance === "number"
      ? `${Math.round(source.relevance * 100)}% match`
      : "";

    const href = localized?.display_url || sourceUrl(source, targetLanguage);
    const title = localized?.display_title || source.video_title || source.title || "Bhajan Marg satsang";
    const excerpt = localized?.display_excerpt || source.transcript_excerpt || source.text || "";
    const exact = localized?.exact_transcript_excerpt || source.transcript_excerpt || source.text || "";
    const translated = Boolean(localized?.is_translation);

    if (card.tagName === "A" && href) {
      card.href = href;
      card.target = "_blank";
      card.rel = "noopener noreferrer";
    }

    const cta = targetLanguage === "en"
      ? `Open video with English captions from ${start} →`
      : targetLanguage === "hinglish"
        ? `Hindi video · ${start} se dekhein →`
        : `${start} से हिन्दी स्रोत देखें →`;

    card.innerHTML = `
      <div class="source-top">
        <span class="source-time">▶ ${esc(range)}</span>
        <span class="source-relevance">${esc(relevance)}</span>
      </div>
      <div class="source-title">${esc(title)}</div>
      ${excerpt ? `<div class="source-excerpt">“${esc(excerpt)}”</div>` : ""}
      ${localized?.display_label ? `<div class="source-localization-label">${esc(localized.display_label)}</div>` : ""}
      ${translated && exact ? `
        <div class="source-original">
          <div class="source-original-label">Original Hindi transcript</div>
          <div class="source-original-text">“${esc(exact)}”</div>
        </div>
      ` : ""}
      <div class="source-cta">${href ? esc(cta) : "Source timestamp unavailable"}</div>
    `;
  }

  async function localizeSourceCard(card, source, message) {
    const targetLanguage = sourceTargetLanguage(message);
    card.dataset.sourceLanguage = targetLanguage;

    // Change the link immediately; text localization may take a moment.
    const immediate = {
      display_url: sourceUrl(source, targetLanguage),
      display_title: source.video_title || source.title || "Bhajan Marg satsang",
      display_excerpt: source.transcript_excerpt || source.text || "",
      display_label: targetLanguage === "hi" ? "मूल हिन्दी स्रोत" : "Localizing source caption…",
      is_translation: false,
      exact_transcript_excerpt: source.transcript_excerpt || source.text || "",
    };
    applySourceCard(card, source, immediate, targetLanguage);

    const localized = await localizedSource(source, targetLanguage);
    if (card.dataset.sourceLanguage !== targetLanguage) return;
    applySourceCard(card, source, localized, targetLanguage);
  }

  function renderSource(source, index, message) {
    const card = document.createElement("a");
    card.className = "source-card";
    card.dataset.sourceIndex = String(index);
    card.__source = source;
    card.__message = message;
    localizeSourceCard(card, source, message);
    return card;
  }

  function refreshSourceLanguages() {
    document.querySelectorAll(".source-card").forEach((card) => {
      if (card.__source && card.__message) {
        localizeSourceCard(card, card.__source, card.__message);
      }
    });
  }

  function renderMessage(message, index) {
    const row = document.createElement("div");
    row.className = `message ${message.role === "user" ? "user" : "assistant"}`;
    row.dataset.messageId = message.id || "";

    if (message.role === "assistant") {
      const avatar = document.createElement("div");
      avatar.className = "avatar";
      avatar.textContent = "र";
      row.appendChild(avatar);
    }

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    if (message.role === "user") {
      bubble.textContent = message.content;
    } else {
      const meta = document.createElement("div");
      meta.className = "answer-meta";
      meta.innerHTML = `
        <span class="evidence-badge ${esc(message.evidence_level || "none")}">${esc(evidenceLabel(message))}</span>
        ${message.standalone_query ? `<span class="query-label" title="${esc(message.standalone_query)}">${esc(message.standalone_query)}</span>` : ""}
      `;
      if (["hi", "hinglish", "en"].includes(message.response_language)) {
        const languageBadge = document.createElement("span");
        languageBadge.className = "query-label response-lang-badge";
        languageBadge.dataset.responseLanguage = message.response_language;
        languageBadge.textContent = `Answer language: ${message.response_language === "hi" ? "हिन्दी" : message.response_language === "hinglish" ? "Hinglish" : "English"}`;
        meta.appendChild(languageBadge);
      }
      bubble.appendChild(meta);

      splitAnswer(message.content).forEach((section) => {
        const box = document.createElement("section");
        box.className = "answer-section";
        box.innerHTML = `
          <div class="section-title">${esc(section.title)}</div>
          <div class="answer-text">${esc(section.body)}</div>
        `;
        bubble.appendChild(box);
      });

      if (message.evidence_reason) {
        const note = document.createElement("div");
        note.className = "answer-note";
        note.textContent = "Why these sources: " + message.evidence_reason;
        bubble.appendChild(note);
      }

      if (Array.isArray(message.sources) && message.sources.length) {
        const sources = document.createElement("div");
        sources.className = "sources";
        const title = document.createElement("div");
        title.className = "sources-title";
        title.innerHTML = `<span>Original satsang sources</span><span>${message.sources.length} source${message.sources.length > 1 ? "s" : ""}</span>`;
        const grid = document.createElement("div");
        grid.className = "source-grid";
        message.sources.forEach((source, sourceIndex) => grid.appendChild(renderSource(source, sourceIndex, message)));
        sources.append(title, grid);
        bubble.appendChild(sources);
      }

      const feedback = document.createElement("div");
      feedback.className = "feedback-row";
      feedback.innerHTML = `
        <button class="feedback-btn" type="button" data-rating="1">👍 Helpful</button>
        <button class="feedback-btn" type="button" data-rating="-1">👎 Not helpful</button>
      `;
      feedback.querySelector('[data-rating="1"]').addEventListener("click", () => submitQuickFeedback(index, 1));
      feedback.querySelector('[data-rating="-1"]').addEventListener("click", () => openNegativeFeedback(index));
      bubble.appendChild(feedback);
    }

    row.appendChild(bubble);
    els.messages.appendChild(row);
  }

  function recentHistoryForApi() {
    return state.messages
      .filter((m) => ["user", "assistant"].includes(m.role) && m.content)
      .slice(-8)
      .map((m) => ({ role: m.role, content: m.content }));
  }

  async function persistUserMessage(question) {
    const message = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
      created_at: new Date().toISOString(),
    };

    if (state.user) {
      try {
        const data = await api(`/api/conversations/${encodeURIComponent(state.activeConversationId)}/messages`, {
          method: "POST",
          body: { role: "user", content: question },
        });
        return normalizeStoredMessage(data);
      } catch (error) {
        console.warn("persist user message", error);
        return message;
      }
    }

    guestSaveMessage(message);
    return message;
  }

  async function persistAssistantMessage(data, questionSnapshot) {
    const message = normalizeStoredMessage({
      id: crypto.randomUUID(),
      role: "assistant",
      content: data.answer || "",
      standalone_query: data.standalone_query || "",
      evidence_level: data.evidence_level || "none",
      evidence_reason: data.evidence_reason || "",
      answer_status: data.answer_status || "",
      extraction_status: data.extraction_status || "",
      interpretation_status: data.interpretation_status || "",
      response_language: data.response_language || "",
      request_id: data.request_id || "",
      quality_case_id: data.quality_case_id || "",
      elapsed_ms: data.elapsed_ms || null,
      quotes: data.quotes || [],
      claims: data.claims || [],
      sources: data.sources || [],
      question_snapshot: questionSnapshot,
      created_at: new Date().toISOString(),
    });

    if (state.user) {
      try {
        const saved = await api(`/api/conversations/${encodeURIComponent(state.activeConversationId)}/messages`, {
          method: "POST",
          body: {
            role: "assistant",
            content: message.content,
            standalone_query: message.standalone_query,
            evidence_level: message.evidence_level,
            evidence_reason: message.evidence_reason,
            answer_status: message.answer_status,
            extraction_status: message.extraction_status,
            interpretation_status: message.interpretation_status,
            response_language: message.response_language,
            request_id: message.request_id,
            elapsed_ms: message.elapsed_ms,
            quotes: message.quotes,
            claims: message.claims,
            question_snapshot: questionSnapshot,
            sources: message.sources || [],
          },
        });
        return normalizeStoredMessage(saved);
      } catch (error) {
        console.warn("persist assistant", error);
        return message;
      }
    }

    guestSaveMessage(message);
    return message;
  }

  async function maybeTitleConversation(question) {
    const conv = state.conversations.find((x) => x.id === state.activeConversationId);
    if (!conv || (conv.title && conv.title !== "New chat")) return;

    const title = question.replace(/\s+/g, " ").trim().slice(0, 58) || "New chat";
    await renameConversation(state.activeConversationId, title);
  }

  function beginSearch() {
    let stage = 0;
    const started = Date.now();
    const lang = resolvedUiLanguage();
    const stages = SEARCH_STAGES[lang] || SEARCH_STAGES.en;

    els.searchJapName.textContent = state.selectedJapName;
    els.searchStage.textContent = stages[0];
    els.searchTime.textContent =
      lang === "hi" ? "0 सेकंड" : (lang === "hinglish" ? "0 second" : "0s");
    els.searchOverlay.classList.add("show");

    state.searchTimers.push(setInterval(() => {
      const sec = Math.floor((Date.now() - started) / 1000);
      els.searchTime.textContent =
        lang === "hi"
          ? `${sec} सेकंड`
          : (lang === "hinglish" ? `${sec} second` : `${sec}s`);
    }, 500));

    state.searchTimers.push(setInterval(() => {
      stage = (stage + 1) % stages.length;
      els.searchStage.textContent = stages[stage];
    }, 4200));

    state.searchTimers.push(setInterval(() => incrementJap(1), 900));
  }

  function endSearch() {
    state.searchTimers.forEach(clearInterval);
    state.searchTimers = [];
    els.searchOverlay.classList.remove("show");
  }

  async function askApi(question, history) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 240000);

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        credentials: "include",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          conversation_id: state.activeConversationId,
          history,
          preferred_language: state.language,
        }),
      });

      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const ref = data?.error?.request_id || response.headers.get("X-Request-ID");
        const message = data?.error?.message || `Server error (${response.status})`;
        throw new Error(message + (ref ? ` · Reference ${ref}` : ""));
      }
      if (!data || typeof data.answer !== "string") {
        throw new Error("The server returned an incomplete answer.");
      }
      return data;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (state.busy) return;

    const question = els.question.value.trim();
    if (!question) return;

    if (!state.activeConversationId) {
      const conv = await createConversation({ select: false });
      if (!conv) return;
      state.activeConversationId = conv.id;
    }

    const history = recentHistoryForApi();
    state.busy = true;
    els.askBtn.disabled = true;
    els.newChatBtn.disabled = true;

    const userMessage = await persistUserMessage(question);
    state.messages.push(userMessage);
    if (state.messages.length === 1) els.messages.innerHTML = "";
    renderMessage(userMessage, state.messages.length - 1);
    els.question.value = "";
    autoSize();
    scrollBottom();
    beginSearch();
    els.status.textContent = searchStatusText();
    track("question_asked", { language: state.language, question: question.slice(0, 500), conversation_id: state.activeConversationId });

    try {
      const data = await askApi(question, history);
      const assistantMessage = await persistAssistantMessage(data, question);
      state.messages.push(assistantMessage);
      renderMessage(assistantMessage, state.messages.length - 1);

      await maybeTitleConversation(question);
      await loadConversations();
      renderConversationList(els.chatSearch.value);

      els.status.textContent = answerStatusText(data);

      track("answer_received", {
        language: data.response_language || state.language,
        evidence_level: data.evidence_level || "none",
        answer_status: data.answer_status || "",
        source_count: data.sources?.length || 0,
        elapsed_ms: data.elapsed_ms || null,
      });
    } catch (error) {
      userMessage.failed = true;
      const message = error?.name === "AbortError"
        ? "The answer took too long. Your question is kept below so you can retry."
        : (error?.message || "The answer could not be loaded.");

      if (!els.question.value.trim()) {
        els.question.value = question;
        autoSize();
      }
      els.status.textContent = message;
      showToast(message);
      track("answer_error", { error: message.slice(0, 160) });
    } finally {
      endSearch();
      state.busy = false;
      els.askBtn.disabled = false;
      els.newChatBtn.disabled = false;
      els.question.focus();
      scrollBottom();
    }
  }

  async function submitQuickFeedback(index, rating) {
    const assistant = state.messages[index];
    if (!assistant || assistant.role !== "assistant") return;

    const question = assistant.question_snapshot || previousUserQuestion(index);
    const payload = feedbackPayload(assistant, question, rating, rating === 1 ? "helpful" : null, null);

    if (rating === -1) {
      openNegativeFeedback(index);
      return;
    }

    const result = await sendFeedback(payload);
    markFeedbackButtons(index, rating);
    if (result.persisted) {
      showToast("Thanks — feedback saved");
    } else {
      showToast("Feedback saved on this device; it will retry automatically");
    }
  }

  function openNegativeFeedback(index) {
    state.feedbackTarget = index;
    els.feedbackComment.value = "";
    state.voiceTranscript = "";
    if (els.feedbackVoiceStatus) els.feedbackVoiceStatus.textContent = "";
    document.querySelectorAll('input[name="feedbackReason"]').forEach((x) => { x.checked = false; });
    openModal(els.feedbackModal);
  }

  function previousUserQuestion(index) {
    for (let i = index - 1; i >= 0; i--) {
      if (state.messages[i]?.role === "user") return state.messages[i].content;
    }
    return "";
  }

  function feedbackPayload(assistant, question, rating, reason, comment) {
    return {
      user_id: state.user?.id || null,
      guest_id: state.user ? null : state.guestId,
      conversation_id: uuidOrNull(state.activeConversationId),
      message_id: state.user ? uuidOrNull(assistant.id) : null,
      request_id: assistant.request_id || null,
      question: question || "",
      answer: assistant.content || "",
      retrieved_sources: assistant.sources || [],
      rating,
      reason,
      comment,
      voice_transcript: state.voiceTranscript || null,
      client_metadata: {
        response_language: assistant.response_language || "",
        evidence_level: assistant.evidence_level || "",
        answer_status: assistant.answer_status || "",
        quality_case_id: assistant.quality_case_id || null,
        browser_language: navigator.language || "",
      },
    };
  }

  function queueFeedback(payload) {
    const local = JSON.parse(localStorage.getItem("bm_local_feedback") || "[]");
    const queued = {
      ...payload,
      queue_id: payload.queue_id || crypto.randomUUID(),
      created_at: payload.created_at || new Date().toISOString(),
    };
    local.push(queued);
    localStorage.setItem("bm_local_feedback", JSON.stringify(local.slice(-500)));
    return queued;
  }

  async function sendFeedback(payload, { queueOnFailure = true } = {}) {
    try {
      const result = await api("/api/feedback", {
        method: "POST",
        body: {
          guest_id: state.user ? null : (payload.guest_id || state.guestId),
          conversation_id: uuidOrNull(payload.conversation_id),
          message_id: uuidOrNull(payload.message_id),
          request_id: payload.request_id || null,
          question: payload.question || "",
          answer: payload.answer || "",
          retrieved_sources: payload.retrieved_sources || [],
          rating: payload.rating,
          reason: payload.reason || null,
          comment: payload.comment || null,
          voice_transcript: payload.voice_transcript || null,
          client_metadata: payload.client_metadata || {},
        },
      });
      track("feedback_submitted", {
        rating: payload.rating,
        reason: payload.reason || "",
        feedback_id: result?.id || null,
      });
      return { persisted: true, id: result?.id || null };
    } catch (error) {
      console.warn(error);
      if (queueOnFailure) queueFeedback(payload);
      return { persisted: false, error };
    }
  }

  async function flushFeedbackQueue() {
    let queue = [];
    try {
      queue = JSON.parse(localStorage.getItem("bm_local_feedback") || "[]");
    } catch {
      queue = [];
    }
    if (!Array.isArray(queue) || !queue.length) return;

    const remaining = [];
    for (const payload of queue) {
      const result = await sendFeedback(payload, { queueOnFailure: false });
      if (!result.persisted) remaining.push(payload);
    }
    localStorage.setItem("bm_local_feedback", JSON.stringify(remaining.slice(-500)));
    if (!remaining.length) showToast("Saved feedback synced");
  }

  async function submitDetailedFeedback() {
    const index = state.feedbackTarget;
    const assistant = state.messages[index];
    if (!assistant) return;

    const reason = document.querySelector('input[name="feedbackReason"]:checked')?.value || "other";
    const question = assistant.question_snapshot || previousUserQuestion(index);
    const payload = feedbackPayload(
      assistant,
      question,
      -1,
      reason,
      els.feedbackComment.value.trim() || null
    );

    const result = await sendFeedback(payload);
    closeModal(els.feedbackModal);
    markFeedbackButtons(index, -1);
    if (result.persisted) {
      showToast("Thanks — feedback saved for review");
    } else {
      showToast("Feedback saved on this device; it will retry automatically");
    }
  }

  function startVoiceFeedback() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      showToast("Voice feedback is not supported in this browser");
      return;
    }

    if (state.voiceRecognition) {
      try { state.voiceRecognition.stop(); } catch {}
      return;
    }

    const recognition = new Recognition();
    recognition.lang = sourceTargetLanguage(state.messages[state.feedbackTarget]) === "hi"
      ? "hi-IN"
      : sourceTargetLanguage(state.messages[state.feedbackTarget]) === "en"
        ? "en-IN"
        : "hi-IN";
    recognition.interimResults = true;
    recognition.continuous = false;

    let finalText = state.voiceTranscript || "";
    state.voiceRecognition = recognition;
    if (els.feedbackVoiceStatus) els.feedbackVoiceStatus.textContent = "Listening…";
    if (els.feedbackVoiceBtn) els.feedbackVoiceBtn.textContent = "■ Stop";

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const text = event.results[i][0]?.transcript || "";
        if (event.results[i].isFinal) finalText = (finalText + " " + text).trim();
        else interim += text;
      }
      state.voiceTranscript = finalText;
      if (els.feedbackVoiceStatus) {
        els.feedbackVoiceStatus.textContent = (finalText || interim)
          ? `Voice: ${finalText || interim}`
          : "Listening…";
      }
    };

    recognition.onerror = (event) => {
      if (els.feedbackVoiceStatus) {
        els.feedbackVoiceStatus.textContent = `Voice error: ${event.error || "unknown"}`;
      }
    };

    recognition.onend = () => {
      state.voiceRecognition = null;
      if (els.feedbackVoiceBtn) els.feedbackVoiceBtn.textContent = "🎙 Explain by voice";
      if (els.feedbackVoiceStatus && state.voiceTranscript) {
        els.feedbackVoiceStatus.textContent = "Voice feedback captured";
      }
    };

    recognition.start();
  }

  function markFeedbackButtons(index, rating) {
    const assistantMessages = [...els.messages.querySelectorAll(".message.assistant")];
    const assistantIndex = state.messages.slice(0, index + 1).filter((x) => x.role === "assistant").length - 1;
    const row = assistantMessages[assistantIndex];
    row?.querySelectorAll(".feedback-btn").forEach((button) => {
      button.classList.toggle("selected", Number(button.dataset.rating) === rating);
    });
  }

  async function track(eventName, properties = {}) {
    const event = {
      guest_id: state.user ? null : state.guestId,
      conversation_id: uuidOrNull(state.activeConversationId),
      event_name: eventName,
      properties,
    };

    // Fire and forget; analytics should never block chat.
    api("/api/analytics", { method: "POST", body: event }).catch(() => {
      const local = JSON.parse(localStorage.getItem("bm_local_analytics") || "[]");
      local.push({ ...event, created_at: new Date().toISOString() });
      localStorage.setItem("bm_local_analytics", JSON.stringify(local.slice(-400)));
    });
  }

  function buildMala() {
    els.mala.innerHTML = "";
    for (let i = 0; i < 108; i++) {
      const bead = document.createElement("span");
      bead.className = "bead";
      els.mala.appendChild(bead);
    }
  }

  function japKey(
    name = state.selectedJapName,
    conversationId = state.activeConversationId
  ) {
    const chat = conversationId || "no-chat";
    return (
      "bm_jap_chat_" +
      encodeURIComponent(chat) +
      "_" +
      encodeURIComponent(name)
    );
  }

  function clearJapForConversation(conversationId) {
    if (!conversationId) return;

    const prefix = "bm_jap_chat_" + encodeURIComponent(conversationId) + "_";
    const remove = [];

    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (key?.startsWith(prefix)) remove.push(key);
    }

    remove.forEach((key) => localStorage.removeItem(key));
  }

  function loadJapCount() {
    state.japCount =
      Number.parseInt(localStorage.getItem(japKey()) || "0", 10) || 0;
    renderJap();
  }

  function setJapName(name) {
    const clean = safeText(name).trim();
    if (!clean) return;

    state.selectedJapName = clean;
    localStorage.setItem("bm_jap_name", clean);

    const builtIn = [...els.japNameSelect.options].some((option) => option.value === clean && option.value !== "__custom__");
    if (builtIn) {
      els.japNameSelect.value = clean;
      els.customJapRow.classList.remove("show");
    } else {
      els.japNameSelect.value = "__custom__";
      els.customJapName.value = clean;
      els.customJapRow.classList.add("show");
    }

    els.japLabel.textContent = clean + " नाम जप";
    els.japAdd.textContent = "+1";
    els.searchJapName.textContent = clean;
    loadJapCount();
  }

  function incrementJap(amount = 1) {
    state.japCount += amount;
    localStorage.setItem(japKey(), String(state.japCount));
    renderJap();
  }

  function renderJap() {
    els.japCount.textContent = state.japCount.toLocaleString("en-IN");
    els.overlayCount.textContent = state.japCount.toLocaleString("en-IN");
    const exactMala = state.japCount > 0 && state.japCount % 108 === 0;
    const progress = exactMala ? 108 : state.japCount % 108;
    els.mala.querySelectorAll(".bead").forEach((bead, i) => {
      bead.classList.toggle("active", i < progress);
    });
  }

  function bindEvents() {
    els.chatForm.addEventListener("submit", onSubmit);
    els.question.addEventListener("input", autoSize);
    els.question.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        els.chatForm.requestSubmit();
      }
    });

    els.newChatBtn.addEventListener("click", () => createConversation({ select: true }));
    els.chatSearch.addEventListener("input", () => renderConversationList(els.chatSearch.value));
    els.mobileMenu.addEventListener("click", openSidebar);
    els.drawerBackdrop.addEventListener("click", closeSidebar);
    els.themeToggle.addEventListener("click", cycleTheme);
    els.languageSelect.addEventListener("change", () => {
      setLanguage(els.languageSelect.value);
      track("language_changed", { language: state.language });
    });

    els.authButton.addEventListener("click", () => state.user ? openProfile() : openModal(els.authModal));
    els.profileButton.addEventListener("click", () => {
      closeSidebar();

      if (state.user) {
        openProfile();
      } else {
        openModal(els.authModal);
      }
    });
    els.googleSignIn.addEventListener("click", signInGoogle);
    els.emailAuthSubmit.addEventListener("click", submitEmailAuth);
    els.forgotPassword.addEventListener("click", forgotPassword);
    els.toggleAuthMode.addEventListener("click", () => {
      state.authMode = state.authMode === "signin" ? "signup" : "signin";
      els.authTitle.textContent = state.authMode === "signin" ? "Sign in" : "Create account";
      els.emailAuthSubmit.textContent = state.authMode === "signin" ? "Sign in" : "Create account";
      els.toggleAuthMode.textContent = state.authMode === "signin" ? "Create account" : "I already have an account";
      els.nameField.style.display = state.authMode === "signup" ? "block" : "none";
      els.forgotPassword.style.visibility = state.authMode === "signin" ? "visible" : "hidden";
      els.authStatus.textContent = "";
    });

    els.saveProfile.addEventListener("click", async () => {
      const fields = {
        name: els.profileNameInput.value.trim() || displayNameFromUser(state.user),
        preferred_language: els.profileLanguage.value,
        theme: els.profileTheme.value,
      };
      await updateProfileFields(fields, true);
      setLanguage(fields.preferred_language, { persist: true });
      applyTheme(fields.theme);
      closeModal(els.profileModal);
    });
    els.logoutBtn.addEventListener("click", logout);
    els.saveNewPassword.addEventListener("click", updatePassword);
    els.submitFeedback.addEventListener("click", submitDetailedFeedback);
    els.feedbackVoiceBtn?.addEventListener("click", startVoiceFeedback);
    window.addEventListener("online", () => flushFeedbackQueue());

    els.saveConversationTitle.addEventListener("click", saveConversationRename);
    els.deleteConversationButton.addEventListener("click", handleConversationDelete);
    els.conversationTitleInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveConversationRename();
      }
    });

    els.japNameSelect.addEventListener("change", () => {
      if (els.japNameSelect.value === "__custom__") {
        els.customJapRow.classList.add("show");
        els.customJapName.focus();
      } else {
        setJapName(els.japNameSelect.value);
      }
    });
    els.saveCustomJap.addEventListener("click", () => {
      const value = els.customJapName.value.trim();
      if (!value) return showToast("नाम लिखें");
      setJapName(value);
      showToast(value + " चुना गया");
    });
    els.customJapName.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        els.saveCustomJap.click();
      }
    });
    els.japAdd.addEventListener("click", () => {
      incrementJap(1);
      showToast(state.selectedJapName + " नाम जप +1");
    });

    document.querySelectorAll("[data-close]").forEach((button) => {
      button.addEventListener("click", () => {
        const modal = $(button.dataset.close);
        closeModal(modal);
        if (modal === els.conversationModal) {
          state.conversationActionId = null;
          resetConversationActionModal();
        }
      });
    });

    document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
      backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop) closeModal(backdrop);
      });
    });

    matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
      if (state.theme === "system") applyTheme("system");
    });
  }

  function openProfile() {
    if (!state.user) return openModal(els.authModal);
    els.profileNameInput.value = displayNameFromUser(state.user);
    els.profileLanguage.value = state.profile?.preferred_language || state.language || "auto";
    els.profileTheme.value = state.profile?.theme || state.theme || "system";
    openModal(els.profileModal);
  }

  async function boot() {
    applyTheme(state.theme);
    setLanguage(state.language, { persist: false });
    buildMala();
    setJapName(state.selectedJapName);
    bindEvents();
    autoSize();
    await initAuth();
    await flushFeedbackQueue();

  }

  boot().catch((error) => {
    console.error(error);
    showToast("The app could not finish loading");
  });
})();
