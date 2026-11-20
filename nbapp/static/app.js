/* NeuroBridge web app — vanilla JS single-page app (no build step, so it runs in Colab).
   Structure: core helpers → shell & router → pages (individual, caregiver, shared) → boot.
   All text from the server or users is escaped by the `html` template tag. */
"use strict";

/* ============================================================ core helpers */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
const raw = (s) => new Raw(s);
const fmt = (v) => v instanceof Raw ? v.s : Array.isArray(v) ? v.map(fmt).join("") :
  (v === false || v === null || v === undefined) ? "" : esc(v);
const html = (strs, ...vals) => raw(strs.reduce((a, s, i) => a + s + (i < vals.length ? fmt(vals[i]) : ""), ""));

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return store._m[k] ?? null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { store._m[k] = v; } },
  del(k) { try { localStorage.removeItem(k); } catch { delete store._m[k]; } }, _m: {},
};

const S = { user: null, prefs: {}, status: null, token: store.get("nb_token"), unread: 0,
            seenNotif: Number(store.get("nb_seen_notif") || 0), people: null };

async function api(method, path, body) {
  const headers = { "Content-Type": "application/json" };
  if (S.token) headers.Authorization = "Bearer " + S.token;
  let res;
  try {
    res = await fetch("api/" + path.replace(/^\//, ""), { method, headers,
      body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw new Error("Can't reach NeuroBridge. Check your connection and try again.");
  }
  let data; try { data = await res.json(); } catch { data = { detail: res.statusText }; }
  if (res.status === 401 && S.token && !path.startsWith("auth/")) { signOutLocal(); throw new Error(data.detail || "Please sign in."); }
  if (!res.ok) {
    let d = data.detail;
    if (Array.isArray(d)) d = d.map((x) => x.msg).join("; ");
    if (d && typeof d === "object") d = d.message || JSON.stringify(d);
    const err = new Error(d || "Something went wrong (" + res.status + ")");
    err.status = res.status; err.data = data; throw err;
  }
  return data;
}
const GET = (p) => api("GET", p), POST = (p, b = {}) => api("POST", p, b), PUT = (p, b) => api("PUT", p, b),
  PATCH = (p, b = {}) => api("PATCH", p, b), DEL = (p, b) => api("DELETE", p, b);

function toast(msg, err = false) {
  const el = document.createElement("div");
  el.className = "toast" + (err ? " err" : ""); el.textContent = msg;
  $("#toast").appendChild(el);
  setTimeout(() => el.remove(), err ? 6000 : 3200);
}
const fail = (e) => toast(e.message || String(e), true);

function inlineMd(t) {
  return t.replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)\]]+)/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>');
}
function md(text) {
  const lines = esc(text || "").split("\n"); let out = "", i = 0;
  const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
  const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => inlineMd(c.trim()));
  while (i < lines.length) {
    const l = lines[i]; let m;
    if (isRow(l)) {
      const rows = []; while (i < lines.length && isRow(lines[i])) rows.push(lines[i++]);
      const sep = rows.length > 1 && /^\s*\|?\s*:?-{2,}/.test(rows[1]);
      const head = sep ? rows[0] : null, body = sep ? rows.slice(2) : rows;
      out += "<table>" + (head ? "<tr>" + cells(head).map((c) => `<th>${c}</th>`).join("") + "</tr>" : "") +
        body.map((r) => "<tr>" + cells(r).map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") + "</table>";
      continue;
    }
    if ((m = l.match(/^\s*(#{1,4})\s+(.*)$/))) { out += `<h4>${inlineMd(m[2])}</h4>`; i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) { out += "<hr>"; i++; continue; }
    if (/^\s*[-*•]\s+/.test(l)) { out += "<ul>"; while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) out += `<li>${inlineMd(lines[i++].replace(/^\s*[-*•]\s+/, ""))}</li>`; out += "</ul>"; continue; }
    if (/^\s*\d+[.)]\s+/.test(l)) { out += "<ol>"; while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) out += `<li>${inlineMd(lines[i++].replace(/^\s*\d+[.)]\s+/, ""))}</li>`; out += "</ol>"; continue; }
    if (!l.trim()) { i++; continue; }
    const para = []; while (i < lines.length && lines[i].trim() && !isRow(lines[i]) && !/^\s*(#{1,4}\s|[-*•]\s|\d+[.)]\s|-{3,})/.test(lines[i])) para.push(lines[i++]);
    out += `<p>${inlineMd(para.join("<br>"))}</p>`;
  }
  return raw(out);
}

const fmtDate = (s) => { if (!s) return ""; const d = new Date(s.length === 10 ? s + "T00:00" : s); return isNaN(d) ? s : d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }); };
const fmtTime = (s) => { if (!s || s.length < 16) return ""; const d = new Date(s); return isNaN(d) ? "" : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }); };
const fmtWhen = (s) => (fmtDate(s) + " " + fmtTime(s)).trim();
const today = () => new Date().toISOString().slice(0, 10);
const isInd = () => S.user && S.user.role === "individual";
const isCare = () => S.user && S.user.role === "caregiver";
const isAdmin = () => S.user && S.user.role === "admin";

