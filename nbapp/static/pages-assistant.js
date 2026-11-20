/* NeuroBridge — AI assistant page: chat LLM + research/booking agent in one conversation. */
"use strict";

const MODE_LABEL = { chat: "Chat", agent: "Research & actions", safety: "Safety guidance" };
const SUGGEST = {
  individual: ["I have to clean my room and I can't start.", "Help me plan a gentle day.", "Help me write a message saying I need more time.",
    "Find sensory-friendly social clubs near Panjim.", "What does research say about ADHD body doubling?"],
  caregiver: ["How can I support someone who is overwhelmed?", "How can I make transitions easier?", "How do I explain neurodivergence to family?",
    "Find a child psychologist in Goa who speaks Konkani.", "Find a support group for parents this month and sign me up."],
  admin: ["Summarise our community guidelines in simple words."],
};

route("assistant", async (main, cidArg, preset, presetMode) => {
  if (!S.status) S.status = await GET("status").catch(() => ({ ai_connected: false, models: [] }));
  const convs = (await GET("assistant/conversations")).conversations;
  let cid = cidArg && cidArg !== "new" ? Number(cidArg) : null;
  let conv = cid ? await GET("assistant/conversations/" + cid).catch(() => null) : null;
  if (!conv) cid = null;
  if (isCare() && !S.people) S.people = (await GET("circle")).links.filter((l) => l.status === "active");
  main.innerHTML = html`${head(isCare() ? t("Care assistant") : t("Assistant"), "Talk things through, plan, or research with sources. I won't book or send anything without your approval.")}
    ${S.status.ai_connected ? "" : html`<div class="alert warn"><strong>No AI model is connected.</strong> Chat needs a GROQ_API_KEY or GEMINI_API_KEY on the server (see the README). Emergency guidance still works.</div>`}
    <div class="chat-wrap">
      <aside class="card soft conv-list" aria-label="Conversations"><a class="btn small primary" href="#/assistant/new" style="width:100%;margin-bottom:8px">+ New chat</a>
        ${convs.length ? convs.map((c) => html`<button data-act="open" data-id="${c.id}" aria-current="${c.id === cid}" title="${c.title}">${c.title}</button>`) : html`<p class="hint">Your chats are private to you.</p>`}</aside>
      <section class="chat">
        <div class="msgs" id="msgs" aria-live="polite">${conv ? conv.messages.map(msgHtml) : html`<div class="card soft"><h3>Try asking</h3><div class="suggest">${(SUGGEST[S.user.role] || []).map((s) => html`<button class="btn small" data-act="suggest" data-text="${s}">${s}</button>`)}</div>
          <p class="hint" style="margin:0"><strong>Auto</strong> picks for you: everyday help goes to Chat; questions needing facts, sources, places or bookings go to Research &amp; actions, which searches the web and shows its sources.</p></div>`}</div>
        <form class="composer" id="composer" data-form="send">
          <label class="sr-only" for="msgIn">Message</label>
          <textarea id="msgIn" name="message" placeholder="Type here… (Enter to send, Shift+Enter for a new line)" maxlength="6000" required>${preset ? decodeURIComponent(preset) : ""}</textarea>
          <div class="composer-bar">
            <label class="sr-only" for="modeSel">Mode</label>
            <select id="modeSel" name="mode"><option value="auto">Auto</option><option value="chat" ${raw(presetMode === "chat" ? "selected" : "")}>Chat</option><option value="agent" ${raw(presetMode === "agent" ? "selected" : "")}>Research &amp; actions</option></select>
            ${S.status.models.length > 1 ? html`<label class="sr-only" for="modelSel">Model</label><select id="modelSel" name="provider" title="AI model"><option value="">Default model</option>${S.status.models.map((m) => html`<option value="${m.provider}">${m.label}</option>`)}</select>` : ""}
            ${isCare() && S.people.length && !cid ? html`<label class="sr-only" for="aboutSel">About</label><select id="aboutSel" name="about" title="Who is this about?"><option value="">Not about a specific person</option>${S.people.map((p) => html`<option value="${p.individual_id}">About ${p.display_name}</option>`)}</select>` : ""}
            <label class="check" style="margin:0;font-size:.86rem"><input type="checkbox" name="allow_actions"> Allow bookings (I'll still approve each one)</label>
            <span class="spacer" style="flex:1"></span>
            <button type="button" class="btn small quiet" data-act="mic" aria-label="Speak your message">🎙</button>
            ${cid ? html`<button type="button" class="btn small quiet" data-act="remember" title="Suggest things to remember">🧠 Remember</button>` : ""}
            <button class="btn primary small" id="sendBtn">${t("Send")}</button>
          </div></form>
        <p class="hint">AI can be wrong. NeuroBridge doesn't diagnose or give medication advice. In an emergency call 112.</p>
      </section></div>`.s;
  const msgs = $("#msgs"); const input = $("#msgIn");
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });
  if (preset) input.focus(); else if (!cid) input.focus();
  window.scrollTo(0, document.body.scrollHeight);
  const send = async (fd) => {
    const text = String(fd.get("message") || "").trim(); if (!text) return;
    if (!conv && msgs.querySelector(".card.soft")) msgs.innerHTML = "";
    msgs.insertAdjacentHTML("beforeend", msgHtml({ role: "user", content: text }).s);
    input.value = "";
    const mode = fd.get("mode");
    const pending = document.createElement("div"); pending.className = "msg assistant";
    pending.innerHTML = html`<div class="loading" style="padding:0"><span class="spinner"></span> ${mode === "agent" ? "Researching — searching, reading and checking sources…" : mode === "chat" ? "Thinking…" : "Working on it…"}</div>`.s;
    msgs.appendChild(pending); pending.scrollIntoView({ block: "end" });
    try {
      const r = await POST("assistant/message", { message: text, conversation_id: cid, mode, provider: fd.get("provider") || null,
        allow_actions: !!fd.get("allow_actions"), about_individual_id: fd.get("about") ? Number(fd.get("about")) : null });
      pending.outerHTML = msgHtml({ role: "assistant", content: r.reply, mode: r.mode, meta: r.meta, sources: r.sources }).s;
      if (!cid) { cid = r.conversation_id; history.replaceState(null, "", "#/assistant/" + cid); conv = { messages: [] }; }
      if (S.prefs.tts && S.prefs.auto_speak) speak(r.reply);
    } catch (e) { pending.outerHTML = html`<div class="msg assistant"><div class="alert danger" style="margin:0">${e.message}</div></div>`.s; }
    msgs.lastElementChild.scrollIntoView({ block: "end" });
  };
  bind(main, {
    send, open: (b) => { location.hash = "#/assistant/" + b.dataset.id; },
    suggest: (b) => { input.value = b.dataset.text; input.focus(); },
    mic: () => listen((txt) => { input.value = (input.value ? input.value + " " : "") + txt; input.focus(); }),
    speak: (b) => speak(b.closest(".msg").querySelector(".msg-text").innerText),
    approve: async (b) => {
      const ok = b.dataset.ok === "1";
      if (ok && !(await confirmDlg("Approve this action?", "NeuroBridge will do exactly what is shown — nothing else. If any detail changes, it will ask you again.", "Approve"))) return;
      const r = await POST(`assistant/runs/${b.dataset.run}/approve`, { approval_id: b.dataset.ap, approved: ok });
      b.closest(".approval").innerHTML = html`<span class="chip ${ok ? "sage" : ""}">${ok ? "Approved" : "Declined"}</span>`.s;
      msgs.insertAdjacentHTML("beforeend", msgHtml({ role: "assistant", content: r.reply, mode: r.mode, meta: r.meta, sources: r.sources }).s);
      msgs.lastElementChild.scrollIntoView({ block: "end" });
    },
    track: (b) => dialog({ title: "Track this clinic", okText: "Save", wide: true,
      body: html`<p class="hint">Fill in what you can see on the source page. NeuroBridge can't book with clinics outside its directory — this keeps track and drafts a message.</p>
        <div class="field"><label for="tn">Clinic or doctor name</label><input id="tn" name="clinic_name" required maxlength="200" value="${(b.dataset.title || "").split(/[|\-–—:]/)[0].trim().slice(0, 200)}"></div>
        <div class="grid g2"><div class="field"><label for="tp">Profession</label><input id="tp" name="profession" maxlength="80" placeholder="e.g. Psychiatrist"></div><div class="field"><label for="tph">Phone (from the page)</label><input id="tph" name="phone" maxlength="40"></div></div>
        <div class="field"><label for="tt">Times that suit you</label><input id="tt" name="preferred_times" maxlength="200" placeholder="e.g. weekday mornings"></div>
        <input type="hidden" name="source_url" value="${b.dataset.url}">`,
      onOk: async (fd) => { const body = {}; for (const k of ["clinic_name", "profession", "phone", "preferred_times", "source_url"]) body[k] = val(fd, k);
        await POST("outside-requests", body); toast("Saved to Providers & appointments."); } }),
    remember: async () => {
      const r = await POST("assistant/memory/suggest", { conversation_id: cid });
      if (!r.candidates.length) return toast("Nothing in this chat seems worth remembering.");
      dialog({ title: "Remember anything from this chat?", okText: "Save selected", wide: true,
        body: html`<p class="muted">Only what you tick is saved. You can see and delete memories in Settings. Your circle never sees them.</p>
          ${r.candidates.map((c, i) => html`<label class="check field"><input type="checkbox" name="k" value="${c.key}"> <span><strong>${c.key}</strong>: ${c.value} ${c.sensitive ? html`<span class="chip rose">sensitive</span>` : ""}</span></label>`)}
          <label class="check"><input type="checkbox" name="sens"> Also save items marked sensitive</label>`,
        onOk: async (fd) => { const s = await POST("assistant/memory/save", { candidates: r.candidates, approved_keys: fd.getAll("k"), allow_sensitive: !!fd.get("sens") });
          toast(`Saved ${s.saved.length}.` + (s.rejected.length ? ` ${s.rejected.length} not saved.` : "")); } });
    },
  });
});

