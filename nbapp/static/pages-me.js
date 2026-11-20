/* NeuroBridge — individual pages: overwhelm mode, My Day, tasks, focus, routines,
   check-in + insights, sensory toolkit, communication cards, journal, blueprint, goals, learn. */
"use strict";

/* ============================================================ Overwhelm mode */
async function openOverwhelm() {
  const root = document.documentElement;
  const prevLow = root.dataset.lowstim; root.dataset.lowstim = "1"; root.dataset.overwhelm = "1";
  const el = document.createElement("div");
  el.className = "calm"; el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true"); el.setAttribute("aria-label", "Calm mode");
  document.body.appendChild(el);
  const exit = () => { el.remove(); root.dataset.lowstim = prevLow; delete root.dataset.overwhelm; speechSynthesis?.cancel?.(); document.removeEventListener("keydown", onKey); $("#overwhelmBtn")?.focus(); };
  const onKey = (e) => { if (e.key === "Escape") exit(); };
  document.addEventListener("keydown", onKey);
  let strategies = null, cards = null;
  const screen = (inner) => {
    el.innerHTML = html`<button class="btn exit" data-c="exit">Exit calm mode ✕</button><div class="calm-inner">${inner}</div>`.s;
    const first = $(".opt, .btn:not(.exit)", el) || $(".exit", el); first?.focus();
  };
  const home = () => screen(html`<h2>I'm here.</h2><p>You don't need to explain anything.</p><p>What would help right now?</p>
    <div class="opts">
      <button class="opt" data-c="quiet"><span aria-hidden="true">🤫</span> Quiet</button>
      <button class="opt" data-c="less"><span aria-hidden="true">🫧</span> Less talking</button>
      <button class="opt" data-c="communicate"><span aria-hidden="true">💬</span> Help me communicate</button>
      <button class="opt" data-c="ground"><span aria-hidden="true">🪨</span> Grounding</button>
      <button class="opt" data-c="someone"><span aria-hidden="true">🫶</span> I need someone</button>
      <button class="opt" data-c="unsure"><span aria-hidden="true">🌫</span> I'm not sure</button>
    </div>`);
  const back = html`<p style="margin-top:32px"><button class="btn" data-c="home">Back</button></p>`;
  const actions = {
    exit, home,
    quiet: () => screen(html`<p>Quiet.</p><p class="muted">Take your time. Nothing is needed from you.</p>${back}`),
    less: () => screen(html`<h2>OK.</h2><p>Fewer words now.</p><p>You are safe to rest here.</p>${back}`),
    communicate: async () => {
      if (!cards) { try { cards = (await GET("cards")).cards.filter((c) => !c.hidden); } catch { cards = []; } }
      const fav = cards.filter((c) => c.favorite); const show = (fav.length ? fav : cards).slice(0, 6);
      screen(html`<h2>Show or play a card</h2><div class="opts">${show.map((c) => html`<button class="opt" data-c="card" data-text="${c.text}"><span aria-hidden="true">${c.symbol || "💬"}</span> ${c.text}</button>`)}</div>${back}`);
    },
    card: (b) => { const text = b.dataset.text; el.innerHTML = html`<div class="big-card" style="background:inherit"><div class="txt">${text}</div>
      <div class="row"><button class="btn" data-c="say" data-text="${text}">🔊 Say it</button><button class="btn" data-c="communicate">Back</button></div></div>`.s; },
    say: (b) => speak(b.dataset.text),
    ground: async (b) => {
      if (!strategies) { try { strategies = (await GET("sensory")).strategies.filter((s) => s.status !== "removed" && s.status !== "disliked"); } catch { strategies = []; } }
      const i = Number(b?.dataset.i || 0) % Math.max(1, strategies.length); const s = strategies[i];
      screen(s ? html`<h2>${s.title}</h2><p>${s.how}</p>
        <div class="row" style="margin-top:24px"><button class="btn" data-c="ground" data-i="${i + 1}">Try something else</button>${back}</div>`
        : html`<p>Find a quieter spot if you can. Notice your feet on the floor.</p>${back}`);
    },
    someone: async () => {
      if (!isInd()) return screen(html`<p>If anyone is in danger, call <strong>112</strong>.</p>${back}`);
      let circle = []; try { circle = (await GET("circle")).links.filter((l) => l.status === "active"); } catch {}
      screen(html`<h2>Who should I tell?</h2>
        ${circle.length ? html`<div class="opts">${circle.map((l) => html`<button class="opt" data-c="send" data-id="${l.caregiver_id}">🫶 ${l.display_name}</button>`)}
          <button class="opt" data-c="send" data-id="">📣 Everyone in my circle</button></div>`
        : html`<p>No one is in your circle yet. You can add trusted people in My circle later.</p>`}
        <p class="muted" style="margin-top:20px">If you or someone else is in danger, call <strong>112</strong> now.</p>${back}`);
    },
    send: async (b) => {
      try {
        const r = await POST("support-requests", { message: "I need help. (sent from calm mode)", to: b.dataset.id ? [Number(b.dataset.id)] : [] });
        screen(html`<h2>Sent.</h2><p>I told ${r.sent_to} ${r.sent_to === 1 ? "person" : "people"} you need help.</p><p class="muted">You can stay here while you wait.</p>${back}`);
      } catch (e) { screen(html`<p>${e.message}</p>${back}`); }
    },
    unsure: () => screen(html`<h2>That's OK.</h2><p>Maybe start with somewhere quieter, or something to drink.</p>
      <div class="opts"><button class="opt" data-c="quiet">🤫 Just quiet</button><button class="opt" data-c="ground">🪨 One small grounding idea</button></div>${back}`),
  };
  el.addEventListener("click", (e) => { const b = e.target.closest("[data-c]"); if (b && actions[b.dataset.c]) actions[b.dataset.c](b); });
  home();
}