function speak(text) {
  if (!("speechSynthesis" in window)) { toast("Text-to-speech isn't supported in this browser.", true); return; }
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/[#*_`|>]/g, " "));
  const langMap = { hi: "hi-IN", mr: "mr-IN", bn: "bn-IN", ta: "ta-IN", te: "te-IN", ml: "ml-IN", kn: "kn-IN", gu: "gu-IN", pa: "pa-IN", ur: "ur-IN", kok: "hi-IN" };
  u.lang = langMap[S.user?.language] || "en-IN"; u.rate = 0.92;
  speechSynthesis.speak(u);
}
function listen(onText) {
  const R = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!R) { toast("Speech-to-text isn't supported in this browser. Try Chrome or Edge.", true); return; }
  const r = new R(); r.lang = { hi: "hi-IN", mr: "mr-IN", ta: "ta-IN", te: "te-IN", bn: "bn-IN" }[S.user?.language] || "en-IN";
  r.interimResults = false; r.onresult = (e) => onText(e.results[0][0].transcript);
  r.onerror = (e) => toast("Couldn't hear that (" + e.error + ").", true);
  r.start(); toast("Listening…");
}

/* ------------------------------------------------------------ dialogs */
function dialog({ title, body, okText = "Save", cancelText = "Cancel", onOk, wide = false, danger = false }) {
  const d = document.createElement("dialog");
  if (wide) d.style.width = "min(760px,94vw)";
  d.innerHTML = html`<form method="dialog"><div class="dlg-body"><h2>${title}</h2>${body}</div>
    <div class="dlg-foot">${cancelText ? html`<button class="btn quiet" value="cancel" type="button" data-x>${cancelText}</button>` : ""}
    ${okText ? html`<button class="btn ${danger ? "danger" : "primary"}" value="ok">${okText}</button>` : ""}</div></form>`.s;
  document.body.appendChild(d);
  const close = () => { d.close(); d.remove(); };
  $("[data-x]", d)?.addEventListener("click", close);
  d.addEventListener("cancel", () => setTimeout(() => d.remove(), 0));
  $("form", d).addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!onOk) return close();
    const btn = $(".dlg-foot .btn:last-child", d); btn.disabled = true;
    try { const keep = await onOk(new FormData($("form", d)), d); if (keep !== true) close(); }
    catch (err) { fail(err); } finally { btn.disabled = false; }
  });
  d.showModal(); const f = $("input,textarea,select", d); if (f) f.focus();
  return d;
}
const confirmDlg = (title, text, okText = "Yes", danger = false) => new Promise((res) => {
  const d = dialog({ title, body: html`<p>${text}</p>`, okText, danger, onOk: () => res(true) });
  d.addEventListener("close", () => res(false));
});

/* ============================================================ preferences */
function applyPrefs() {
  const p = S.prefs || {}, r = document.documentElement;
  r.style.setProperty("--scale", p.font_scale || 1);
  r.dataset.dyslexia = p.dyslexia_font ? "1" : "0";
  r.dataset.contrast = p.high_contrast ? "high" : "normal";
  r.dataset.motion = p.reduced_motion ? "reduced" : "normal";
  r.dataset.lowstim = p.low_stimulation ? "1" : "0";
  r.dataset.theme = p.theme === "dark" ? "dark" : "light";
  window.NB_LANG = S.user?.language || "en";
  r.lang = window.NB_LANG === "kok" ? "kok" : window.NB_LANG;
  r.dir = (window.NB_RTL || []).includes(window.NB_LANG) ? "rtl" : "ltr";
}
async function savePrefs(changes, extra = {}) {
  const r = await PUT("me/settings", { prefs: changes, ...extra });
  S.prefs = r.prefs; S.user = r.user; applyPrefs(); return r;
}

