(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const langSelect = $("languageSelect");
  const question = $("question");

  if (!langSelect) return;

  const hints = new Set([
    "aap","ap","ka","ki","ke","kya","kaise","kyun","kyu","mera","meri","mere",
    "mann","man","dil","bhagwan","bhagwaan","naam","jap","krodh","gussa","bhakti",
    "satsang","karma","karm","mujhe","mujh","hum","hume","hame","nahi","nahin",
    "hai","hain","ho","karu","karun","kare","karen","chahiye","prem","radha",
    "krishna","maharaj","ji"
  ]);

  const C = {
    hi: {
      newChat: "नई चैट", recent: "हाल की चैट", searchChats: "चैट खोजें",
      askPlaceholder: "सत्संग से कुछ भी पूछें…", ask: "पूछें", signIn: "साइन इन",
      guest: "अतिथि", guestSaved: "चैट इस डिवाइस पर सेव हैं",
      disclaimer: "AI से गलती हो सकती है। महत्वपूर्ण संदर्भ मूल सत्संग में सत्यापित करें।",
      welcomeTitle: "आज आप क्या समझना चाहेंगे?",
      welcomeBody: "आपका प्रश्न भजन मार्ग के उपलब्ध सत्संगों में खोजा जाता है। सीधी शिक्षा तभी दिखाई जाती है जब उपलब्ध स्रोत उसका समर्थन करें। AI द्वारा तैयार व्याख्या अलग से दिखाई जाती है।",
      recentEmpty: "आपकी हाल की चैट यहाँ दिखेंगी।", noMatch: "कोई मिलती-जुलती चैट नहीं मिली।",
      sources: "मूल सत्संग स्रोत", sourceOne: "1 स्रोत", sourceMany: n => `${n} स्रोत`,
      helpful: "👍 सहायक", notHelpful: "👎 सहायक नहीं", why: "ये स्रोत क्यों:",
      direct: "सीधा सत्संग प्रमाण", related: "संबंधित शिक्षा", none: "पर्याप्त स्रोत प्रमाण नहीं",
      sourceOnly: "स्रोत मिला · साफ उत्तर-अंश उपलब्ध नहीं",
      answerLanguage: "उत्तर भाषा", searchTitle: "सभी उपलब्ध सत्संगों में खोज रहे हैं",
      authTitle: "साइन इन", google: "G  Google से जारी रखें", create: "अकाउंट बनाएँ",
      forgot: "पासवर्ड भूल गए?", guestContinue: "अतिथि के रूप में जारी रखें",
      profile: "प्रोफ़ाइल और पसंद", save: "सेव करें", logout: "लॉग आउट",
      feedbackTitle: "क्या गलत था?", sendFeedback: "फीडबैक भेजें",
      resetTitle: "नया पासवर्ड सेट करें", updatePassword: "पासवर्ड अपडेट करें",
      suggestions: ["बार-बार क्रोध आए तो क्या करें?","भगवान पर विश्वास कैसे बढ़ाएं?","मन शांत कैसे करें?","नाम जप में मन भटके तो क्या करें?"]
    },
    hinglish: {
      newChat: "Nayi chat", recent: "Recent chats", searchChats: "Chats search karein",
      askPlaceholder: "Satsang se kuch bhi poochhein…", ask: "Poochhein", signIn: "Sign in",
      guest: "Guest", guestSaved: "Chats is device par saved hain",
      disclaimer: "AI galti kar sakta hai. Important context original satsang mein verify karein.",
      welcomeTitle: "Aaj aap kya samajhna chahenge?",
      welcomeBody: "Aapka prashn Bhajan Marg ke uplabdh satsangon mein khoja jaata hai. Seedhi shiksha tabhi dikhayi jaati hai jab uplabdh srot uska samarthan karein. AI dwara taiyar vyakhya alag se dikhayi jaati hai.",
      recentEmpty: "Aapki recent chats yahan dikhenge.", noMatch: "Matching chats nahi mili.",
      sources: "Original satsang sources", sourceOne: "1 source", sourceMany: n => `${n} sources`,
      helpful: "👍 Helpful", notHelpful: "👎 Not helpful", why: "Ye sources kyun:",
      direct: "Direct satsang evidence", related: "Related teaching", none: "Enough source evidence nahi",
      sourceOnly: "Source mila · clean answer span available nahi",
      answerLanguage: "Answer language", searchTitle: "Sabhi uplabdh satsangon mein khoj rahe hain",
      authTitle: "Sign in", google: "G  Google se continue karein", create: "Account banayein",
      forgot: "Password bhool gaye?", guestContinue: "Guest ke roop mein continue karein",
      profile: "Profile & preferences", save: "Save", logout: "Log out",
      feedbackTitle: "Kya galat tha?", sendFeedback: "Feedback bhejein",
      resetTitle: "Naya password set karein", updatePassword: "Password update karein",
      suggestions: ["Bar-bar gussa aaye to kya karein?","Bhagwan par vishwas kaise badhayein?","Mann shaant kaise karein?","Naam-jap ke time mann bhatke to kya karein?"]
    },
    en: {
      newChat: "New chat", recent: "Recent chats", searchChats: "Search chats",
      askPlaceholder: "Ask anything from the satsang…", ask: "Ask", signIn: "Sign in",
      guest: "Guest", guestSaved: "Chats saved on this device",
      disclaimer: "AI may make mistakes. Verify important context in the original satsang.",
      welcomeTitle: "What would you like to understand today?",
      welcomeBody: "Your question is searched across the available Bhajan Marg satsangs. Direct teaching is shown only when the available sources support it. AI interpretation is shown separately.",
      recentEmpty: "Your recent chats will appear here.", noMatch: "No matching chats.",
      sources: "Original satsang sources", sourceOne: "1 source", sourceMany: n => `${n} sources`,
      helpful: "👍 Helpful", notHelpful: "👎 Not helpful", why: "Why these sources:",
      direct: "Direct satsang evidence", related: "Related teaching", none: "No sufficient source evidence",
      sourceOnly: "Source found · clean answer span unavailable",
      answerLanguage: "Answer language", searchTitle: "Searching all available satsangs",
      authTitle: "Sign in", google: "G  Continue with Google", create: "Create account",
      forgot: "Forgot password?", guestContinue: "Continue as guest",
      profile: "Profile & preferences", save: "Save", logout: "Log out",
      feedbackTitle: "What was wrong?", sendFeedback: "Send feedback",
      resetTitle: "Set a new password", updatePassword: "Update password",
      suggestions: ["What should I do when anger keeps returning?","How can I increase my faith in God?","How can I calm my mind?","How should I do naam-jap when my mind wanders?"]
    }
  };

  function detect(value) {
    value = String(value || "").trim();
    if (!value) return "hi";

    const chars = [...value];
    const dev = chars.filter(ch => /[\u0900-\u097F]/.test(ch)).length;
    const letters = chars.filter(ch => /[A-Za-z\u0900-\u097F]/.test(ch)).length;

    if (dev >= 3 && dev / Math.max(letters, 1) >= 0.20) return "hi";

    const words = new Set(
      (value.toLowerCase().match(/[a-z']+/g) || [])
        .map(x => x.replace(/[^a-z]/g, ""))
    );

    let count = 0;
    words.forEach(w => {
      if (hints.has(w)) count += 1;
    });

    return count >= 2 ? "hinglish" : "en";
  }

  function activeLang() {
    const selected = langSelect.value;
    if (selected !== "auto") return selected;
    return detect(question?.value || "");
  }

  function languageName(code) {
    if (code === "hi") return "हिन्दी";
    if (code === "hinglish") return "Hinglish";
    return "English";
  }

  function copy() {
    return C[activeLang()] || C.en;
  }

  function setText(selector, value) {
    const el = document.querySelector(selector);
    if (el && el.textContent !== value) el.textContent = value;
  }

  function updateAutoLabel() {
    const auto = langSelect.querySelector('option[value="auto"]');
    if (!auto) return;

    const detected = languageName(activeLang());

    // Only Auto gets a dynamic label. Explicit selections remain untouched.
    const label = langSelect.value === "auto" ? `Auto · ${detected}` : "Auto";

    if (auto.textContent !== label) {
      auto.textContent = label;
    }

    langSelect.title = `Answer language: ${
      langSelect.value === "auto"
        ? `Auto (${detected})`
        : languageName(langSelect.value)
    }`;
  }

  function translateDynamic() {
    const c = copy();

    document.querySelectorAll(".sources-title").forEach(el => {
      const spans = el.querySelectorAll("span");
      if (spans[0] && spans[0].textContent !== c.sources) {
        spans[0].textContent = c.sources;
      }

      if (spans[1]) {
        const n = Number((spans[1].textContent.match(/\d+/) || [0])[0]);
        const next = n === 1 ? c.sourceOne : c.sourceMany(n);
        if (spans[1].textContent !== next) spans[1].textContent = next;
      }
    });

    document.querySelectorAll('.feedback-btn[data-rating="1"]').forEach(el => {
      if (el.textContent !== c.helpful) el.textContent = c.helpful;
    });

    document.querySelectorAll('.feedback-btn[data-rating="-1"]').forEach(el => {
      if (el.textContent !== c.notHelpful) el.textContent = c.notHelpful;
    });

    document.querySelectorAll(".evidence-badge").forEach(el => {
      let next = c.none;

      if (el.classList.contains("direct")) next = c.direct;
      else if (el.classList.contains("related")) next = c.related;
      else if (
        el.textContent.toLowerCase().includes("clean answer") ||
        el.textContent.includes("उत्तर-अंश")
      ) next = c.sourceOnly;

      if (el.textContent !== next) el.textContent = next;
    });

    document.querySelectorAll(".response-lang-badge").forEach(el => {
      const code = el.dataset.responseLanguage;
      if (!code) return;
      const next = `${c.answerLanguage}: ${languageName(code)}`;
      if (el.textContent !== next) el.textContent = next;
    });
  }

  function translateWelcome() {
    const c = copy();
    setText("#welcome h1", c.welcomeTitle);
    setText("#welcome p", c.welcomeBody);

    [...document.querySelectorAll("#welcome .suggestion")].forEach((button, i) => {
      const next = c.suggestions[i];
      if (next && button.textContent !== next) button.textContent = next;
    });
  }

  let observer = null;
  let scheduled = false;
  let applying = false;

  function apply() {
    if (applying) return;
    applying = true;

    // Critical: do not let our own text replacements trigger another apply cycle.
    observer?.disconnect();

    try {
      const c = copy();
      const code = activeLang();

      document.documentElement.lang = code === "hi" ? "hi" : "en";
      document.documentElement.dataset.uiLanguage = code;

      updateAutoLabel();

      setText("#newChatBtn", "＋ " + c.newChat);
      setText(".side-label", c.recent);

      const search = $("chatSearch");
      if (search && search.placeholder !== c.searchChats) {
        search.placeholder = c.searchChats;
      }

      if (question && question.placeholder !== c.askPlaceholder) {
        question.placeholder = c.askPlaceholder;
      }

      setText("#askBtn", c.ask);

      const status = $("status");
      if (
        status &&
        !document.querySelector("#searchOverlay.show") &&
        status.textContent !== c.disclaimer
      ) {
        status.textContent = c.disclaimer;
      }

      const auth = $("authButton");
      if (
        auth &&
        ["Sign in", "साइन इन"].includes(auth.textContent.trim())
      ) {
        auth.textContent = c.signIn;
      }

      const profileName = $("profileName");
      if (
        profileName &&
        ["Guest", "अतिथि"].includes(profileName.textContent.trim())
      ) {
        profileName.textContent = c.guest;
      }

      const profileEmail = $("profileEmail");
      if (
        profileEmail &&
        /device|डिवाइस/i.test(profileEmail.textContent)
      ) {
        profileEmail.textContent = c.guestSaved;
      }

      setText("#searchOverlay .search-card > strong", c.searchTitle);
      setText("#authTitle", c.authTitle);
      setText("#googleSignIn", c.google);
      setText("#toggleAuthMode", c.create);
      setText("#forgotPassword", c.forgot);

      const guestBtn = [...document.querySelectorAll('#authModal .text-link')]
        .find(x => x.dataset.close === "authModal");

      if (guestBtn && guestBtn.textContent !== c.guestContinue) {
        guestBtn.textContent = c.guestContinue;
      }

      setText("#profileModal h2", c.profile);
      setText("#saveProfile", c.save);
      setText("#logoutBtn", c.logout);
      setText("#feedbackModal h2", c.feedbackTitle);
      setText("#submitFeedback", c.sendFeedback);
      setText("#resetModal h2", c.resetTitle);
      setText("#saveNewPassword", c.updatePassword);

      translateWelcome();
      translateDynamic();
    } finally {
      applying = false;
      observer?.observe(document.body, {
        childList: true,
        subtree: true
      });
    }
  }

  function scheduleApply() {
    if (scheduled) return;
    scheduled = true;

    requestAnimationFrame(() => {
      scheduled = false;
      apply();
    });
  }

  // The main app owns the actual selected value/persistence.
  // This layer only updates visible text immediately.
  langSelect.addEventListener("change", () => {
    apply();
  });

  question?.addEventListener("input", () => {
    if (langSelect.value === "auto") {
      scheduleApply();
    }
  });

  observer = new MutationObserver(mutations => {
    // Only react when the application adds/removes real elements
    // (new message, source card, modal content, etc.).
    const structuralChange = mutations.some(mutation =>
      [...mutation.addedNodes, ...mutation.removedNodes]
        .some(node => node.nodeType === Node.ELEMENT_NODE)
    );

    if (structuralChange) scheduleApply();
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true
  });

  window.BHAJAN_ACTIVE_LANGUAGE = activeLang;
  window.BHAJAN_APPLY_LANGUAGE = apply;

  apply();
})();