/* ============================================================ My Day */
const ENERGY = [[1, "🪫", "Very low"], [2, "😮‍💨", "Low"], [3, "🙂", "OK"], [4, "😊", "Good"], [5, "⚡", "High"]];
route("home", async (main) => {
  if (isCare()) return ROUTES.carehome(main);
  if (isAdmin()) return ROUTES.moderation(main);
  const d = await GET("myday");
  const hour = new Date().getHours(); const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const open = d.tasks.filter((x) => x.status !== "done");
  main.innerHTML = html`${head(`${greet}, ${S.user.display_name}`, "Here's today. Change anything — skipping or moving things is completely fine.",
      html`<a class="btn" href="#/assistant">✨ Ask the assistant</a>`)}
    <div class="grid g3" style="margin-bottom:16px">
      <div class="card tint-teal" style="grid-column:span 2"><h3>How's your energy?</h3>
        <div class="scale" role="group" aria-label="Energy">${ENERGY.map(([v, e, l]) => html`<button class="choice" data-act="energy" data-v="${v}" aria-pressed="${d.last_checkin?.energy === v && d.last_checkin.created_at.slice(0, 10) === today()}"><span class="emo" aria-hidden="true">${e}</span>${l}</button>`)}</div>
        <p class="hint" style="margin-top:8px">Optional. It helps the assistant suggest the right size of plan.</p></div>
      <div class="card tint-lav"><h3>Need something now?</h3><div class="stack">
        <a class="btn" href="#/communicate">💬 Communication cards</a>
        <button class="btn" data-act="overwhelm">🌊 Calm mode</button>
        <a class="btn" href="#/sensory">🎧 Sensory toolkit</a></div></div>
    </div>
    <div class="grid g2">
      <div class="card"><div class="card-head"><h3>Today's tasks</h3><a class="btn small quiet" href="#/tasks">All tasks →</a></div>
        ${d.suggested_next ? html`<div class="alert info"><strong>Maybe start with:</strong> ${d.suggested_next.task.title}<br><small>${d.suggested_next.reason}</small>
          <div class="row" style="margin-top:8px"><button class="btn small primary" data-act="start" data-id="${d.suggested_next.task.id}">${t("Help me start")}</button></div></div>` : ""}
        ${open.length ? html`<ul class="list">${open.map((x) => html`<li class="item">
            <input type="checkbox" class="check" aria-label="Mark ${x.title} done" data-act="done" data-id="${x.id}" style="width:22px;height:22px;margin-top:3px">
            <div class="grow"><div class="item-title">${x.title}</div><small>${[x.estimate_min ? `~${x.estimate_min} min` : "", x.due_date ? "due " + fmtDate(x.due_date) : ""].filter(Boolean).join(" · ")}</small></div>
            <button class="btn small quiet" data-act="later" data-id="${x.id}" title="Move to later">Later</button></li>`)}</ul>`
          : emptyState("🌱", "Nothing planned", "That's allowed. Add one small thing if you want to.", html`<a class="btn small" href="#/tasks">Add a task</a>`)}
        <form data-form="quickTask" class="row" style="margin-top:12px"><label class="sr-only" for="qt">New task for today</label>
          <input id="qt" name="title" type="text" placeholder="Add something for today…" style="flex:1" maxlength="200" required><button class="btn">${t("Add")}</button></form>
      </div>
      <div class="stack">
        <div class="card"><div class="card-head"><h3>Coming up</h3><a class="btn small quiet" href="#/calendar">Calendar →</a></div>
          ${d.events.length ? html`<ul class="list">${d.events.slice(0, 5).map((e) => html`<li><div class="item-title">${e.title}</div><small>${fmtWhen(e.start_time)}${e.location ? " · " + e.location : ""}</small></li>`)}</ul>`
            : html`<p class="muted">Nothing in the next week.</p>`}</div>
        <div class="card"><div class="card-head"><h3>Routines</h3><a class="btn small quiet" href="#/routines">All →</a></div>
          ${d.routines.length ? html`<div class="row">${d.routines.slice(0, 4).map((r) => html`<a class="btn small" href="#/routines/${r.id}">▶ ${r.name}${r.reminder_time ? " · " + r.reminder_time : ""}</a>`)}</div>`
            : html`<p class="muted">No routines yet. <a href="#/routines">Make one from a template</a>.</p>`}</div>
        <div class="card tint-sage"><h3>Done today</h3>${d.accomplishments.length ? html`<ul>${d.accomplishments.map((a) => html`<li>${a.title}</li>`)}</ul>` : html`<p class="muted">Anything counts — even resting.</p>`}</div>
      </div>
    </div>`.s;
  bind(main, {
    energy: async (b) => { await POST("checkins", { energy: Number(b.dataset.v) }); $$("[data-act=energy]", main).forEach((x) => x.setAttribute("aria-pressed", x === b)); toast("Thanks. Noted for today."); },
    overwhelm: openOverwhelm,
    start: (b) => helpStart(Number(b.dataset.id)),
    done: async (b) => { await PATCH("tasks/" + b.dataset.id, { status: "done" }); toast("Done. Nice."); navigate(); },
    later: async (b) => { await PATCH("tasks/" + b.dataset.id, { status: "later", plan_date: null }); toast("Moved to later. No problem."); navigate(); },
    quickTask: async (fd) => { await POST("tasks", { title: val(fd, "title"), plan_date: today() }); navigate(); },
  });
});

/* ============================================================ Tasks */
async function helpStart(taskId, kind = "start") {
  const r = await POST("assistant/task-help", { task_id: taskId, kind }).catch(fail); if (!r) return;
  const d = dialog({ title: kind === "simplify" ? "A simpler version" : "Just this one step", okText: kind === "simplify" ? "" : "Give me the next step", cancelText: "OK",
    body: html`<p style="font-size:1.3rem;font-weight:600">${r.step}</p>${r.note ? html`<p class="hint">${r.note}</p>` : html`<p class="hint">Suggested by AI. Change or delete it any time.</p>`}
      ${kind !== "simplify" ? html`<p class="hint">Added to the task's steps.</p>` : ""}`,
    onOk: async () => { setTimeout(() => helpStart(taskId, "next"), 50); } });
  d.addEventListener("close", () => { if (CURRENT.name === "tasks" || CURRENT.name === "home") navigate(); });
}