/* ============================================================ navigation */
const NAV = {
  individual: [
    ["Today", [["home", "🏠", "My Day"], ["assistant", "✨", "Assistant"], ["tasks", "✅", "Tasks"], ["routines", "🔁", "Routines"]]],
    ["Support", [["checkin", "🌤", "Check-in"], ["sensory", "🎧", "Sensory toolkit"], ["communicate", "💬", "Communication"]]],
    ["Me", [["journal", "📓", "Journal"], ["blueprint", "🧭", "Support Blueprint"], ["goals", "🎯", "Goals"], ["learn", "📚", "Learn & life skills"]]],
    ["Connect", [["community", "🤝", "Community"], ["events", "📅", "Events & groups"], ["appointments", "🩺", "Providers & appointments"], ["circle", "🫶", "My circle"]]],
  ],
  caregiver: [
    ["Care", [["home", "🏠", "Dashboard"], ["assistant", "✨", "Care assistant"], ["calendar", "📆", "Care calendar"], ["carejournal", "📝", "Care journal"]]],
    ["Support", [["people", "🫶", "People I support"], ["coordination", "🧩", "Coordination"], ["requests", "🔔", "Support requests"]]],
    ["Learn & find", [["learn", "📚", "Learning hub"], ["appointments", "🩺", "Providers & appointments"], ["events", "📅", "Events & groups"]]],
    ["Me", [["community", "🤝", "Community"], ["wellbeing", "🌿", "Wellbeing"]]],
  ],
  admin: [
    ["Admin", [["home", "🛡", "Moderation"], ["directory", "🩺", "Provider directory"], ["events", "📅", "Events & groups"], ["community", "🤝", "Community"], ["assistant", "✨", "Assistant"]]],
  ],
};
const ROUTES = {};
const route = (name, fn) => (ROUTES[name] = fn);
let CURRENT = { name: null, cleanup: null };

function navHtml() {
  const groups = NAV[S.user.role] || [];
  const hide = (k) => S.user.is_minor && k === "appointments";
  return groups.map(([g, items]) => html`<div class="nav-group">${t(g)}</div><ul class="nav">
    ${items.filter(([k]) => !hide(k)).map(([k, ico, label]) => html`<li><a href="#/${k}" data-nav="${k}"><span class="ico" aria-hidden="true">${ico}</span>${t(label)}</a></li>`)}</ul>`)
    .concat([html`<div class="nav-group">${t("Settings")}</div><ul class="nav"><li><a href="#/settings" data-nav="settings"><span class="ico" aria-hidden="true">⚙️</span>${t("Settings")}</a></li></ul>`]);
}

function renderShell() {
  $("#app").innerHTML = html`<div class="shell">
    <nav class="side" id="side" aria-label="Main">
      <a class="brand" href="#/home"><span class="brand-mark" aria-hidden="true">◡</span>NeuroBridge</a>
      ${navHtml()}
      <p class="hint" style="padding:16px 12px 0">NeuroBridge is a support tool, not a medical service. In an emergency call <strong>112</strong>.</p>
    </nav>
    <div class="main-col">
      <header class="top">
        <button class="btn icon-btn quiet menu-btn" id="menuBtn" aria-label="Open menu" aria-expanded="false">☰</button>
        <span class="spacer"></span>
        <button class="btn overwhelm" id="overwhelmBtn">🌊 <span>${t("I'm overwhelmed")}</span></button>
        <button class="btn icon-btn quiet" id="bellBtn" aria-label="${t("Notifications")}">🔔<span class="badge-dot hide" id="bellCount"></span></button>
        <button class="btn quiet small" id="userBtn" aria-haspopup="dialog" aria-label="Account: ${S.user.display_name}"><span aria-hidden="true">👤</span><span class="uname">${S.user.display_name} ▾</span></button>
      </header>
      <main id="main" tabindex="-1"></main>
    </div></div>`.s;
  $("#menuBtn").onclick = () => { const s = $("#side"); s.classList.toggle("open"); $("#menuBtn").setAttribute("aria-expanded", s.classList.contains("open")); };
  $("#side").addEventListener("click", (e) => { if (e.target.closest("a")) $("#side").classList.remove("open"); });
  $("#overwhelmBtn").onclick = openOverwhelm;
  $("#bellBtn").onclick = openNotifications;
  $("#userBtn").onclick = () => {
    const d = dialog({ title: S.user.display_name, okText: "", cancelText: "Close",
      body: html`<p class="muted">${S.user.email} · ${S.user.role}${S.user.is_minor ? " · under 18" : ""}</p>
        <div class="row"><a class="btn" href="#/settings" id="toSettings">⚙️ ${t("Settings")}</a>
        <button class="btn danger" type="button" id="signOutBtn">${t("Sign out")}</button></div>` });
    $("#signOutBtn", d).onclick = signOut;
    $("#toSettings", d).onclick = () => { d.close(); d.remove(); };
  };
  updateBell();
}