function msgHtml(m) {
  if (m.role === "user") return html`<div class="msg user"><div class="msg-text">${m.content}</div></div>`;
  const meta = m.meta || {}, mode = m.mode || "chat";
  const pend = (meta.approvals || []);
  const statusChip = { COMPLETED: ["Completed", "sage"], PARTIAL: ["Partly completed", "amber"], WAITING_APPROVAL: ["Needs your approval", "lav"],
    FAILED: ["Couldn't finish", "rose"], NO_EVIDENCE: ["No sources found", "amber"], EMERGENCY_GUIDANCE: ["Emergency guidance", "rose"] }[meta.status];
  return html`<div class="msg assistant ${mode === "safety" ? "safety" : ""}">
    ${meta.activity?.length ? html`<div class="activity" aria-label="What the agent did">${meta.activity.map((a) => html`<span class="chip">${a}</span>`)}</div>` : ""}
    <div class="msg-text">${md(m.content)}</div>
    ${pend.length ? pend.map((a) => html`<div class="card soft approval" style="margin-top:10px;padding:12px"><strong>Approval needed:</strong> ${a.reason || a.task_name}
      ${a.summary ? html`<dl class="kv" style="margin:8px 0">${Object.entries(a.summary).filter(([k]) => k !== "demo_listing").map(([k, v]) => html`<dt>${k.replace(/_/g, " ")}</dt><dd>${typeof v === "boolean" ? (v ? "yes" : "no") : (k === "start" || k === "end") && /^\d{4}-\d\d-\d\dT/.test(v || "") ? fmtWhen(v) : String(v ?? "")}</dd>`)}</dl>` : ""}
      ${a.summary?.demo_listing ? html`<p class="alert warn" style="margin:6px 0">This is a demo listing — not a real event or clinic.</p>` : ""}
      <div class="row"><button class="btn small primary" data-act="approve" data-ok="1" data-run="${meta.run_id}" data-ap="${a.approval_id}">Approve</button>
      <button class="btn small" data-act="approve" data-ok="0" data-run="${meta.run_id}" data-ap="${a.approval_id}">Decline</button></div></div>`) : ""}
    ${m.sources?.length ? html`<div class="sources"><strong>Sources</strong><ol>${m.sources.map((s) => html`<li>${s.ref || s.id ? html`<span class="chip">${s.ref || s.id}</span> ` : ""}<a href="${s.url}" target="_blank" rel="noopener noreferrer">${s.title || s.url}</a>${s.published ? html` <small>(${s.published})</small>` : ""}${meta.provider_request ? html` <button class="btn small quiet" data-act="track" data-title="${s.title || ""}" data-url="${s.url}">＋ Track this clinic</button>` : ""}</li>`)}</ol>
      ${meta.provider_request ? html`<p class="hint" style="margin:6px 0 0">Found a clinic you like that isn't in NeuroBridge? “Track this clinic” saves it in Providers &amp; appointments with a ready-to-send message. Check its phone number on the clinic's own website.</p>` : ""}</div>` : ""}
    <div class="msg-meta"><span class="chip ${mode === "agent" ? "blue" : mode === "safety" ? "rose" : "teal"}">${MODE_LABEL[mode] || mode}${meta.routed ? " (auto)" : ""}</span>
      ${statusChip ? html`<span class="chip ${statusChip[1]}">${statusChip[0]}</span>` : ""}
      ${meta.label ? html`<span class="chip">${meta.label}</span>` : ""}
      ${meta.context_used?.length ? html`<span class="chip lav" title="Personal context used">Used: ${meta.context_used.join(", ")}</span>` : ""}
      ${meta.llm_called === false ? html`<span class="chip">Fixed guidance — no AI</span>` : ""}
      <button class="btn small quiet" data-act="speak" aria-label="Read aloud">🔊</button></div></div>`;
}