function focusSession(task) {
  let mins = 15, left = 0, timer = null;
  const d = dialog({ title: task ? `Focus: ${task.title}` : "Focus session", okText: "", cancelText: "Close", body: html`
    <div id="fsSetup"><p>Pick a length. You can stop any time — stopping early still counts.</p>
      <div class="row">${[5, 10, 15, 25, 45].map((m) => html`<button type="button" class="choice" data-m="${m}" aria-pressed="${m === 15}">${m} min</button>`)}</div>
      <p style="margin-top:16px"><button type="button" class="btn primary" id="fsGo">Start</button></p></div>
    <div id="fsRun" class="hide"><div class="timer" id="fsTime" aria-live="off"></div>
      <p class="muted" id="fsBuddy" style="text-align:center">I'm here working alongside you.</p>
      <div class="row" style="justify-content:center"><button type="button" class="btn" id="fsStop">Stop</button></div></div>` });
  const buddy = ["I'm here working alongside you.", "Still here. Keep going at your pace.", "Doing great — one bit at a time.", "If you drifted, that's normal. Come back gently.", "Almost there. Or stop — that's fine too."];
  $$("[data-m]", d).forEach((b) => b.onclick = () => { mins = Number(b.dataset.m); $$("[data-m]", d).forEach((x) => x.setAttribute("aria-pressed", x === b)); });
  const show = () => { $("#fsTime", d).textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`; };
  const end = async (completed) => {
    clearInterval(timer); timer = null;
    const used = Math.max(1, Math.round((mins * 60 - left) / 60));
    try { await POST("focus", { minutes: completed ? mins : used, task_id: task?.id || null, completed }); } catch {}
    $("#fsRun", d).innerHTML = html`<p style="text-align:center;font-size:1.2rem">${completed ? "Time's up. Well done." : `You focused for ${used} min. That counts.`}</p>`.s;
  };
  $("#fsGo", d).onclick = () => { left = mins * 60; $("#fsSetup", d).classList.add("hide"); $("#fsRun", d).classList.remove("hide"); show();
    timer = setInterval(() => { left--; show(); if (left % 300 === 0) $("#fsBuddy", d).textContent = buddy[(mins * 60 - left) / 300 % buddy.length]; if (left <= 0) end(true); }, 1000); };
  $("#fsStop", d).onclick = () => end(false);
  d.addEventListener("close", () => clearInterval(timer));
}

route("tasks", async (main) => {
  const r = await GET("tasks");
  const groups = { doing: [], todo: [], later: [], done: [], skipped: [] };
  r.tasks.forEach((x) => (groups[x.status] || groups.todo).push(x));
  const pri = { 1: ["Important", "rose"], 2: ["", ""], 3: ["Whenever", "sage"] };
  const taskLi = (x) => html`<li class="item ${x.status === "done" ? "done" : ""}">
    <input type="checkbox" aria-label="Done: ${x.title}" ${raw(x.status === "done" ? "checked" : "")} data-act="toggle" data-id="${x.id}" data-status="${x.status}" style="width:22px;height:22px;margin-top:3px;accent-color:var(--teal)">
    <div class="grow"><div class="row"><span class="item-title">${x.title}</span>${pri[x.priority][0] ? html`<span class="chip ${pri[x.priority][1]}">${pri[x.priority][0]}</span>` : ""}${x.plan_date === today() ? html`<span class="chip teal">Today</span>` : ""}${x.shared ? html`<span class="chip blue">Shared</span>` : ""}</div>
      <small>${[x.estimate_min ? `~${x.estimate_min} min` : "", x.due_date ? `due ${fmtDate(x.due_date)}` : ""].filter(Boolean).join(" · ")}</small>
      ${x.steps.length ? html`<ul class="list" style="margin:6px 0 0 4px">${x.steps.map((s) => html`<li class="item ${s.done ? "done" : ""}" style="padding:4px 0;border:0">
        <input type="checkbox" ${raw(s.done ? "checked" : "")} aria-label="Step: ${s.text}" data-act="step" data-id="${x.id}" data-step="${s.id}" data-done="${s.done}" style="accent-color:var(--teal)">
        <span class="grow item-title" style="font-weight:400">${s.text} ${s.source === "ai" ? html`<span class="chip lav">AI</span>` : ""}</span>
        <button class="btn small quiet" data-act="delstep" data-id="${x.id}" data-step="${s.id}" aria-label="Remove step">✕</button></li>`)}</ul>` : ""}
      ${x.status !== "done" ? html`<div class="row" style="margin-top:8px">
        <button class="btn small" data-act="start" data-id="${x.id}">🚀 ${x.steps.length ? "Next step" : t("Help me start")}</button>
        <button class="btn small" data-act="focus" data-id="${x.id}">⏱ Focus</button>
        <button class="btn small quiet" data-act="simplify" data-id="${x.id}">Make it smaller</button>
        <button class="btn small quiet" data-act="addstep" data-id="${x.id}">+ Step</button>
        <button class="btn small quiet" data-act="move" data-id="${x.id}" data-status="${x.status}">${x.status === "later" ? "Bring back" : x.plan_date === today() ? "Not today" : "Do today"}</button>
        <button class="btn small quiet" data-act="more" data-id="${x.id}">⋯</button></div>` : ""}
    </div></li>`;
  const section = (title, list, hint) => list.length ? html`<h3 style="margin-top:20px">${title} <small class="muted">${list.length}</small></h3>${hint ? html`<p class="hint">${hint}</p>` : ""}<ul class="list">${list.map(taskLi)}</ul>` : "";
  main.innerHTML = html`${head(t("Tasks"), "Small steps, flexible plans. Nothing here is graded.",
      html`<button class="btn" data-act="next">🧭 ${t("What should I do next?")}</button><button class="btn" data-act="focus">⏱ Focus session</button>`)}
    <div class="card" style="margin-bottom:16px"><form data-form="add" class="grid" style="grid-template-columns:2fr 1fr 1fr auto;align-items:end">
      <div><label for="tt">New task</label><input id="tt" name="title" type="text" maxlength="200" required placeholder="e.g. Reply to Priya's email"></div>
      <div><label for="te">Rough time (min)</label><input id="te" name="estimate_min" type="number" min="1" max="600"></div>
      <div><label for="td">Due (optional)</label><input id="td" name="due_date" type="date"></div>
      <div class="row"><label class="check" style="margin:0 8px 10px 0"><input type="checkbox" name="today" checked> Today</label><button class="btn primary">${t("Add")}</button></div>
    </form></div>
    <div class="card">${r.tasks.length ? html`${section("In progress", groups.doing)}${section("To do", groups.todo)}${section("Later", groups.later, "Parked for now. That's OK.")}${section("Done", groups.done.slice(0, 15))}${section("Skipped", groups.skipped)}`
      : emptyState("📝", "No tasks yet", "Add one above. If you're not sure where to start, ask the assistant to break something down.", html`<a class="btn" href="#/assistant">✨ Ask the assistant</a>`)}</div>`.s;
  const find = (id) => r.tasks.find((x) => x.id === Number(id));
  bind(main, {
    add: async (fd) => { await POST("tasks", { title: val(fd, "title"), estimate_min: fd.get("estimate_min") ? Number(fd.get("estimate_min")) : null, due_date: val(fd, "due_date"), plan_date: fd.get("today") ? today() : null }); navigate(); },
    toggle: async (b) => { await PATCH("tasks/" + b.dataset.id, { status: b.dataset.status === "done" ? "todo" : "done" }); navigate(); },
    step: async (b) => { await PATCH(`tasks/${b.dataset.id}/steps/${b.dataset.step}?done=${b.dataset.done === "0"}`); navigate(); },
    delstep: async (b) => { await DEL(`tasks/${b.dataset.id}/steps/${b.dataset.step}`); navigate(); },
    start: (b) => helpStart(Number(b.dataset.id), find(b.dataset.id).steps.length ? "next" : "start"),
    simplify: (b) => helpStart(Number(b.dataset.id), "simplify"),
    focus: (b) => focusSession(b.dataset.id ? find(b.dataset.id) : null),
    addstep: (b) => dialog({ title: "Add a step", body: html`<div class="field"><label for="st">Step</label><input id="st" name="text" type="text" maxlength="300" required></div>`,
      onOk: async (fd) => { await POST(`tasks/${b.dataset.id}/steps`, { text: val(fd, "text") }); navigate(); } }),
    move: async (b) => { const x = find(b.dataset.id); const body = x.status === "later" ? { status: "todo" } : x.plan_date === today() ? { plan_date: "" } : { plan_date: today(), status: x.status === "later" ? "todo" : x.status }; await PATCH("tasks/" + x.id, body); navigate(); },
    next: async () => { const n = await GET("tasks/next"); dialog({ title: "What next?", okText: n.task ? "Help me start" : "", cancelText: "Close",
      body: n.task ? html`<p style="font-size:1.2rem;font-weight:600">${n.task.title}</p><p class="muted">${n.reason}</p><p class="hint">Just a suggestion — pick something else if you want.</p>` : html`<p>${n.reason}</p>`,
      onOk: () => helpStart(n.task.id, n.task.steps.length ? "next" : "start") }); },
    more: (b) => { const x = find(b.dataset.id); const d = dialog({ title: "Edit task", body: html`
        <div class="field"><label for="et">Title</label><input id="et" name="title" type="text" value="${x.title}" maxlength="200" required></div>
        <div class="field"><label for="en">Notes</label><textarea id="en" name="notes">${x.notes || ""}</textarea></div>
        <div class="grid g2"><div class="field"><label for="ep">Priority</label><select id="ep" name="priority">${[[1, "Important"], [2, "Normal"], [3, "Whenever"]].map(([v, l]) => html`<option value="${v}" ${raw(x.priority === v ? "selected" : "")}>${l}</option>`)}</select></div>
        <div class="field"><label for="es">Status</label><select id="es" name="status">${["todo", "doing", "later", "skipped", "done"].map((s) => html`<option ${raw(x.status === s ? "selected" : "")}>${s}</option>`)}</select></div></div>
        ${isInd() ? html`<label class="check"><input type="checkbox" name="shared" ${raw(x.shared ? "checked" : "")}> Share with my circle <span class="hint">(only people you gave "Tasks" access)</span></label>` : ""}
        <p style="margin-top:16px"><button type="button" class="btn danger small" id="delTask">Delete task</button></p>`,
      onOk: async (fd) => { await PATCH("tasks/" + x.id, { title: val(fd, "title"), notes: fd.get("notes") || "", priority: Number(fd.get("priority")), status: fd.get("status"), shared: !!fd.get("shared") }); navigate(); } });
      $("#delTask", d).onclick = async () => { await DEL("tasks/" + x.id); d.close(); d.remove(); navigate(); }; },
  });
});

/* ============================================================ Routines */
route("routines", async (main, id) => {
  const [r, tpl] = await Promise.all([GET("routines"), GET("routines/templates")]);
  if (id) { const one = r.routines.find((x) => x.id === Number(id)); if (one) return routinePlayer(main, one); }
  main.innerHTML = html`${head(t("Routines"), "Step-by-step routines you can reorder, skip or change. Breaking a routine is never a failure.",
      html`<button class="btn primary" data-act="new">+ New routine</button>`)}
    ${r.routines.length ? html`<div class="grid gauto">${r.routines.map((x) => html`<div class="card">
        <div class="card-head"><h3>${x.name}</h3>${x.shared ? html`<span class="chip blue">Shared</span>` : ""}</div>
        <p class="muted">${x.steps.length} steps${x.reminder_time ? " · reminder " + x.reminder_time : ""}</p>
        <ol style="padding-left:20px;margin:0 0 12px">${x.steps.slice(0, 4).map((s) => html`<li>${s.text}${s.optional ? " (optional)" : ""}</li>`)}${x.steps.length > 4 ? html`<li class="muted">…</li>` : ""}</ol>
        <div class="row"><a class="btn small primary" href="#/routines/${x.id}">▶ Start</a><button class="btn small" data-act="edit" data-id="${x.id}">Edit</button></div></div>`)}</div>`
      : html`<div class="card">${emptyState("🔁", "No routines yet", "Start from a template below and change it to suit you.")}</div>`}
    <h2 style="margin-top:28px">Templates</h2>
    <div class="grid gauto">${tpl.templates.map((x) => html`<div class="card soft"><h3>${x.name}</h3><p class="muted">${x.steps.map((s) => s.text).join(" → ")}</p>
      <button class="btn small" data-act="tpl" data-key="${x.key}" data-name="${x.name}">Use this</button></div>`)}</div>`.s;
  bind(main, {
    tpl: async (b) => { await POST("routines", { name: b.dataset.name, template: b.dataset.key }); toast("Added. Edit it any time."); navigate(); },
    new: () => routineEditor(null), edit: (b) => routineEditor(r.routines.find((x) => x.id === Number(b.dataset.id))),
  });
});

function routineEditor(x) {
  const steps = x ? x.steps.map((s) => ({ ...s })) : [{ text: "", minutes: null }];
  const rowsHtml = () => steps.map((s, i) => html`<div class="row" style="margin-bottom:6px;flex-wrap:nowrap" data-row="${i}">
      <input type="text" aria-label="Step ${i + 1}" data-k="text" value="${s.text}" placeholder="Step ${i + 1}" style="flex:3" maxlength="200">
      <input type="number" aria-label="Minutes" data-k="minutes" value="${s.minutes ?? ""}" placeholder="min" style="width:80px" min="0">
      <label class="check" style="margin:0;font-size:.8rem"><input type="checkbox" data-k="optional" ${raw(s.optional ? "checked" : "")}>opt.</label>
      <button type="button" class="btn small quiet" data-mv="-1" data-i="${i}" aria-label="Move up">↑</button>
      <button type="button" class="btn small quiet" data-mv="1" data-i="${i}" aria-label="Move down">↓</button>
      <button type="button" class="btn small quiet" data-rm="${i}" aria-label="Remove step">✕</button></div>`);
  const d = dialog({ title: x ? "Edit routine" : "New routine", wide: true, body: html`
    <div class="grid g2"><div class="field"><label for="rn">Name</label><input id="rn" name="name" type="text" value="${x?.name || ""}" required maxlength="100"></div>
    <div class="field"><label for="rt">Gentle reminder (optional)</label><input id="rt" name="reminder_time" type="time" value="${x?.reminder_time || ""}"></div></div>
    <label>Steps</label><div id="rsteps"></div><button type="button" class="btn small" id="radd">+ Add step</button>
    ${isInd() ? html`<label class="check" style="margin-top:16px"><input type="checkbox" name="shared" ${raw(x?.shared ? "checked" : "")}> Share with my circle (people with "Routines" access)</label>` : ""}
    ${x ? html`<p style="margin-top:16px"><button type="button" class="btn small danger" id="rdel">Delete routine</button></p>` : ""}`,
    onOk: async (fd) => {
      sync(); const clean = steps.filter((s) => s.text.trim()).map((s) => ({ text: s.text.trim(), minutes: s.minutes ? Number(s.minutes) : null, optional: !!s.optional }));
      if (!clean.length) throw new Error("Add at least one step.");
      const body = { name: val(fd, "name"), reminder_time: val(fd, "reminder_time"), shared: !!fd.get("shared"), steps: clean };
      x ? await PUT("routines/" + x.id, body) : await POST("routines", body); navigate();
    } });
  const box = $("#rsteps", d);
  const sync = () => $$("[data-row]", box).forEach((row) => { const s = steps[row.dataset.row]; s.text = $("[data-k=text]", row).value; s.minutes = $("[data-k=minutes]", row).value; s.optional = $("[data-k=optional]", row).checked; });
  const draw = () => { box.innerHTML = rowsHtml().map((r) => r.s).join(""); };
  draw();
  $("#radd", d).onclick = () => { sync(); steps.push({ text: "" }); draw(); $$("[data-k=text]", box).pop().focus(); };
  box.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; sync();
    if (b.dataset.rm) steps.splice(Number(b.dataset.rm), 1);
    if (b.dataset.mv) { const i = Number(b.dataset.i), j = i + Number(b.dataset.mv); if (j >= 0 && j < steps.length) [steps[i], steps[j]] = [steps[j], steps[i]]; }
    draw(); };
  if (x) $("#rdel", d).onclick = async () => { await DEL("routines/" + x.id); d.close(); d.remove(); navigate(); };
}

async function routinePlayer(main, r) {
  const run = await POST(`routines/${r.id}/runs`);
  let i = 0, done = 0, skipped = 0;
  const draw = () => {
    if (i >= r.steps.length) return finish();
    const s = r.steps[i];
    main.innerHTML = html`<div class="card player"><p class="muted">${r.name} · step ${i + 1} of ${r.steps.length}</p>
      <div class="progress" aria-hidden="true"><span style="width:${Math.round(i / r.steps.length * 100)}%"></span></div>
      <div class="step-sym" aria-hidden="true">${s.symbol || "◯"}</div>
      <div class="step-text">${s.text}</div>
      ${s.minutes ? html`<p class="muted">About ${s.minutes} min${s.optional ? " · optional" : ""}</p>` : s.optional ? html`<p class="muted">Optional</p>` : ""}
      ${s.alternative ? html`<p class="hint">Or instead: ${s.alternative}</p>` : ""}
      <div class="row" style="justify-content:center;margin-top:20px"><button class="btn primary" data-act="done">✓ Done</button><button class="btn" data-act="skip">Skip</button>
        ${s.minutes ? html`<button class="btn quiet" data-act="timer">⏱ Timer</button>` : ""}<button class="btn quiet" data-act="say">🔊</button></div>
      <p style="margin-top:28px"><a href="#/routines" class="btn small quiet">Stop here</a></p></div>`.s;
  };
  const finish = async () => {
    const res = await POST(`routines/${r.id}/runs/${run.run_id}/finish`, { done_steps: done, skipped_steps: skipped });
    main.innerHTML = html`<div class="card player"><div class="step-sym">🌿</div><div class="step-text">${res.message}</div><a class="btn" href="#/routines">Back to routines</a></div>`.s;
  };
  bind(main, { done: () => { done++; i++; draw(); }, skip: () => { skipped++; i++; draw(); }, say: () => speak(r.steps[i].text),
    timer: () => { const s = r.steps[i]; let left = s.minutes * 60; const b = $("[data-act=timer]", main);
      const tick = setInterval(() => { left--; if (!b.isConnected) return clearInterval(tick); b.textContent = `⏱ ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`; if (left <= 0) { clearInterval(tick); b.textContent = "⏱ Time's up"; } }, 1000);
      CURRENT.cleanup = () => clearInterval(tick); } });
  draw();
}

/* ============================================================ Check-in + insights */
const SCALES = [
  ["mood", "Mood", ["😞", "🙁", "😐", "🙂", "😄"]], ["energy", "Energy", ["🪫", "😮‍💨", "🙂", "😊", "⚡"]],
  ["stress", "Stress", ["😌", "🙂", "😐", "😣", "🤯"]], ["sensory", "Sensory comfort", ["😖", "😕", "😐", "🙂", "😌"]],
  ["social", "Social energy", ["🫥", "🙁", "😐", "🙂", "🥳"]], ["sleep", "Sleep (optional)", ["😫", "🥱", "😐", "🙂", "😴"]],
];
const NEEDS = ["Quiet", "Food or water", "Rest", "Movement", "Company", "Time alone", "Help with a task", "Less noise", "Dim light", "A hug", "Nothing right now"];
route("checkin", async (main) => {
  const [hist, ins] = await Promise.all([GET("checkins?days=14"), GET("insights")]);
  const picked = {}; const needs = new Set();
  main.innerHTML = html`${head(t("Check-in"), "Tap what fits. Skip anything. Words are optional.")}
    <div class="grid g2"><div class="card"><form data-form="save">
      ${SCALES.map(([k, label, emo]) => html`<div class="field"><div style="font-weight:550;margin-bottom:6px">${label}</div>
        <div class="scale" role="group" aria-label="${label}">${emo.map((e, i) => html`<button type="button" class="choice" data-act="pick" data-k="${k}" data-v="${i + 1}" aria-pressed="false" aria-label="${label} ${i + 1} of 5"><span class="emo" aria-hidden="true">${e}</span>${i + 1}</button>`)}</div></div>`)}
      <label class="check field"><input type="checkbox" name="overwhelmed"> I'm feeling overwhelmed</label>
      <div class="field"><div style="font-weight:550;margin-bottom:6px">What do you need right now?</div><div class="row">${NEEDS.map((n) => html`<button type="button" class="choice" data-act="need" data-n="${n}" aria-pressed="false">${n}</button>`)}</div></div>
      <div class="field"><label for="cn">Anything to add? <span class="hint">(optional, private)</span></label><textarea id="cn" name="note" maxlength="2000"></textarea></div>
      <button class="btn primary">Save check-in</button></form></div>
    <div class="stack">
      <div class="card"><h3>Last 14 days</h3>${hist.checkins.length ? trendBars(hist.checkins) : html`<p class="muted">Your check-ins will show here.</p>`}<p class="hint">${hist.notice}</p></div>
      <div class="card tint-sage"><h3>What seems to help you</h3>
        ${ins.helpful_strategies.length || ins.most_used_cards.length || ins.routines.some((r) => r.runs) ? html`<ul>
          ${ins.helpful_strategies.map((s) => html`<li>You marked <strong>${s.title}</strong> as helpful${s.uses ? ` (used ${s.uses}×)` : ""}.</li>`)}
          ${ins.most_used_cards.map((c) => html`<li>Card “${c.text}” used ${c.uses}×.</li>`)}
          ${ins.routines.filter((r) => r.runs).map((r) => html`<li>Routine “${r.name}”: started ${r.runs}×.</li>`)}</ul>` : html`<p class="muted">As you use NeuroBridge, gentle patterns appear here.</p>`}
        <p class="muted">This week: ${ins.tasks_done_7d} tasks done · ${ins.focus_minutes_7d} focus minutes.</p><p class="hint">${ins.notice}</p></div></div></div>`.s;
  bind(main, {
    pick: (b) => { picked[b.dataset.k] = Number(b.dataset.v); $$(`[data-k=${b.dataset.k}]`, main).forEach((x) => x.setAttribute("aria-pressed", x === b)); },
    need: (b) => { const n = b.dataset.n; needs.has(n) ? needs.delete(n) : needs.add(n); b.setAttribute("aria-pressed", needs.has(n)); },
    save: async (fd) => {
      if (!Object.keys(picked).length && !needs.size && !fd.get("note") && !fd.get("overwhelmed")) throw new Error("Tap at least one thing first.");
      await POST("checkins", { ...picked, needs: [...needs], note: val(fd, "note"), overwhelmed: !!fd.get("overwhelmed") });
      toast("Saved. Thank you for checking in.");
      if (fd.get("overwhelmed")) return openOverwhelm();
      navigate();
    },
  });
});
function trendBars(rows) {
  const keys = [["mood", "Mood", "var(--teal)"], ["energy", "Energy", "var(--blue)"], ["stress", "Stress", "var(--lav)"]];
  return html`${keys.map(([k, l, c]) => { const pts = rows.filter((r) => r[k]).slice(-14); return pts.length ? html`<div style="margin-bottom:10px"><small>${l}</small>
    <div style="display:flex;gap:3px;align-items:flex-end;height:44px" role="img" aria-label="${l}: ${pts.map((p) => p[k]).join(", ")}">${pts.map((p) => html`<span title="${fmtDate(p.created_at)}: ${p[k]}" style="flex:1;max-width:18px;background:${raw(c)};opacity:.8;border-radius:3px 3px 0 0;height:${p[k] * 20}%"></span>`)}</div></div>` : ""; })}`;
}

/* ============================================================ Sensory toolkit */
route("sensory", async (main) => {
  const s = await GET("sensory");
  const vis = s.strategies.filter((x) => x.status !== "removed"), removed = s.strategies.filter((x) => x.status === "removed");
  main.innerHTML = html`${head(t("Sensory toolkit"), "Ideas, not instructions. Keep what helps, hide what doesn't.", html`<button class="btn" data-act="calm">🌊 Calm mode</button>`)}
    <div class="grid gauto">${vis.map((x) => html`<div class="card ${x.status === "liked" ? "tint-sage" : ""}"><span class="chip">${x.group}</span>
      <h3 style="margin-top:8px">${x.title}</h3><p class="muted">${x.how}</p>
      <div class="row"><button class="btn small" data-act="pref" data-k="${x.key}" data-s="${x.status === "liked" ? "neutral" : "liked"}" aria-pressed="${x.status === "liked"}">${x.status === "liked" ? "💚 Helps me" : "♡ This helps"}</button>
        <button class="btn small quiet" data-act="used" data-k="${x.key}">Used it</button>
        <button class="btn small quiet" data-act="pref" data-k="${x.key}" data-s="removed">Hide</button></div>
      ${x.status === "disliked" ? html`<small>Marked as not for you</small>` : ""}</div>`)}</div>
    ${removed.length ? html`<p class="muted" style="margin-top:12px">Hidden: ${removed.map((x) => html`<button class="btn small quiet" data-act="pref" data-k="${x.key}" data-s="neutral">↺ ${x.title}</button>`)}</p>` : ""}
    <div class="grid g2" style="margin-top:20px">
      <div class="card"><h3>My sensory kit</h3><p class="hint">Tick what's packed before you go out.</p>
        <ul class="list">${s.kit.map((k) => html`<li class="item"><label class="check grow"><input type="checkbox" data-act="pack" data-id="${k.id}" ${raw(k.packed ? "checked" : "")}> ${k.item}</label><button class="btn small quiet" data-act="delkit" data-id="${k.id}" aria-label="Remove ${k.item}">✕</button></li>`)}</ul>
        <form data-form="kit" class="row" style="margin-top:8px"><input name="item" type="text" aria-label="Add kit item" placeholder="Add an item" maxlength="100" required style="flex:1"><button class="btn">${t("Add")}</button></form></div>
      <div class="card"><h3>Sensory diary</h3><form data-form="diary">
        <div class="field"><label for="se">Where were you?</label><input id="se" name="environment" type="text" maxlength="500" placeholder="e.g. supermarket on Saturday"></div>
        <div class="field"><label for="sw">What happened? <span class="hint">(optional)</span></label><textarea id="sw" name="what_happened" maxlength="2000" style="min-height:60px"></textarea></div>
        <div class="field"><label for="sh">What helped?</label><input id="sh" name="what_helped" type="text" maxlength="1000"></div>
        <button class="btn">Save note</button></form>
        ${s.diary.length ? html`<ul class="list" style="margin-top:12px">${s.diary.slice(0, 6).map((n) => html`<li><small>${fmtWhen(n.created_at)}</small><div>${n.environment || ""}${n.what_helped ? html` — <em>helped: ${n.what_helped}</em>` : ""}</div></li>`)}</ul>` : ""}</div></div>`.s;
  bind(main, {
    calm: openOverwhelm,
    pref: async (b) => { await PUT("sensory/strategies/" + b.dataset.k, { status: b.dataset.s }); navigate(); },
    used: async (b) => { const x = s.strategies.find((y) => y.key === b.dataset.k); await PUT("sensory/strategies/" + b.dataset.k, { status: x.status === "neutral" ? "liked" : x.status, used: true }); toast("Noted."); },
    pack: async (b) => { await PATCH(`sensory/kit/${b.dataset.id}?packed=${b.checked}`); },
    delkit: async (b) => { await DEL("sensory/kit/" + b.dataset.id); navigate(); },
    kit: async (fd) => { await POST("sensory/kit", { item: val(fd, "item") }); navigate(); },
    diary: async (fd) => { await POST("sensory/diary", { environment: val(fd, "environment"), what_happened: val(fd, "what_happened"), what_helped: val(fd, "what_helped") }); toast("Saved."); navigate(); },
  });
  // checkboxes inside bind: click handler runs before state change completes — use change instead
  $$("[data-act=pack]", main).forEach((c) => { c.removeAttribute("data-act"); c.onchange = () => PATCH(`sensory/kit/${c.dataset.id}?packed=${c.checked}`).catch(fail); });
});

/* ============================================================ Communication cards */
route("communicate", async (main) => {
  const r = await GET("cards"); const cats = {}; let showHidden = false;
  const draw = () => {
    Object.keys(cats).forEach((k) => delete cats[k]);
    r.cards.filter((c) => showHidden || !c.hidden).forEach((c) => (cats[c.favorite ? "★ Favourites" : c.category] ||= []).push(c));
    main.innerHTML = html`${head(t("Communication"), "Tap a card to show it full-screen or say it out loud.",
        html`<button class="btn primary" data-act="new">+ My own card</button><button class="btn quiet" data-act="hidden">${showHidden ? "Hide hidden cards" : "Show hidden cards"}</button>`)}
      ${Object.entries(cats).sort(([a], [b]) => (a.startsWith("★") ? -1 : b.startsWith("★") ? 1 : a.localeCompare(b))).map(([cat, list]) => html`<h2 style="margin:20px 0 10px">${cat}</h2>
        <div class="cards-grid">${list.map((c) => html`<div style="position:relative">
          <button class="comm-card" data-act="show" data-id="${c.id}" style="${c.hidden ? "opacity:.5" : ""}"><span class="sym" aria-hidden="true">${c.symbol || "💬"}</span><span class="txt">${c.text}</span></button>
          <div class="row" style="position:absolute;top:6px;right:6px;gap:0">
            <button class="btn small quiet" data-act="fav" data-id="${c.id}" aria-label="${c.favorite ? "Remove from favourites" : "Add to favourites"}: ${c.text}">${c.favorite ? "★" : "☆"}</button>
            <button class="btn small quiet" data-act="edit" data-id="${c.id}" aria-label="Edit card: ${c.text}">⋯</button></div></div>`)}</div>`)}`.s;
  };
  const find = (id) => r.cards.find((c) => c.id === Number(id));
  const refresh = async () => { r.cards = (await GET("cards")).cards; draw(); };
  bind(main, {
    show: (b) => { const c = find(b.dataset.id); PATCH("cards/" + c.id, { used: true }).catch(() => {});
      const el = document.createElement("div"); el.className = "big-card"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", c.text);
      el.innerHTML = html`<div class="sym" aria-hidden="true">${c.symbol || "💬"}</div><div class="txt">${c.text}</div>
        <div class="row"><button class="btn primary" data-b="say">🔊 Say it</button><button class="btn" data-b="close">Close</button></div>`.s;
      document.body.appendChild(el); $("[data-b=say]", el).focus();
      const close = () => { el.remove(); document.removeEventListener("keydown", k); }; const k = (e) => e.key === "Escape" && close();
      document.addEventListener("keydown", k);
      el.onclick = (e) => { const x = e.target.closest("[data-b]"); if (!x) return; x.dataset.b === "say" ? speak(c.text) : close(); };
      if (S.prefs.tts) speak(c.text); },
    fav: async (b) => { const c = find(b.dataset.id); await PATCH("cards/" + c.id, { favorite: !c.favorite }); await refresh(); },
    hidden: () => { showHidden = !showHidden; draw(); },
    new: () => cardEditor(null, refresh), edit: (b) => cardEditor(find(b.dataset.id), refresh),
  });
  draw();
});
function cardEditor(c, refresh) {
  const d = dialog({ title: c ? "Edit card" : "New card", body: html`
    <div class="field"><label for="ct">What it says</label><input id="ct" name="text" type="text" maxlength="200" value="${c?.text || ""}" required></div>
    <div class="grid g2"><div class="field"><label for="cc">Category</label><input id="cc" name="category" type="text" maxlength="40" value="${c?.category || "My cards"}"></div>
    <div class="field"><label for="cs">Symbol or emoji</label><input id="cs" name="symbol" type="text" maxlength="8" value="${c?.symbol || ""}" placeholder="🙂"></div></div>
    ${c ? html`<div class="row"><button type="button" class="btn small" id="chide">${c.hidden ? "Unhide" : "Hide"}</button><button type="button" class="btn small danger" id="cdel">Delete</button></div>` : ""}`,
    onOk: async (fd) => { const body = { text: val(fd, "text"), category: val(fd, "category") || "My cards", symbol: val(fd, "symbol") }; c ? await PATCH("cards/" + c.id, body) : await POST("cards", body); await refresh(); } });
  if (c) { $("#chide", d).onclick = async () => { await PATCH("cards/" + c.id, { hidden: !c.hidden }); d.close(); d.remove(); refresh(); };
    $("#cdel", d).onclick = async () => { await DEL("cards/" + c.id); d.close(); d.remove(); refresh(); }; }
}

/* ============================================================ Journal */
route("journal", async (main, q = "") => {
  const r = await GET("journal" + (q ? "?q=" + encodeURIComponent(decodeURIComponent(q)) : ""));
  main.innerHTML = html`${head(t("Journal"), r.privacy, html`<button class="btn primary" data-act="new">+ New entry</button>`)}
    <form data-form="search" class="row" style="margin-bottom:16px"><label class="sr-only" for="jq">Search journal</label><input id="jq" name="q" type="search" placeholder="Search your journal" value="${decodeURIComponent(q)}" style="flex:1"><button class="btn">Search</button></form>
    ${r.entries.length ? html`<div class="stack">${r.entries.map((e) => html`<article class="card">
        <div class="card-head"><div><h3>${e.title || fmtDate(e.created_at)}</h3><small>${fmtWhen(e.created_at)} · ${e.kind}</small></div>
          <div class="row"><button class="btn small quiet" data-act="reflect" data-id="${e.id}">✨ Reflect</button><button class="btn small quiet" data-act="edit" data-id="${e.id}">Edit</button></div></div>
        <div style="white-space:pre-wrap">${e.body}</div>
        ${e.tags.length ? html`<div class="row" style="margin-top:8px">${e.tags.map((t2) => html`<span class="chip">#${t2}</span>`)}</div>` : ""}</article>`)}</div>`
      : html`<div class="card">${emptyState("📓", q ? "Nothing found" : "Your private space", q ? "Try another word." : "Write a thought, a win, a hard moment — or nothing at all.")}</div>`}`.s;
  bind(main, {
    search: (fd) => { location.hash = "#/journal/" + encodeURIComponent(fd.get("q") || ""); },
    new: () => journalEditor(null), edit: (b) => journalEditor(r.entries.find((e) => e.id === Number(b.dataset.id))),
    reflect: async (b) => {
      const ok = await confirmDlg("Ask the AI to reflect?", "This entry will be sent to the AI model to write a short, gentle reflection. The reflection isn't saved and nobody else sees it.", "Reflect");
      if (!ok) return; const res = await POST("assistant/reflect", { journal_id: Number(b.dataset.id) });
      dialog({ title: "A gentle reflection", okText: "", cancelText: "Close", body: html`${md(res.reflection)}<p class="hint">AI-written (${res.provider || "AI"}). It may be wrong — you know yourself best.</p>` });
    },
  });
});
function journalEditor(e) {
  const kinds = ["thought", "experience", "feeling", "sensory", "accomplishment", "challenge", "reflection"];
  const d = dialog({ title: e ? "Edit entry" : "New entry", wide: true, body: html`
    <div class="grid g2"><div class="field"><label for="jt">Title (optional)</label><input id="jt" name="title" type="text" maxlength="200" value="${e?.title || ""}"></div>
    <div class="field"><label for="jk">Kind</label><select id="jk" name="kind">${kinds.map((k) => html`<option ${raw(e?.kind === k ? "selected" : "")}>${k}</option>`)}</select></div></div>
    <div class="field"><label for="jb">Write anything</label><textarea id="jb" name="body" style="min-height:200px" required maxlength="20000">${e?.body || ""}</textarea>
      <button type="button" class="btn small quiet" id="jmic">🎙 Speak instead</button></div>
    <div class="field"><label for="jg">Tags <span class="hint">(comma separated)</span></label><input id="jg" name="tags" type="text" value="${(e?.tags || []).join(", ")}"></div>
    ${e ? html`<button type="button" class="btn small danger" id="jdel">Delete entry</button>` : ""}`,
    onOk: async (fd) => { const body = { title: val(fd, "title"), body: fd.get("body"), kind: fd.get("kind"), tags: String(fd.get("tags") || "").split(",").map((x) => x.trim()).filter(Boolean) };
      e ? await PUT("journal/" + e.id, body) : await POST("journal", body); navigate(); } });
  $("#jmic", d).onclick = () => listen((txt) => { const ta = $("#jb", d); ta.value = (ta.value ? ta.value + " " : "") + txt; });
  if (e) $("#jdel", d).onclick = async () => { if (await confirmDlg("Delete this entry?", "This can't be undone.", "Delete", true)) { await DEL("journal/" + e.id); d.close(); d.remove(); navigate(); } };
}

/* ============================================================ Support Blueprint */
route("blueprint", async (main) => {
  const r = await GET("blueprint");
  main.innerHTML = html`${head(t("Support Blueprint"), "A living guide to you — in your words. You decide which parts your circle can see.",
      html`<button class="btn" data-act="export">⬇ Export</button><a class="btn quiet" href="#/circle">Who can see it?</a>`)}
    <div class="alert info">Sections marked <strong>Shared</strong> are visible only to people in your circle you've given “Blueprint” access. Everything else stays private.</div>
    <div class="grid g2">${r.sections.map((s) => html`<form class="card" data-form="save" data-s="${s.section}">
      <div class="card-head"><h3><label for="bp-${s.section}">${s.title}</label></h3>${s.shared ? html`<span class="chip blue">Shared</span>` : html`<span class="chip">Private</span>`}</div>
      <textarea id="bp-${s.section}" name="content" maxlength="5000">${s.content}</textarea>
      <div class="row between" style="margin-top:8px"><label class="check" style="margin:0"><input type="checkbox" name="shared" ${raw(s.shared ? "checked" : "")}> Share</label>
        <button class="btn small">${t("Save")}</button></div>${s.updated_at ? html`<small>Updated ${fmtDate(s.updated_at)}</small>` : ""}</form>`)}</div>`.s;
  bind(main, {
    save: async (fd, f) => { await PUT("blueprint/" + f.dataset.s, { content: fd.get("content") || "", shared: !!fd.get("shared") }); toast("Saved."); navigate(); },
    export: async () => { const ex = await GET("blueprint/export"); const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([ex.markdown], { type: "text/markdown" })); a.download = "my-support-blueprint.md"; a.click(); },
  });
});

/* ============================================================ Goals */
route("goals", async (main) => {
  const r = await GET("goals");
  const st = { active: ["Active", "teal"], paused: ["Paused", "amber"], achieved: ["Achieved", "sage"], dropped: ["Let go", ""] };
  main.innerHTML = html`${head(t("Goals"), "Goals you choose, at your pace. Pausing or letting go of a goal is a valid choice.", html`<button class="btn primary" data-act="new">+ New goal</button>`)}
    ${r.goals.length ? html`<div class="grid g2">${r.goals.map((g) => html`<div class="card"><div class="card-head"><h3>${g.title}</h3><span class="chip ${st[g.status][1]}">${st[g.status][0]}</span></div>
      ${g.why ? html`<p class="muted">Why: ${g.why}</p>` : ""}${g.next_step ? html`<p><strong>Next small step:</strong> ${g.next_step}</p>` : ""}
      <div class="row">${g.shared ? html`<span class="chip blue">Shared</span>` : ""}<button class="btn small" data-act="edit" data-id="${g.id}">Edit</button>
      <a class="btn small quiet" href="#/assistant/new/${encodeURIComponent("Help me break my goal '" + g.title + "' into small steps.")}">✨ Break it down</a></div></div>`)}</div>`
      : html`<div class="card">${emptyState("🎯", "No goals yet", "Something you'd like to learn, do, or change? Write it here — tiny goals count.")}</div>`}`.s;
  bind(main, { new: () => goalEditor(null), edit: (b) => goalEditor(r.goals.find((g) => g.id === Number(b.dataset.id))) });
});
function goalEditor(g) {
  const d = dialog({ title: g ? "Edit goal" : "New goal", body: html`
    <div class="field"><label for="gt">Goal</label><input id="gt" name="title" type="text" maxlength="200" value="${g?.title || ""}" required></div>
    <div class="field"><label for="gw">Why it matters to me (optional)</label><textarea id="gw" name="why" maxlength="1000">${g?.why || ""}</textarea></div>
    <div class="field"><label for="gn">Next small step</label><input id="gn" name="next_step" type="text" maxlength="300" value="${g?.next_step || ""}"></div>
    ${g ? html`<div class="field"><label for="gs">Status</label><select id="gs" name="status">${[["active", "Active"], ["paused", "Paused"], ["achieved", "Achieved"], ["dropped", "Let go"]].map(([v, l]) => html`<option value="${v}" ${raw(g.status === v ? "selected" : "")}>${l}</option>`)}</select></div>` : ""}
    ${isInd() ? html`<label class="check"><input type="checkbox" name="shared" ${raw(g?.shared ? "checked" : "")}> Share with my circle (people with "Goals" access)</label>` : ""}
    ${g ? html`<p style="margin-top:12px"><button type="button" class="btn small danger" id="gdel">Delete</button></p>` : ""}`,
    onOk: async (fd) => { const body = { title: val(fd, "title"), why: val(fd, "why"), next_step: val(fd, "next_step"), status: fd.get("status") || "active", shared: !!fd.get("shared") };
      g ? await PUT("goals/" + g.id, body) : await POST("goals", body); navigate(); } });
  if (g) $("#gdel", d).onclick = async () => { await DEL("goals/" + g.id); d.close(); d.remove(); navigate(); };
}

/* ============================================================ Learn & life skills */
route("learn", async (main, q = "") => {
  const [l, s] = await Promise.all([GET("learn" + (q ? "?q=" + q : "")), GET("life-skills")]);
  const ask = (p, mode = "chat") => `#/assistant/new/${encodeURIComponent(p)}/${mode}`;
  main.innerHTML = html`${head(isCare() ? t("Learning hub") : t("Learn & life skills"), "Short, plain guides — and an assistant that can research any topic with sources.")}
    <form class="row" data-form="s" style="margin-bottom:16px"><label class="sr-only" for="lq">Search topics</label><input id="lq" name="q" type="search" placeholder="Search topics (e.g. transitions, burnout)" value="${decodeURIComponent(q)}" style="flex:1"><button class="btn">Search</button></form>
    <div class="alert info">${l.notice}</div>
    <div class="grid g2">${l.topics.map((x) => html`<article class="card"><h3>${x.title}</h3><p>${x.summary}</p>
      <p class="hint">Read more: ${x.links.map(([n, u], i) => html`${i ? " · " : ""}<a href="${u}" target="_blank" rel="noopener noreferrer">${n}</a>`)}</p>
      <div class="row"><a class="btn small" href="${ask("Research with sources: " + x.title + (isCare() ? " — practical, respectful ways caregivers can help" : " — practical tips"), "agent")}">🔎 Research this (with sources)</a>
      <a class="btn small quiet" href="${ask("Explain " + x.title + " simply, and what might help me.")}">✨ Ask</a></div></article>`)}</div>
    <h2 style="margin-top:28px">${isCare() ? "Practical guides" : "Life skills, study & work"}</h2>
    <div class="grid gauto">${s.skills.map((x) => html`<a class="card soft" style="text-decoration:none;color:inherit" href="${ask(x.prompt)}"><h3>${x.title}</h3><p class="muted">${x.prompt}</p></a>`)}</div>`.s;
  bind(main, { s: (fd) => { location.hash = "#/learn/" + encodeURIComponent(fd.get("q") || ""); } });
});