async function navigate() {
  if (!S.user) return;
  const [name, ...args] = (location.hash.replace(/^#\/?/, "") || "home").split("/");
  const fn = ROUTES[name] || ROUTES.home;
  $$(".nav a").forEach((a) => a.dataset.nav === name ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  if (CURRENT.cleanup) { try { CURRENT.cleanup(); } catch {} }
  CURRENT = { name, cleanup: null };
  const main = $("#main");
  main.innerHTML = html`<div class="loading"><span class="spinner"></span> Loading…</div>`.s;
  try { await fn(main, ...args); }
  catch (e) {
    main.innerHTML = html`<div class="card"><div class="empty"><div class="art">🌧</div><h3>That didn't load</h3><p>${e.message}</p>
      <button class="btn" onclick="navigate()">Try again</button></div></div>`.s;
  }
  const h = $("h1", main); document.title = (h ? h.textContent + " · " : "") + "NeuroBridge";
  if (!navigate.first) main.focus({ preventScroll: true });
  navigate.first = false; window.scrollTo(0, 0);
}
navigate.first = true;
window.navigate = navigate;

function head(title, sub, actions = "") {
  return html`<div class="page-head"><div><h1>${title}</h1>${sub ? html`<p>${sub}</p>` : ""}</div><div class="row">${actions}</div></div>`;
}
const emptyState = (art, title, text, action = "") => html`<div class="empty"><div class="art" aria-hidden="true">${art}</div><h3>${title}</h3><p>${text}</p>${action}</div>`;
function bind(root, handlers) {
  root.onclick = async (e) => {
    const el = e.target.closest("[data-act]"); if (!el || !root.contains(el)) return;
    const fn = handlers[el.dataset.act]; if (!fn) return;
    e.preventDefault();
    if (el.tagName === "BUTTON") el.disabled = true;
    try { await fn(el, e); } catch (err) { fail(err); } finally { if (el.isConnected && el.tagName === "BUTTON") el.disabled = false; }
  };
  root.onsubmit = async (e) => {
    const f = e.target.closest("form[data-form]"); if (!f) return;
    e.preventDefault(); const fn = handlers[f.dataset.form]; if (!fn) return;
    const btn = $("button[type=submit],button:not([type])", f); if (btn) btn.disabled = true;
    try { await fn(new FormData(f), f); } catch (err) { fail(err); } finally { if (btn) btn.disabled = false; }
  };
}
const val = (fd, k) => { const v = fd.get(k); return v === null || v === "" ? null : String(v).trim(); };

/* ============================================================ notifications */
async function updateBell() {
  try {
    const me = await GET("me"); S.unread = me.unread_notifications;
    const b = $("#bellCount"); if (!b) return;
    b.textContent = S.unread; b.classList.toggle("hide", !S.unread);
  } catch {}
}
async function pollNotifications() {
  if (!S.user) return;
  try {
    const now = new Date().toTimeString().slice(0, 5);
    await GET("reminders/due?hhmm=" + encodeURIComponent(now));
    const r = await GET("notifications");
    const fresh = r.notifications.filter((n) => n.id > S.seenNotif && !n.read_at && !n.silent);
    if (fresh.length && !document.documentElement.dataset.overwhelm) fresh.slice(0, 2).forEach((n) => toast("🔔 " + n.title));
    if (r.notifications[0]) { S.seenNotif = Math.max(S.seenNotif, r.notifications[0].id); store.set("nb_seen_notif", S.seenNotif); }
    updateBell();
  } catch {}
}
async function openNotifications() {
  const r = await GET("notifications").catch(fail); if (!r) return;
  const d = dialog({ title: t("Notifications"), okText: "Mark all as read", cancelText: "Close", wide: true,
    onOk: async () => { await POST("notifications/read"); updateBell(); },
    body: r.notifications.length ? html`<ul class="list">${r.notifications.map((n) => html`<li class="item">
      <div class="grow"><div class="item-title">${n.read_at ? "" : "● "}${n.title}</div>${n.body ? html`<div class="muted">${n.body}</div>` : ""}
      <small>${fmtWhen(n.created_at)}${n.silent ? " · arrived during quiet hours" : ""}</small></div>
      ${n.link ? html`<a class="btn small" href="${n.link}" data-close>Open</a>` : ""}</li>`)}</ul>
      <p class="hint">Change what you get in Settings → Notifications.</p>` : emptyState("🔕", "All quiet", "No notifications yet.") });
  $$("[data-close]", d).forEach((a) => a.addEventListener("click", () => { d.close(); d.remove(); }));
}

/* ============================================================ auth */
function renderAuth(mode = "signin") {
  document.documentElement.dataset.theme = "light";
  $("#app").innerHTML = html`<div class="auth">
    <section class="auth-hero">
      <h1>Support that fits the way your brain works.</h1>
      <p>NeuroBridge helps neurodivergent people plan their day, communicate needs, and calm overwhelm — and helps the people who support them do it with consent, not control.</p>
      <ul class="feature-list">
        <li>🌊 A calm “I'm overwhelmed” mode, always one tap away</li>
        <li>✨ An AI assistant that researches with sources and never books anything without you</li>
        <li>🫶 A circle of support where <strong>you</strong> choose what is shared</li>
        <li>🤝 Community groups, clubs and sensory-friendly events</li>
      </ul>
    </section>
    <section class="auth-form"><div class="card">
      <div class="tabs" role="tablist">
        <button role="tab" aria-selected="${mode === "signin"}" data-mode="signin">Sign in</button>
        <button role="tab" aria-selected="${mode === "register"}" data-mode="register">Create account</button>
      </div>
      ${mode === "signin" ? html`<form id="authForm">
        <div class="field"><label for="em">Email</label><input id="em" name="email" type="email" autocomplete="email" required></div>
        <div class="field"><label for="pw">Password</label><input id="pw" name="password" type="password" autocomplete="current-password" required></div>
        <button class="btn primary" style="width:100%">Sign in</button></form>` :
      html`<form id="authForm">
        <fieldset class="field" style="border:0;padding:0;margin:0 0 16px"><legend style="font-weight:550;margin-bottom:8px">This account is for…</legend>
          <label class="check"><input type="radio" name="role" value="individual" checked> <span><strong>Me</strong> — I'm neurodivergent (or think I might be) and want support for myself.</span></label>
          <label class="check" style="margin-top:8px"><input type="radio" name="role" value="caregiver"> <span><strong>Supporting someone</strong> — parent, family, partner, carer, educator or support worker.</span></label>
        </fieldset>
        <div class="field"><label for="dn">What should we call you?</label><input id="dn" name="display_name" type="text" maxlength="60" required></div>
        <div class="field"><label for="em">Email</label><input id="em" name="email" type="email" autocomplete="email" required></div>
        <div class="field"><label for="pw">Password</label><input id="pw" name="password" type="password" autocomplete="new-password" minlength="10" required><div class="hint">At least 10 characters, with a number, symbol or capital.</div></div>
        <div class="field"><label for="lg">Language</label><select id="lg" name="language">${window.NB_LANGS.map(([c, n]) => html`<option value="${c}">${n}</option>`)}</select></div>
        <label class="check field"><input type="checkbox" name="is_minor"> <span>I'm under 18 <span class="hint">(a parent or guardian can help manage sharing, and community features are limited for safety)</span></span></label>
        <button class="btn primary" style="width:100%">Create account</button>
        <p class="hint" style="margin-top:12px">Your journal, check-in notes, AI chats and memories are private to you. Nothing is shared with anyone unless you choose.</p></form>`}
      <div id="authErr" role="alert"></div>
    </div></section></div>`.s;
  $$("[data-mode]").forEach((b) => b.onclick = () => renderAuth(b.dataset.mode));
  $("#authForm").onsubmit = async (e) => {
    e.preventDefault(); const fd = new FormData(e.target); const btn = $("button", e.target); btn.disabled = true;
    try {
      const body = mode === "signin" ? { email: fd.get("email"), password: fd.get("password") } :
        { email: fd.get("email"), password: fd.get("password"), display_name: fd.get("display_name"), role: fd.get("role"), is_minor: !!fd.get("is_minor"), language: fd.get("language") };
      if (body.is_minor && body.role === "caregiver") throw new Error("Caregiver accounts are for adults.");
      const r = await POST(mode === "signin" ? "auth/login" : "auth/register", body);
      S.token = r.token; store.set("nb_token", r.token); await boot(true);
    } catch (err) { $("#authErr").innerHTML = html`<div class="alert danger" style="margin-top:12px">${err.message}</div>`.s; }
    finally { btn.disabled = false; }
  };
}
function signOutLocal() { S.token = null; S.user = null; store.del("nb_token"); renderAuth(); }
async function signOut() { try { await POST("auth/logout"); } catch {} $$("dialog").forEach((d) => d.remove()); signOutLocal(); }
