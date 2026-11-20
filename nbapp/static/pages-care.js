/* NeuroBridge — caregiver pages, circle & consent, calendar, providers, settings. */
"use strict";

const SCOPE_ICON = { blueprint: "🧭", routines: "🔁", calendar: "📆", goals: "🎯", tasks: "✅", checkin_summary: "🌤", coordination: "🧩" };
async function myPeople() { S.people = (await GET("circle")).links.filter((l) => l.status === "active"); return S.people; }
const personPicker = (people, selected, name = "person") => html`<label class="sr-only" for="pp">Person</label>
  <select id="pp" name="${name}" data-pick>${people.map((p) => html`<option value="${p.individual_id}" ${raw(Number(selected) === p.individual_id ? "selected" : "")}>${p.display_name}</option>`)}</select>`;
const noPeople = () => html`<div class="card">${emptyState("🫶", "No one connected yet", "Invite the person you support from Settings → My circle. They choose what to share with you.", html`<a class="btn primary" href="#/circle">Invite someone</a>`)}</div>`;

/* ============================================================ caregiver dashboard */
route("carehome", async (main) => {
  const d = await GET("care/dashboard");
  const active = d.people.filter((p) => p.status === "active"), pending = d.people.filter((p) => p.status === "pending");
  main.innerHTML = html`${head(`Hello, ${S.user.display_name}`, "An overview of what's shared with you and what needs you today.", html`<a class="btn" href="#/assistant">✨ Care assistant</a>`)}
    ${d.support_requests.length ? html`<div class="card" style="border:2px solid var(--lav);margin-bottom:16px"><h3>🔔 Support requests</h3><ul class="list">${d.support_requests.map((r) => html`<li class="item">
      <div class="grow"><div class="item-title">${r.other_name}: “${r.message}”</div><small>${fmtWhen(r.created_at)} · ${r.status.replace(/_/g, " ")}</small></div>
      <div class="row"><button class="btn small" data-act="sr" data-id="${r.id}" data-s="seen">Seen</button><button class="btn small primary" data-act="sr" data-id="${r.id}" data-s="on_my_way">On my way</button><button class="btn small quiet" data-act="sr" data-id="${r.id}" data-s="resolved">Done</button></div></li>`)}</ul></div>` : ""}
    <div class="grid g2">
      <div class="card"><div class="card-head"><h3>People I support</h3><a class="btn small quiet" href="#/circle">Manage →</a></div>
        ${active.length ? html`<ul class="list">${active.map((p) => html`<li class="item"><div class="grow"><div class="item-title">${p.display_name}${p.is_guardian ? html` <span class="chip amber">Guardian</span>` : ""}</div>
          <small>Shared with you: ${Object.entries(p.permissions).filter(([, s]) => s === "granted").map(([k]) => k.replace("_", " ")).join(", ") || "nothing yet"}</small></div>
          <a class="btn small" href="#/people/${p.individual_id}">Open</a></li>`)}</ul>` : html`<p class="muted">No one connected yet.</p>`}
        ${pending.length ? html`<p class="hint">${pending.length} invitation(s) pending.</p>` : ""}</div>
      <div class="card"><div class="card-head"><h3>My care tasks</h3><a class="btn small quiet" href="#/coordination">Coordination →</a></div>
        ${d.my_care_tasks.length ? html`<ul class="list">${d.my_care_tasks.map((x) => html`<li class="item"><div class="grow"><div class="item-title">${x.title}</div><small>For ${x.person}${x.due_date ? " · " + fmtDate(x.due_date) : ""}</small></div><button class="btn small" data-act="ct" data-id="${x.id}">Done</button></li>`)}</ul>` : html`<p class="muted">Nothing assigned to you.</p>`}</div>
      <div class="card"><div class="card-head"><h3>Coming up</h3><a class="btn small quiet" href="#/calendar">Calendar →</a></div>
        ${d.upcoming.length ? html`<ul class="list">${d.upcoming.map((e) => html`<li><div class="item-title">${e.title}</div><small>${fmtWhen(e.start_time)}</small></li>`)}</ul>` : html`<p class="muted">Nothing scheduled.</p>`}</div>
      <div class="card tint-sage"><h3>And you?</h3><p>${d.last_wellbeing ? `Last check-in ${fmtDate(d.last_wellbeing.created_at)}.` : "Caring is work. How are you doing?"}</p><a class="btn" href="#/wellbeing">🌿 Wellbeing check-in</a></div>
    </div>`.s;
  bind(main, {
    sr: async (b) => { await PATCH("support-requests/" + b.dataset.id, { status: b.dataset.s }); toast("They've been told."); navigate(); },
    ct: async (b) => { await PATCH(`care/tasks/${b.dataset.id}?status=done`); navigate(); },
  });
});

/* ============================================================ support requests */
route("requests", async (main) => {
  const r = await GET("support-requests");
  main.innerHTML = html`${head(t("Support requests"), isInd() ? "Messages you've sent to your circle." : "Requests from the people you support.")}
    <div class="card">${r.requests.length ? html`<ul class="list">${r.requests.map((x) => html`<li class="item"><div class="grow">
      <div class="item-title">${isInd() ? "To " + x.other_name : x.other_name}: “${x.message}”</div>
      <small>${fmtWhen(x.created_at)} · <span class="chip ${x.status === "resolved" ? "sage" : "lav"}">${x.status.replace(/_/g, " ")}</span>${x.reply ? " · " + x.reply : ""}</small></div>
      ${isCare() && x.status !== "resolved" ? html`<div class="row"><button class="btn small" data-act="s" data-id="${x.id}" data-s="seen">Seen</button><button class="btn small primary" data-act="s" data-id="${x.id}" data-s="on_my_way">On my way</button><button class="btn small quiet" data-act="s" data-id="${x.id}" data-s="resolved">Done</button></div>` : ""}</li>`)}</ul>`
      : emptyState("🔔", "No requests", isInd() ? "From My circle you can send a quick message like “I need quiet”." : "When someone you support asks for help, it appears here and on your dashboard.")}</div>`.s;
  bind(main, { s: async (b) => { await PATCH("support-requests/" + b.dataset.id, { status: b.dataset.s }); navigate(); } });
});

/* ============================================================ shared support view */
route("people", async (main, pid) => {
  const people = await myPeople(); if (!people.length) { main.innerHTML = head(t("People I support")).s + noPeople().s; return; }
  pid = Number(pid || people[0].individual_id);
  const v = await GET("shared/" + pid); const link = people.find((p) => p.individual_id === pid);
  const sec = v.sections;
  main.innerHTML = html`${head(t("People I support"), "You only see what this person chose to share. Ask for more — they decide.", personPicker(people, pid))}
    <div class="card soft" style="margin-bottom:16px"><h3>What ${v.person.display_name} shares with you</h3><div class="row">
      ${Object.entries(link.permissions_meta || {}).length ? "" : ""}
      ${Object.keys(SCOPE_ICON).map((k) => { const st = link.permissions[k]; return html`<span class="chip ${st === "granted" ? "teal" : st === "requested" ? "amber" : ""}">${SCOPE_ICON[k]} ${k.replace("_", " ")}: ${st === "granted" ? "shared" : st === "requested" ? "asked" : "not shared"}</span>
        ${st !== "granted" && st !== "requested" ? html`<button class="btn small quiet" data-act="ask" data-link="${link.id}" data-scope="${k}">Ask</button>` : ""}`; })}</div>
      <p class="hint">Their journal, check-in notes, AI chats and memories are never shareable.</p></div>
    <div class="grid g2">
      ${sec.blueprint ? html`<div class="card" style="grid-column:1/-1"><h3>🧭 Support Blueprint</h3>${sec.blueprint.length ? html`<div class="grid g2">${sec.blueprint.map((s) => html`<div><h4>${s.title}</h4><p style="white-space:pre-wrap">${s.content}</p></div>`)}</div>` : html`<p class="muted">No sections shared yet.</p>`}</div>` : ""}
      ${sec.routines ? html`<div class="card"><h3>🔁 Routines</h3>${sec.routines.length ? sec.routines.map((r) => html`<h4>${r.name}${r.reminder_time ? " · " + r.reminder_time : ""}</h4><ol>${r.steps.map((s) => html`<li>${s.text}</li>`)}</ol>`) : html`<p class="muted">None shared.</p>`}</div>` : ""}
      ${sec.calendar ? html`<div class="card"><h3>📆 Upcoming</h3>${sec.calendar.length ? html`<ul class="list">${sec.calendar.map((e) => html`<li><div class="item-title">${e.title}</div><small>${fmtWhen(e.start_time)}${e.location ? " · " + e.location : ""}</small></li>`)}</ul>` : html`<p class="muted">Nothing shared.</p>`}</div>` : ""}
      ${sec.goals ? html`<div class="card"><h3>🎯 Goals</h3>${sec.goals.length ? html`<ul>${sec.goals.map((g) => html`<li><strong>${g.title}</strong> (${g.status})${g.next_step ? " — next: " + g.next_step : ""}</li>`)}</ul>` : html`<p class="muted">None shared.</p>`}</div>` : ""}
      ${sec.tasks ? html`<div class="card"><h3>✅ Tasks</h3>${sec.tasks.length ? html`<ul>${sec.tasks.map((x) => html`<li>${x.title} <small>(${x.status})</small></li>`)}</ul>` : html`<p class="muted">None shared.</p>`}</div>` : ""}
      ${sec.checkin_summary ? html`<div class="card"><h3>🌤 Check-in summary (7 days)</h3><p>${sec.checkin_summary.count_7d} check-ins · mood ${sec.checkin_summary.mood_avg ?? "–"} · energy ${sec.checkin_summary.energy_avg ?? "–"} · stress ${sec.checkin_summary.stress_avg ?? "–"} <small>(1–5)</small></p><p class="hint">${sec.checkin_summary.notice} Not a diagnosis.</p></div>` : ""}
      ${sec.coordination ? html`<div class="card tint-blue"><h3>🧩 Coordination</h3><p>Shared care tasks and notes.</p><a class="btn" href="#/coordination/${pid}">Open coordination</a></div>` : ""}
    </div>
    ${!Object.keys(sec).length ? html`<div class="card">${emptyState("🔒", "Nothing shared yet", "That's their choice. You can ask for access above — they'll get a notification and decide.")}</div>` : ""}
    <p style="margin-top:16px"><a class="btn" href="#/assistant/new/${encodeURIComponent("How can I best support " + v.person.display_name + " this week, based on what they've shared?")}">✨ Ask the assistant about supporting ${v.person.display_name}</a></p>`.s;
  $("[data-pick]", main).onchange = (e) => { location.hash = "#/people/" + e.target.value; };
  bind(main, { ask: async (b) => { await PUT(`circle/${b.dataset.link}/scopes/${b.dataset.scope}`, { state: "requested" }); toast("Asked. They'll decide."); navigate(); } });
});

/* ============================================================ coordination */
route("coordination", async (main, pid) => {
  let people = isInd() ? [{ individual_id: S.user.id, display_name: "Me" }] : (await myPeople()).filter((p) => p.permissions.coordination === "granted");
  if (!people.length) { main.innerHTML = html`${head(t("Coordination"), "Share care tasks and handover notes across the support team.")}<div class="card">${emptyState("🧩", "Coordination isn't shared yet", "Coordination opens when the person gives you the “Coordination” permission. You can ask from People I support.", html`<a class="btn" href="#/people">People I support</a>`)}</div>`.s; return; }
  pid = Number(pid || people[0].individual_id);
  const c = await GET("care/coordination/" + pid);
  main.innerHTML = html`${head(t("Coordination"), "Who's doing what, and notes so nobody has to repeat themselves.", isCare() ? personPicker(people, pid) : "")}
    <div class="grid g2"><div class="card"><h3>Care tasks</h3>
      <form data-form="task" class="grid" style="grid-template-columns:2fr 1fr 1fr auto;align-items:end;margin-bottom:12px">
        <div><label for="ctt">Task</label><input id="ctt" name="title" type="text" required maxlength="200" placeholder="e.g. Pick up from school Thu"></div>
        <div><label for="cta">Who</label><select id="cta" name="assignee_id"><option value="">Anyone</option>${c.team.map((m) => html`<option value="${m.id}">${m.display_name}</option>`)}</select></div>
        <div><label for="ctd">When</label><input id="ctd" name="due_date" type="date"></div><button class="btn primary">${t("Add")}</button></form>
      ${c.tasks.length ? html`<ul class="list">${c.tasks.map((x) => html`<li class="item ${x.status === "done" ? "done" : ""}"><div class="grow"><div class="item-title">${x.title}</div><small>${x.assignee || "Unassigned"}${x.due_date ? " · " + fmtDate(x.due_date) : ""}</small></div>
        <button class="btn small" data-act="tog" data-id="${x.id}" data-s="${x.status === "done" ? "open" : "done"}">${x.status === "done" ? "Reopen" : "Done"}</button></li>`)}</ul>` : html`<p class="muted">No care tasks yet.</p>`}
      ${Object.keys(c.open_task_load).length ? html`<p class="hint">Open tasks: ${Object.entries(c.open_task_load).map(([n, k]) => `${n} ${k}`).join(" · ")} — share the load if one person has too much.</p>` : ""}</div>
    <div class="card"><h3>Notes & handovers</h3><form data-form="note"><div class="field"><label for="nb">New note</label><textarea id="nb" name="body" required maxlength="4000" placeholder="e.g. Slept badly; headphones helped at lunch."></textarea></div>
      <div class="row between"><label class="check" style="margin:0"><input type="checkbox" name="handover"> This is a handover</label><button class="btn primary">${t("Add")}</button></div></form>
      ${c.notes.length ? html`<ul class="list" style="margin-top:12px">${c.notes.map((n) => html`<li><div class="row"><strong>${n.author}</strong>${n.kind === "handover" ? html`<span class="chip amber">Handover</span>` : ""}<small>${fmtWhen(n.created_at)}</small></div><div style="white-space:pre-wrap">${n.body}</div></li>`)}</ul>` : ""}
      <p class="hint">Visible to ${isInd() ? "you and the supporters you gave Coordination access" : "the person and others in their team"}.</p></div>
    <div class="card"><h3>Support team</h3><ul>${c.team.map((m) => html`<li>${m.display_name} <small>(${m.role})</small></li>`)}</ul></div></div>`.s;
  $("[data-pick]", main)?.addEventListener("change", (e) => { location.hash = "#/coordination/" + e.target.value; });
  bind(main, {
    task: async (fd) => { await POST("care/tasks", { individual_id: pid, title: val(fd, "title"), assignee_id: fd.get("assignee_id") ? Number(fd.get("assignee_id")) : null, due_date: val(fd, "due_date") }); navigate(); },
    tog: async (b) => { await PATCH(`care/tasks/${b.dataset.id}?status=${b.dataset.s}`); navigate(); },
    note: async (fd) => { await POST("care/notes", { individual_id: pid, body: fd.get("body"), kind: fd.get("handover") ? "handover" : "note" }); navigate(); },
  });
});

/* ============================================================ care journal */
route("carejournal", async (main, pid) => {
  if (isInd()) {
    const r = await GET("care/journal");
    main.innerHTML = html`${head("Notes shared with me", "Observations your supporters chose to show you.")}<div class="card">${r.entries.length ? html`<ul class="list">${r.entries.map((e) => html`<li><strong>${e.author}</strong> <small>${fmtWhen(e.occurred_at)}</small><p>${e.what_happened}</p></li>`)}</ul>` : emptyState("📝", "Nothing shared", "If a supporter shares an observation with you, it appears here.")}</div>`.s; return;
  }
  const people = await myPeople(); pid = pid ? Number(pid) : "";
  const [r, pat] = await Promise.all([GET("care/journal" + (pid ? "?individual_id=" + pid : "")), GET("care/journal/patterns" + (pid ? "?individual_id=" + pid : ""))]);
  main.innerHTML = html`${head(t("Care journal"), "Your own observations. Private to you unless you choose to show one to the person it's about.",
      html`<button class="btn primary" data-act="new">+ New observation</button>`)}
    ${people.length ? html`<div class="row" style="margin-bottom:12px"><label for="cjp">Show:</label><select id="cjp" style="width:auto" data-pick2><option value="">Everyone</option>${people.map((p) => html`<option value="${p.individual_id}" ${raw(pid === p.individual_id ? "selected" : "")}>${p.display_name}</option>`)}</select></div>` : ""}
    <div class="grid g2"><div class="card" style="grid-column:span 1">${r.entries.length ? html`<ul class="list">${r.entries.map((e) => html`<li><div class="row between"><strong>${fmtWhen(e.occurred_at)}</strong>
        <div class="row">${e.visible_to_individual ? html`<span class="chip blue">Shown to them</span>` : ""}<button class="btn small quiet" data-act="del" data-id="${e.id}" aria-label="Delete observation">✕</button></div></div>
        ${e.context ? html`<small>Context: ${e.context}${e.environment ? " · " + e.environment : ""}</small>` : ""}<p style="margin:4px 0">${e.what_happened}</p>
        ${e.support_offered ? html`<small>Support offered: ${e.support_offered}</small><br>` : ""}${e.what_helped ? html`<small>Seemed to help: ${e.what_helped}</small><br>` : ""}
        ${e.followup ? html`<small>Follow-up: ${e.followup}</small>` : ""}${e.tags.length ? html`<div class="row">${e.tags.map((x) => html`<span class="chip">#${x}</span>`)}</div>` : ""}</li>`)}</ul>`
      : emptyState("📝", "No observations yet", "Notes about what happened, what was going on around it, and what helped. Facts first, guesses labelled as guesses.")}</div>
    <div class="card tint-lav"><h3>Possible patterns</h3>${pat.items.length ? html`<ul>${pat.items.map((x) => html`<li>${x}</li>`)}</ul>` : html`<p class="muted">Patterns need more notes. (${pat.observations} so far.)</p>`}<p class="hint">${pat.notice}</p></div></div>`.s;
  $("[data-pick2]", main)?.addEventListener("change", (e) => { location.hash = "#/carejournal/" + e.target.value; });
  bind(main, {
    del: async (b) => { if (await confirmDlg("Delete this observation?", "This can't be undone.", "Delete", true)) { await DEL("care/journal/" + b.dataset.id); navigate(); } },
    new: () => dialog({ title: "New observation", wide: true, body: html`
      <div class="grid g2"><div class="field"><label for="op">About</label><select id="op" name="individual_id"><option value="">(not linked to a person)</option>${people.map((p) => html`<option value="${p.individual_id}" ${raw(pid === p.individual_id ? "selected" : "")}>${p.display_name}</option>`)}</select></div>
      <div class="field"><label for="ow">When</label><input id="ow" name="occurred_at" type="datetime-local" value="${new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16)}"></div></div>
      <div class="grid g2"><div class="field"><label for="oc">Context</label><input id="oc" name="context" type="text" placeholder="e.g. after school" maxlength="500"></div>
      <div class="field"><label for="oe">Environment</label><input id="oe" name="environment" type="text" placeholder="e.g. busy, loud kitchen" maxlength="500"></div></div>
      <div class="field"><label for="oh">What happened</label><textarea id="oh" name="what_happened" required maxlength="5000"></textarea></div>
      <div class="field"><label for="of">Possible contributing factors <span class="hint">(guesses — label them as guesses)</span></label><input id="of" name="factors" type="text" maxlength="2000"></div>
      <div class="grid g2"><div class="field"><label for="os">Support offered</label><input id="os" name="support_offered" type="text" maxlength="2000"></div>
      <div class="field"><label for="oo">What seemed to help</label><input id="oo" name="what_helped" type="text" maxlength="2000"></div></div>
      <div class="field"><label for="ou">Follow-up</label><input id="ou" name="followup" type="text" maxlength="2000"></div>
      <div class="field"><label for="ot">Tags <span class="hint">(comma separated, e.g. noise, transition)</span></label><input id="ot" name="tags" type="text"></div>
      <label class="check"><input type="checkbox" name="visible"> Show this note to the person it's about</label>`,
      onOk: async (fd) => { await POST("care/journal", { individual_id: fd.get("individual_id") ? Number(fd.get("individual_id")) : null, occurred_at: fd.get("occurred_at") ? fd.get("occurred_at") + ":00" : null,
        context: val(fd, "context"), environment: val(fd, "environment"), what_happened: fd.get("what_happened"), factors: val(fd, "factors"), support_offered: val(fd, "support_offered"),
        what_helped: val(fd, "what_helped"), followup: val(fd, "followup"), tags: String(fd.get("tags") || "").split(",").map((x) => x.trim()).filter(Boolean), visible_to_individual: !!fd.get("visible") }); navigate(); } }),
  });
});

/* ============================================================ calendar (both roles) */
route("calendar", async (main) => {
  const r = await GET("calendar"); const people = isCare() ? await myPeople() : [];
  const byDay = {}; r.events.forEach((e) => (byDay[e.start_time.slice(0, 10)] ||= []).push(e));
  main.innerHTML = html`${head(isCare() ? t("Care calendar") : "Calendar", isCare() ? "Your events plus anything the people you support chose to share." : "Your events. Tick “share” to let your circle see one.",
      html`<button class="btn primary" data-act="new">+ Add event</button>`)}
    <div class="card">${Object.keys(byDay).length ? Object.entries(byDay).map(([d, list]) => html`<div class="calendar-day">${fmtDate(d)}${d === today() ? " · today" : ""}</div>
      <ul class="list">${list.map((e) => html`<li class="item"><div class="grow"><div class="item-title">${e.title}</div><small>${fmtTime(e.start_time)}${e.end_time ? "–" + fmtTime(e.end_time) : ""}${e.location ? " · " + e.location : ""}${e.owner !== "me" ? " · from " + e.owner : ""}</small></div>
        ${e.shared && e.owner === "me" ? html`<span class="chip blue">Shared</span>` : ""}${e.owner === "me" ? html`<button class="btn small quiet" data-act="del" data-id="${e.id}" aria-label="Delete ${e.title}">✕</button>` : ""}</li>`)}</ul>`)
      : emptyState("📆", "Nothing scheduled", "Add appointments, events and reminders. Event bookings from Events & groups show in Events.")}</div>`.s;
  bind(main, {
    del: async (b) => { await DEL("calendar/" + b.dataset.id); navigate(); },
    new: () => dialog({ title: "Add event", body: html`<div class="field"><label for="ct2">Title</label><input id="ct2" name="title" type="text" required maxlength="200"></div>
      <div class="grid g2"><div class="field"><label for="cs2">Starts</label><input id="cs2" name="start" type="datetime-local" required></div><div class="field"><label for="ce2">Ends</label><input id="ce2" name="end" type="datetime-local"></div></div>
      <div class="field"><label for="cl2">Where</label><input id="cl2" name="location" type="text" maxlength="200"></div>
      <div class="field"><label for="cn2">Notes</label><textarea id="cn2" name="notes" maxlength="2000"></textarea></div>
      ${isCare() && people.length ? html`<div class="field"><label for="ca2">About (optional)</label><select id="ca2" name="about"><option value="">—</option>${people.map((p) => html`<option value="${p.individual_id}">${p.display_name}</option>`)}</select></div>` : ""}
      ${isInd() ? html`<label class="check"><input type="checkbox" name="shared"> Share with my circle (people with Calendar access)</label>` : ""}`,
      onOk: async (fd) => { await POST("calendar", { title: val(fd, "title"), start_time: fd.get("start") + ":00", end_time: fd.get("end") ? fd.get("end") + ":00" : null, location: val(fd, "location"), notes: val(fd, "notes"), about_individual_id: fd.get("about") ? Number(fd.get("about")) : null, shared: !!fd.get("shared") }); navigate(); } }),
  });
});

/* ============================================================ wellbeing */
route("wellbeing", async (main) => {
  const [w, c] = await Promise.all([GET("care/wellbeing"), GET("care/contacts")]);
  const pick = {};
  main.innerHTML = html`${head(t("Wellbeing"), "Your needs matter too. This is private to you.")}
    <div class="grid g2"><div class="card"><h3>How are you, really?</h3><form data-form="save">
      ${[["stress", "Stress", ["😌", "🙂", "😐", "😣", "🤯"]], ["rest", "Rest", ["😫", "🥱", "😐", "🙂", "😴"]], ["supported", "Feeling supported", ["😞", "🙁", "😐", "🙂", "🤗"]]].map(([k, l, emo]) => html`<div class="field"><div style="font-weight:550;margin-bottom:6px">${l}</div>
        <div class="scale">${emo.map((e, i) => html`<button type="button" class="choice" data-act="p" data-k="${k}" data-v="${i + 1}" aria-pressed="false" aria-label="${l} ${i + 1}"><span class="emo" aria-hidden="true">${e}</span>${i + 1}</button>`)}</div></div>`)}
      <div class="field"><label for="wn">Notes (private)</label><textarea id="wn" name="note" maxlength="2000"></textarea></div><button class="btn primary">Save</button></form>
      <div id="wbMsg"></div></div>
    <div class="stack"><div class="card tint-sage"><h3>Support for you</h3><ul>
        <li><strong>Tele-MANAS</strong>: 14416 or 1-800-891-4416 — free, 24/7 mental health support in India.</li>
        <li><strong>Emergency</strong>: 112.</li><li>Share tasks on the <a href="#/coordination">Coordination</a> page — you don't have to carry everything.</li>
        <li>Find caregiver groups in <a href="#/community">Community</a> and <a href="#/events">Events</a>.</li></ul>
        <p class="hint">Self-care helps, but it doesn't fix a lack of practical support. Asking for help is part of caring well.</p></div>
      <div class="card"><h3>Support team contacts</h3>${c.contacts.length ? html`<ul class="list">${c.contacts.map((x) => html`<li class="item"><div class="grow"><strong>${x.name}</strong> <small>${x.role || ""}</small><br><small>${x.phone || ""} ${x.email || ""}</small></div><button class="btn small quiet" data-act="dc" data-id="${x.id}" aria-label="Remove ${x.name}">✕</button></li>`)}</ul>` : html`<p class="muted">Doctors, teachers, therapists, respite — keep them in one place.</p>`}
        <form data-form="contact" class="grid g2" style="margin-top:8px"><input name="name" type="text" aria-label="Name" placeholder="Name" required maxlength="100"><input name="role" type="text" aria-label="Role" placeholder="Role (e.g. OT)" maxlength="100">
          <input name="phone" type="text" aria-label="Phone" placeholder="Phone" maxlength="40"><input name="email" type="email" aria-label="Email" placeholder="Email" maxlength="200"><button class="btn">${t("Add")}</button></form></div>
      ${w.checkins.length ? html`<div class="card"><h3>Recent</h3><ul class="list">${w.checkins.slice(0, 5).map((x) => html`<li><small>${fmtWhen(x.created_at)}</small> stress ${x.stress ?? "–"} · rest ${x.rest ?? "–"} · supported ${x.supported ?? "–"}</li>`)}</ul></div>` : ""}</div></div>`.s;
  bind(main, {
    p: (b) => { pick[b.dataset.k] = Number(b.dataset.v); $$(`[data-k=${b.dataset.k}]`, main).forEach((x) => x.setAttribute("aria-pressed", x === b)); },
    save: async (fd) => { const r = await POST("care/wellbeing", { ...pick, note: val(fd, "note") }); $("#wbMsg").innerHTML = html`<div class="alert ok" style="margin-top:12px">${r.message}</div>`.s; },
    contact: async (fd) => { await POST("care/contacts", { name: val(fd, "name"), role: val(fd, "role"), phone: val(fd, "phone"), email: val(fd, "email") }); navigate(); },
    dc: async (b) => { await DEL("care/contacts/" + b.dataset.id); navigate(); },
  });
});

/* ============================================================ circle & consent */
route("circle", async (main) => {
  const c = await GET("circle"); const me = S.user;
  const active = c.links.filter((l) => l.status === "active"), pending = c.links.filter((l) => l.status === "pending");
  const requests = isInd() ? (await GET("support-requests")).requests.slice(0, 5) : [];
  const canGrant = (l) => isInd() || (l.is_guardian && l.consent_mode === "guardian");
  main.innerHTML = html`${head(isInd() ? t("My circle") : "My connections", isInd() ? "Trusted people you choose. Being connected shares nothing — you switch on each kind of information yourself." : "Connections with the people you support. They control what you can see.",
      html`<button class="btn primary" data-act="invite">+ Invite</button>`)}
    ${isInd() && active.length ? html`<div class="card tint-lav" style="margin-bottom:16px"><h3>Send a quick message to your circle</h3><div class="row">${c.support_messages.map((m) => html`<button class="btn small" data-act="sr" data-m="${m}">${m}</button>`)}</div>
      ${requests.length ? html`<p class="hint" style="margin-top:8px">Recent: ${requests.map((r) => `“${r.message}” → ${r.other_name} (${r.status.replace(/_/g, " ")})`).join(" · ")}</p>` : ""}</div>` : ""}
    ${pending.length ? html`<div class="card" style="margin-bottom:16px"><h3>Invitations</h3><ul class="list">${pending.map((l) => html`<li class="item"><div class="grow"><strong>${l.display_name}</strong> <small>${l.email}${l.relationship ? " · " + l.relationship : ""}${l.is_guardian ? " · as guardian" : ""}</small><br><small>${l.waiting_for_me ? "Wants to connect with you." : "Waiting for them to accept."}</small></div>
      ${l.waiting_for_me ? html`<div class="row"><button class="btn small primary" data-act="link" data-id="${l.id}" data-a="accept">Accept</button><button class="btn small" data-act="link" data-id="${l.id}" data-a="decline">Decline</button></div>` : html`<button class="btn small quiet" data-act="link" data-id="${l.id}" data-a="revoke">Cancel</button>`}</li>`)}</ul></div>` : ""}
    ${active.length ? html`<div class="stack">${active.map((l) => html`<div class="card"><div class="card-head"><div><h3>${l.display_name}</h3><small>${l.email}${l.relationship ? " · " + l.relationship : ""}</small> ${l.is_guardian ? html`<span class="chip amber">Guardian</span>` : ""}</div>
        <div class="row"><button class="btn small quiet" data-act="hist" data-id="${l.id}">History</button><button class="btn small danger" data-act="link" data-id="${l.id}" data-a="revoke">Disconnect</button></div></div>
      <table class="t"><thead><tr><th scope="col">Information</th><th scope="col">Status</th><th scope="col"><span class="sr-only">Action</span></th></tr></thead><tbody>
      ${Object.entries(c.scopes).map(([k, label]) => { const st = l.permissions[k] || "off"; return html`<tr><td>${SCOPE_ICON[k]} ${label}</td>
        <td><span class="chip ${st === "granted" ? "teal" : st === "requested" ? "amber" : ""}">${st === "granted" ? "Shared" : st === "requested" ? (isInd() ? "They asked" : "Asked") : "Not shared"}</span></td>
        <td>${canGrant(l) ? (st === "granted" ? html`<button class="btn small" data-act="scope" data-id="${l.id}" data-k="${k}" data-s="revoked">Stop sharing</button>` : html`<button class="btn small primary" data-act="scope" data-id="${l.id}" data-k="${k}" data-s="granted">Share</button>`)
          : st === "granted" || st === "requested" ? "" : html`<button class="btn small" data-act="scope" data-id="${l.id}" data-k="${k}" data-s="requested">Ask</button>`}</td></tr>`; })}</tbody></table>
      <p class="hint">Never shareable: ${c.never_shared.join(", ")}.${l.is_guardian && !isInd() ? " As a guardian you can change sharing for an under-18 account in guardian mode; they can always see every change." : ""}</p></div>`)}</div>`
      : !pending.length ? html`<div class="card">${emptyState("🫶", "No one here yet", isInd() ? "Invite a parent, partner, friend or support worker. Nothing is shared until you choose." : "Invite the person you support by their NeuroBridge email.")}</div>` : ""}
    ${isInd() ? html`<div class="card soft" style="margin-top:16px"><h3>Consent mode</h3><p class="muted">Current: <strong>${me.consent_mode}</strong>. ${me.consent_mode === "guardian" ? "A connected guardian can also change sharing for you. You always see every change." : me.consent_mode === "supported" ? "Supporters can ask; you decide (supported decision-making)." : "Only you can share."}</p>
      <div class="row">${["self", "supported", "guardian"].filter((m) => !(me.is_minor && m === "self")).map((m) => html`<button class="btn small" data-act="mode" data-m="${m}" aria-pressed="${me.consent_mode === m}">${{ self: "Only me", supported: "Supported decisions", guardian: "Guardian can help" }[m]}</button>`)}</div></div>` : ""}`.s;
  bind(main, {
    invite: () => dialog({ title: "Invite someone", okText: "Send invitation", body: html`<div class="field"><label for="ie">Their NeuroBridge email</label><input id="ie" name="email" type="email" required></div>
      <div class="field"><label for="ir">Relationship (optional)</label><input id="ir" name="relationship" type="text" maxlength="60" placeholder="e.g. Mum, partner, support worker"></div>
      ${isCare() ? html`<label class="check"><input type="checkbox" name="guardian"> I am their parent or legal guardian <span class="hint">(only takes effect if their account uses guardian consent mode, e.g. under 18)</span></label>` : ""}
      <p class="hint">They need to accept. Nothing is shared until ${isInd() ? "you choose" : "they choose"}.</p>`,
      onOk: async (fd) => { const r = await POST("circle/invite", { email: val(fd, "email"), relationship: val(fd, "relationship"), is_guardian: !!fd.get("guardian") }); toast(r.message); navigate(); } }),
    link: async (b) => { if (b.dataset.a === "revoke" && !(await confirmDlg("Disconnect?", "All sharing with this person stops straight away.", "Disconnect", true))) return; await POST("circle/" + b.dataset.id, { action: b.dataset.a }); navigate(); },
    scope: async (b) => { await PUT(`circle/${b.dataset.id}/scopes/${b.dataset.k}`, { state: b.dataset.s }); toast(b.dataset.s === "granted" ? "Shared." : b.dataset.s === "revoked" ? "Sharing stopped." : "Asked."); navigate(); },
    hist: async (b) => { const h = await GET(`circle/${b.dataset.id}/history`); dialog({ title: "Sharing history", okText: "", cancelText: "Close", body: h.records.length ? html`<ul class="list">${h.records.map((x) => html`<li>${fmtWhen(x.created_at)} — <strong>${x.actor}</strong> ${x.action} <em>${x.scope.replace("_", " ")}</em></li>`)}</ul>` : html`<p class="muted">No changes yet.</p>` }); },
    sr: async (b) => { const r = await POST("support-requests", { message: b.dataset.m }); toast(`Sent to ${r.sent_to}.`); navigate(); },
    mode: async (b) => { await savePrefs({}, { consent_mode: b.dataset.m }); navigate(); },
  });
});

/* ============================================================ providers & appointments */
const PROFESSIONS = ["Psychiatrist", "Psychologist", "Counsellor", "Occupational therapist", "Speech therapist", "Developmental paediatrician", "Special educator"];
const apptStatus = (x) => x.booking_status === "pending_approval" ? ["Request — needs your confirmation", "amber"]
  : x.booking_status === "cancelled" ? ["Cancelled", ""]
  : x.clinic_status === "clinic_confirmed" ? ["Confirmed by the clinic", "teal"]
  : ["Reserved — waiting for the clinic to confirm", "sage"];
const OUT_ST = { to_contact: "To contact", contacted: "Contacted — waiting", booked: "Booked with them", closed: "Closed" };
const telHref = (p) => "tel:" + String(p || "").replace(/[^+\d]/g, "");

function providerCard(x) {
  const verified = x.verified_at ? `Listing checked ${fmtDate(x.verified_at)}` : "Listing checked";
  return html`<li class="item provider"><div class="grow">
    <div class="item-title">${x.provider_name} ${x.is_demo ? html`<span class="chip amber">Demo listing — not a real clinic</span>` : html`<span class="chip sage" title="${x.verification_note || ""}">✓ ${verified}</span>`}</div>
    <small><strong>${x.profession}</strong>${x.credentials ? " · " + x.credentials : ""}${x.organization ? " · " + x.organization : ""}</small><br>
    <small>${x.location || ""}${x.online_consultation ? " · Online available" : ""}${x.languages?.length ? " · " + x.languages.join(", ") : ""}${x.fee_amount ? ` · from ₹${x.fee_amount}` : ""}</small>
    ${x.specialties?.length ? html`<div class="row" style="margin-top:6px">${x.specialties.slice(0, 6).map((sp) => html`<span class="chip">${sp}</span>`)}</div>` : ""}
    ${x.about ? html`<p class="hint" style="margin:6px 0 0">${x.about}</p>` : ""}
    <div class="row" style="margin-top:6px">${x.phone ? html`<a class="btn small quiet" href="${telHref(x.phone)}">📞 ${x.phone}</a>` : ""}${x.website ? html`<a class="btn small quiet" href="${x.website}" target="_blank" rel="noopener">Website ↗</a>` : ""}</div>
    ${x.verification_note && !x.is_demo ? html`<p class="hint" style="margin:4px 0 0">What was checked: ${x.verification_note}</p>` : ""}</div>
    <button class="btn small primary" data-act="slots" data-id="${x.provider_id}" data-name="${x.provider_name}">See times</button></li>`;
}

route("appointments", async (main, profArg) => {
  const prof = profArg ? decodeURIComponent(profArg) : "";
  const [p, a] = await Promise.all([GET("providers" + (prof ? "?profession=" + encodeURIComponent(prof) : "")), GET("appointments")]);
  const outside = a.outside_requests || [];
  main.innerHTML = html`${head(t("Providers & appointments"), "Book a listed psychiatrist, psychologist or therapist, or keep track of clinics you found elsewhere. Nothing is reserved until you confirm the exact details.",
      html`<a class="btn primary" href="#/assistant/new/${encodeURIComponent("Find a psychiatrist near me and book an appointment if one is available")}/agent">✨ Ask the agent to find and book</a>`)}
    <div class="card" style="margin-bottom:16px"><h3>My appointments</h3>${a.appointments.length ? html`<ul class="list">${a.appointments.map((x) => { const [lab, col] = apptStatus(x); return html`<li class="item"><div class="grow">
      <div class="item-title">${x.provider_name} <small>(${x.profession})</small> ${x.is_demo ? html`<span class="chip amber">Demo</span>` : ""}</div><small>${fmtWhen(x.start_time)} · ${x.appointment_type}${x.address ? " · " + x.address : x.location ? " · " + x.location : ""}</small>
      <div class="row" style="margin-top:4px"><span class="chip ${col}">${lab}</span>${x.confirmation_code ? html`<span class="chip">Ref ${x.confirmation_code}</span>` : ""}${x.phone ? html`<a class="chip" href="${telHref(x.phone)}">📞 ${x.phone}</a>` : ""}</div>
      ${x.clinic_note ? html`<p class="hint" style="margin:4px 0 0">Clinic note: ${x.clinic_note}</p>` : ""}</div>
      <div class="row">${x.booking_status === "pending_approval" ? html`<button class="btn small primary" data-act="confirm" data-id="${x.appointment_id}">Review &amp; confirm</button>` : ""}
      ${x.booking_status !== "cancelled" ? html`<button class="btn small quiet" data-act="cancel" data-id="${x.appointment_id}">Cancel</button>` : ""}</div></li>`; })}</ul>
      <p class="hint">${a.confirmation_scope}</p>` : html`<p class="muted">No appointments yet.</p>`}</div>

    <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3>Clinics I'm contacting</h3><p class="hint" style="margin:0">For clinics found on the web. NeuroBridge can't book on their systems, so this keeps track and gives you a message to send.</p></div>
      <button class="btn small" data-act="addout">＋ Add a clinic</button></div>
      ${outside.length ? html`<ul class="list">${outside.map((o) => html`<li class="item"><div class="grow">
        <div class="item-title">${o.clinic_name} ${o.profession ? html`<small>(${o.profession})</small>` : ""}</div>
        <div class="row" style="margin-top:4px"><span class="chip ${o.status === "booked" ? "teal" : o.status === "closed" ? "" : "amber"}">${OUT_ST[o.status] || o.status}</span>
          ${o.phone ? html`<a class="chip" href="${telHref(o.phone)}">📞 ${o.phone}</a>` : ""}${o.email ? html`<a class="chip" href="mailto:${o.email}">✉️ ${o.email}</a>` : ""}${o.source_url ? html`<a class="chip" href="${o.source_url}" target="_blank" rel="noopener">Source ↗</a>` : ""}</div>
        ${o.notes ? html`<p class="hint" style="margin:4px 0 0">${o.notes}</p>` : ""}</div>
        <div class="row"><button class="btn small" data-act="draft" data-id="${o.request_id}">Message to send</button><button class="btn small quiet" data-act="outst" data-id="${o.request_id}">Update</button><button class="btn small quiet" data-act="outdel" data-id="${o.request_id}" aria-label="Remove ${o.clinic_name}">✕</button></div></li>`)}</ul>`
      : html`<p class="muted">Nothing here yet. When the agent finds clinics on the web, use “Track this clinic” on its answer.</p>`}</div>

    <div class="card"><div class="card-head"><div><h3>Listed providers</h3><p class="hint" style="margin:0">${p.notice}</p></div>
      <label class="sr-only" for="pf">Filter by profession</label><select id="pf"><option value="">All professions</option>${PROFESSIONS.map((x) => html`<option ${raw(prof === x ? "selected" : "")}>${x}</option>`)}</select></div>
      ${p.providers?.length ? html`<ul class="list">${p.providers.map(providerCard)}</ul>`
      : emptyState("🩺", prof ? `No listed ${prof.toLowerCase()}s yet` : "No listed providers yet", "Providers appear here after a NeuroBridge admin checks their details. Ask the agent to search the web — it shows sources and contact details it could verify.")}</div>`.s;
  $("#pf", main).onchange = (e) => { location.hash = "#/appointments" + (e.target.value ? "/" + encodeURIComponent(e.target.value) : ""); };
  const outForm = (o = {}) => html`<div class="field"><label for="on">Clinic or doctor name</label><input id="on" name="clinic_name" required maxlength="200" value="${o.clinic_name || ""}"></div>
    <div class="grid g2"><div class="field"><label for="op">Profession</label><input id="op" name="profession" maxlength="80" value="${o.profession || ""}" placeholder="e.g. Psychiatrist"></div>
    <div class="field"><label for="oph">Phone</label><input id="oph" name="phone" maxlength="40" value="${o.phone || ""}"></div></div>
    <div class="grid g2"><div class="field"><label for="oe">Email</label><input id="oe" name="email" type="email" maxlength="160" value="${o.email || ""}"></div>
    <div class="field"><label for="ou">Where you found it (link)</label><input id="ou" name="source_url" type="url" maxlength="300" value="${o.source_url || ""}"></div></div>
    <div class="field"><label for="ot">Times that suit you</label><input id="ot" name="preferred_times" maxlength="200" placeholder="e.g. weekday mornings"></div>
    <div class="field"><label for="or">Reason (optional, brief)</label><input id="or" name="reason" maxlength="500" placeholder="e.g. first consultation for ADHD assessment"></div>
    <p class="hint">Check the phone number on the clinic's own website before calling.</p>`;
  bind(main, {
    slots: async (b) => { const s = await GET("providers/slots?provider_id=" + b.dataset.id);
      dialog({ title: b.dataset.name, okText: s.slots.length ? "Request this time" : "", wide: true,
        body: s.slots.length ? html`<fieldset style="border:0;padding:0"><legend>Choose a time</legend>${s.slots.map((x, i) => html`<label class="check field"><input type="radio" name="slot" value="${x.slot_id}" ${raw(i ? "" : "checked")}> ${fmtWhen(x.start_time)} · ${x.duration_minutes} min${x.fee_amount ? ` · ₹${x.fee_amount}` : ""}${x.online_consultation ? " · online possible" : ""}</label>`)}</fieldset>
          <div class="field"><label for="at">Type</label><select id="at" name="type"><option value="consultation">First consultation</option><option value="follow-up">Follow-up</option><option value="online consultation">Online consultation</option></select></div>
          <div class="field"><label for="an">Notes for the clinic (optional)</label><textarea id="an" name="notes" maxlength="1000" placeholder="e.g. I may need a quiet waiting area"></textarea></div>
          <label class="check field"><input type="checkbox" name="share" checked> Share my name and phone number with the clinic so they can confirm</label>
          <div class="field"><label for="aph">Phone number for the clinic</label><input id="aph" name="phone" maxlength="40" inputmode="tel"></div>
          <p class="hint">This creates a request only. You'll confirm the exact details next.</p>` : html`<p>No open times right now. You can call the clinic directly, or add it to “Clinics I'm contacting”.</p>`,
        onOk: async (fd) => { await POST("appointments", { slot_id: Number(fd.get("slot")), appointment_type: fd.get("type"), notes: val(fd, "notes"), share_contact: !!fd.get("share"), contact_phone: val(fd, "phone") }); toast("Request created — confirm it to reserve."); navigate(); } }); },
    confirm: async (b) => { const x = a.appointments.find((y) => y.appointment_id === Number(b.dataset.id));
      dialog({ title: "Confirm this appointment?", okText: "Yes, reserve it", body: html`<dl class="kv"><dt>Provider</dt><dd>${x.provider_name} (${x.profession})</dd><dt>When</dt><dd>${fmtWhen(x.start_time)}</dd><dt>Type</dt><dd>${x.appointment_type}</dd>${x.address ? html`<dt>Where</dt><dd>${x.address}</dd>` : ""}</dl>
        <label class="check" style="margin-top:12px"><input type="checkbox" name="ok" required> I confirm these exact details.</label><p class="hint">${a.confirmation_scope}</p>`,
        onOk: async (fd) => { if (!fd.get("ok")) throw new Error("Tick the box to confirm."); const r = await POST(`appointments/${x.appointment_id}/approve?explicit_approval=true`); toast("Reserved. Ref " + r.confirmation_code + " — waiting for the clinic to confirm."); navigate(); } }); },
    cancel: async (b) => { if (await confirmDlg("Cancel this appointment?", "The slot will be released.", "Cancel appointment", true)) { await POST(`appointments/${b.dataset.id}/cancel`); navigate(); } },
    addout: () => dialog({ title: "Track a clinic", okText: "Save", wide: true, body: outForm(),
      onOk: async (fd) => { const body = {}; for (const k of ["clinic_name", "profession", "phone", "email", "source_url", "preferred_times", "reason"]) body[k] = val(fd, k); await POST("outside-requests", body); toast("Saved. Open “Message to send” when you're ready."); navigate(); } }),
    draft: (b) => { const o = outside.find((y) => y.request_id === Number(b.dataset.id));
      dialog({ title: "Message to send", okText: "Copy", cancelText: "Close", body: html`<div class="field"><label for="dm">Edit it as you like</label><textarea id="dm" name="m" rows="10">${o.draft_message}</textarea></div>
        <div class="row">${o.phone ? html`<a class="btn small" href="${telHref(o.phone)}">📞 Call</a>` : ""}${o.email ? html`<a class="btn small" href="mailto:${o.email}?subject=${encodeURIComponent("Appointment request")}&body=${encodeURIComponent(o.draft_message)}">✉️ Open in email</a>` : ""}${o.phone ? html`<a class="btn small" href="https://wa.me/${String(o.phone).replace(/[^\d]/g, "")}?text=${encodeURIComponent(o.draft_message)}" target="_blank" rel="noopener">WhatsApp ↗</a>` : ""}</div>`,
        onOk: async (fd) => { await navigator.clipboard.writeText(fd.get("m")); toast("Copied."); } }); },
    outst: (b) => { const o = outside.find((y) => y.request_id === Number(b.dataset.id));
      dialog({ title: o.clinic_name, okText: "Save", body: html`<div class="field"><label for="os">Status</label><select id="os" name="status">${Object.entries(OUT_ST).map(([k, l]) => html`<option value="${k}" ${raw(o.status === k ? "selected" : "")}>${l}</option>`)}</select></div>
        <div class="field"><label for="ono">Notes</label><textarea id="ono" name="notes" maxlength="1000">${o.notes || ""}</textarea></div>`,
        onOk: async (fd) => { await api("PATCH", "outside-requests/" + o.request_id, { status: fd.get("status"), notes: val(fd, "notes") }); navigate(); } }); },
    outdel: async (b) => { if (await confirmDlg("Remove this clinic from your list?", "", "Remove", true)) { await api("DELETE", "outside-requests/" + b.dataset.id); navigate(); } },
  });
});

/* ============================================================ settings */
route("settings", async (main) => {
  const [mem, notif] = await Promise.all([GET("assistant/memory"), GET("notifications")]);
  const p = S.prefs, np = notif.prefs;
  const toggle = (k, label, hint) => html`<label class="check field"><input type="checkbox" data-pref="${k}" ${raw(p[k] ? "checked" : "")}> <span>${label}${hint ? html`<span class="hint" style="display:block">${hint}</span>` : ""}</span></label>`;
  main.innerHTML = html`${head(t("Settings"), "Make NeuroBridge fit you. Changes save straight away.")}
    <div class="grid g2">
      <div class="card"><h3>Display & accessibility</h3>
        <div class="field"><label for="fs">Text size: <span id="fsv">${Math.round((p.font_scale || 1) * 100)}%</span></label><input id="fs" type="range" min="0.85" max="1.6" step="0.05" value="${p.font_scale || 1}" style="width:100%"></div>
        <div class="field"><label for="th">Theme</label><select id="th" data-sel="theme"><option value="light" ${raw(p.theme !== "dark" ? "selected" : "")}>Light</option><option value="dark" ${raw(p.theme === "dark" ? "selected" : "")}>Dark</option></select></div>
        ${toggle("low_stimulation", "Low-stimulation mode", "Muted colours, no shadows, no motion.")}
        ${toggle("high_contrast", "High contrast")}${toggle("reduced_motion", "Reduce motion")}
        ${toggle("dyslexia_font", "Dyslexia-friendly text", "Wider spacing and a clearer font.")}</div>
      <div class="card"><h3>Assistant</h3>
        ${toggle("simple_language", "Simple language", "Short sentences and plain words.")}
        <div class="field"><label for="rl">Answer length</label><select id="rl" data-sel="response_length">${[["short", "Short"], ["balanced", "Balanced"], ["detailed", "Detailed"]].map(([v, l]) => html`<option value="${v}" ${raw(p.response_length === v ? "selected" : "")}>${l}</option>`)}</select></div>
        ${toggle("tts", "Read communication cards aloud")}${toggle("auto_speak", "Read assistant replies aloud automatically")}
        <div class="field"><label for="lang">Language</label><select id="lang">${window.NB_LANGS.map(([c, n]) => html`<option value="${c}" ${raw(S.user.language === c ? "selected" : "")}>${n}</option>`)}</select>
          <div class="hint">The assistant replies in this language. The interface is translated for Hindi (needs review); other languages show English menus for now. Machine translation can be wrong — take extra care with health or safety wording.</div></div></div>
      <div class="card"><h3>Memory</h3>${toggle("memory_enabled", "Let the assistant use memories I approve", "Off means nothing is used or saved.")}
        <p class="hint">${mem.explanation}</p>
        ${mem.memories.length ? html`<ul class="list">${mem.memories.map((m) => html`<li class="item"><div class="grow"><strong>${m.memory_key}</strong>: ${m.memory_value} <small>(${m.category})</small></div><button class="btn small quiet" data-act="forget" data-k="${m.memory_key}">Forget</button></li>`)}</ul>` : html`<p class="muted">Nothing remembered. Use “🧠 Remember” in a chat to choose what to keep.</p>`}</div>
      <div class="card"><h3>Notifications</h3><p class="hint">No streaks, no guilt. Support requests from your circle always come through.</p>
        ${Object.entries(notif.categories).map(([k, l]) => html`<label class="check"><input type="checkbox" data-ncat="${k}" ${raw(np.disabled.includes(k) ? "" : "checked")} ${raw(k === "support_request" ? "disabled" : "")}> ${l}</label>`)}
        <div class="grid g2" style="margin-top:12px"><div class="field"><label for="qs">Quiet from</label><input id="qs" type="time" value="${np.quiet_start}"></div><div class="field"><label for="qe">Until</label><input id="qe" type="time" value="${np.quiet_end}"></div></div>
        <div class="field"><label for="mx">At most per type, per day</label><input id="mx" type="number" min="1" max="50" value="${np.max_per_day}"></div><button class="btn small" data-act="savenotif">Save notification settings</button></div>
      <div class="card"><h3>Your data</h3><p class="muted">Download everything NeuroBridge stores about you, or delete your account.</p>
        <div class="row"><button class="btn" data-act="export">⬇ Download my data</button><button class="btn danger" data-act="delete">Delete account</button></div>
        <p class="hint">NeuroBridge has not been through a legal compliance assessment (e.g. GDPR or India's DPDP Act). Don't store anything you're not comfortable with.</p></div>
      <div class="card"><h3>Account</h3><dl class="kv"><dt>Name</dt><dd>${S.user.display_name}</dd><dt>Email</dt><dd>${S.user.email}</dd><dt>Type</dt><dd>${S.user.role}${S.user.is_minor ? " (under 18)" : ""}</dd></dl>
        <div class="row" style="margin-top:12px"><button class="btn" data-act="rename">Change name</button><button class="btn" data-act="signout">${t("Sign out")}</button></div></div>
    </div>`.s;
  $$("[data-pref]", main).forEach((c) => c.onchange = () => savePrefs({ [c.dataset.pref]: c.checked }).then(() => toast("Saved.")).catch(fail));
  $$("[data-sel]", main).forEach((c) => c.onchange = () => savePrefs({ [c.dataset.sel]: c.value }).then(() => toast("Saved.")).catch(fail));
  const fs = $("#fs", main); fs.oninput = () => { document.documentElement.style.setProperty("--scale", fs.value); $("#fsv").textContent = Math.round(fs.value * 100) + "%"; };
  fs.onchange = () => savePrefs({ font_scale: Number(fs.value) }).catch(fail);
  $("#lang", main).onchange = async (e) => { await savePrefs({}, { language: e.target.value }); renderShell(); navigate(); };
  bind(main, {
    forget: async (b) => { await DEL("assistant/memory/" + encodeURIComponent(b.dataset.k)); navigate(); },
    savenotif: async () => { const disabled = $$("[data-ncat]", main).filter((c) => !c.checked).map((c) => c.dataset.ncat);
      await savePrefs({ notifications: { disabled, quiet_start: $("#qs").value, quiet_end: $("#qe").value, max_per_day: Number($("#mx").value) || 5 } }); toast("Saved."); },
    export: async () => { const d = await GET("me/export"); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" })); a.download = "neurobridge-my-data.json"; a.click(); },
    delete: () => dialog({ title: "Delete your account?", okText: "Delete everything", danger: true, body: html`<p>This permanently deletes your tasks, routines, journal, check-ins, chats, memories, circle connections and community posts. It can't be undone.</p>
      <div class="field"><label for="dp">Type your password to confirm</label><input id="dp" name="password" type="password" required></div>`,
      onOk: async (fd) => { await DEL("me", { password: fd.get("password") }); signOutLocal(); toast("Your account was deleted."); } }),
    rename: () => dialog({ title: "Change name", body: html`<div class="field"><label for="nn">Name</label><input id="nn" name="n" type="text" value="${S.user.display_name}" maxlength="60" required></div>`,
      onOk: async (fd) => { await savePrefs({}, { display_name: val(fd, "n") }); renderShell(); navigate(); } }),
    signout: signOut,
  });
});

/* ============================================================ admin: provider directory */
const provForm = (x = {}) => html`<div class="grid g2"><div class="field"><label for="pn">Name</label><input id="pn" name="provider_name" required minlength="2" maxlength="160" value="${x.provider_name || ""}" placeholder="e.g. Dr A. Naik"></div>
  <div class="field"><label for="pp">Profession</label><input id="pp" name="profession" required list="proflist" maxlength="80" value="${x.profession || ""}"><datalist id="proflist">${PROFESSIONS.map((p) => html`<option value="${p}">`)}</datalist></div></div>
  <div class="grid g2"><div class="field"><label for="pc">Qualifications / registration</label><input id="pc" name="credentials" maxlength="200" value="${x.credentials || ""}" placeholder="e.g. MD Psychiatry · registration no."></div>
  <div class="field"><label for="po">Clinic / organisation</label><input id="po" name="organization" maxlength="160" value="${x.organization || ""}"></div></div>
  <div class="grid g2"><div class="field"><label for="pl">City / area</label><input id="pl" name="location" maxlength="120" value="${x.location || ""}" placeholder="e.g. Panaji, Goa"></div>
  <div class="field"><label for="pa">Address</label><input id="pa" name="address" maxlength="300" value="${x.address || ""}"></div></div>
  <div class="grid g2"><div class="field"><label for="pph">Phone</label><input id="pph" name="phone" maxlength="40" value="${x.phone || ""}"></div>
  <div class="field"><label for="pe">Email</label><input id="pe" name="email" type="email" maxlength="160" value="${x.email || ""}"></div></div>
  <div class="grid g2"><div class="field"><label for="pw">Website</label><input id="pw" name="website" type="url" maxlength="300" value="${x.website || ""}"></div>
  <div class="field"><label for="ps">Where these details came from (link)</label><input id="ps" name="source_url" type="url" maxlength="300" value="${x.source_url || ""}"></div></div>
  <div class="field"><label for="psp">Specialties (comma-separated)</label><input id="psp" name="specialties" maxlength="400" value="${(x.specialties || []).join(", ")}" placeholder="e.g. ADHD, autism, anxiety, adult assessment"></div>
  <div class="grid g2"><div class="field"><label for="plg">Languages</label><input id="plg" name="languages" maxlength="200" value="${(x.languages || []).join(", ")}" placeholder="English, Konkani, Hindi"></div>
  <div class="field"><label for="pag">Age groups</label><input id="pag" name="age_groups" maxlength="200" value="${(x.age_groups || []).join(", ")}" placeholder="e.g. 18+, children 6-17"></div></div>
  <div class="grid g2"><div class="field"><label for="pf2">Fee from (₹)</label><input id="pf2" name="fee_amount" type="number" min="0" value="${x.fee_amount ?? ""}"></div>
  <label class="check field" style="align-self:end"><input type="checkbox" name="online" ${raw(x.online_consultation ? "checked" : "")}> Offers online consultations</label></div>
  <div class="field"><label for="pab">About (shown to users)</label><textarea id="pab" name="about" maxlength="1000">${x.about || ""}</textarea></div>`;
const provBody = (fd) => { const list = (k) => (val(fd, k) || "").split(",").map((s) => s.trim()).filter(Boolean);
  return { provider_name: val(fd, "provider_name"), profession: val(fd, "profession"), credentials: val(fd, "credentials"), organization: val(fd, "organization"),
    location: val(fd, "location"), address: val(fd, "address"), phone: val(fd, "phone"), email: val(fd, "email"), website: val(fd, "website"), source_url: val(fd, "source_url"),
    specialties: list("specialties"), languages: list("languages"), age_groups: list("age_groups"), fee_amount: val(fd, "fee_amount") ? Number(val(fd, "fee_amount")) : null,
    online_consultation: !!fd.get("online"), about: val(fd, "about") }; };
const CLINIC_LABEL = { awaiting_clinic: ["Waiting for clinic", "amber"], clinic_confirmed: ["Clinic confirmed", "teal"], clinic_declined: ["Clinic declined", ""] };

route("directory", async (main) => {
  if (!isAdmin()) { main.innerHTML = html`<div class="card">${emptyState("🔒", "Admins only", "This page manages the provider directory.")}</div>`.s; return; }
  const [p, ap] = await Promise.all([GET("admin/providers"), GET("admin/appointments")]);
  const groups = { pending: "Waiting for checks", verified: "Listed (bookable)", rejected: "Not listed" };
  const upcoming = ap.appointments.filter((x) => x.booking_status === "confirmed");
  main.innerHTML = html`${head("Provider directory", "Add real psychiatrists, psychologists and therapists after checking their details. Only listings you verify can be booked in NeuroBridge.",
      html`<button class="btn primary" data-act="add">＋ Add provider</button>`)}
    <div class="card soft" style="margin-bottom:16px"><h3>How to check a listing</h3><ol class="muted" style="margin:0;padding-left:20px">
      <li>Find the provider's own website or a government / hospital page, and paste it as the source.</li>
      <li>Look up their registration (for psychiatrists: State Medical Council or NMC register; for psychologists: RCI) and note the number.</li>
      <li>Phone the clinic: confirm they want to receive NeuroBridge bookings, their fee and their open times.</li>
      <li>Write what you checked in the verification note. It is shown to users.</li></ol></div>
    <div class="card" style="margin-bottom:16px"><h3>Reserved appointments</h3>${upcoming.length ? html`<table class="t"><thead><tr><th scope="col">When</th><th scope="col">Provider</th><th scope="col">Patient contact</th><th scope="col">Clinic</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>
      ${upcoming.map((x) => { const [l, c] = CLINIC_LABEL[x.clinic_status] || ["—", ""]; return html`<tr><td>${fmtWhen(x.start_time)}<br><small>Ref ${x.confirmation_code}</small></td>
        <td>${x.provider_name}${x.clinic_phone ? html`<br><a href="${telHref(x.clinic_phone)}"><small>📞 ${x.clinic_phone}</small></a>` : ""}</td>
        <td>${x.share_contact ? html`${x.requester_name || ""}<br><small>${x.requester_phone || "no phone given"}</small>` : html`<small class="muted">Not shared</small>`}${x.caregiver_notes ? html`<br><small>“${x.caregiver_notes}”</small>` : ""}</td>
        <td><span class="chip ${c}">${l}</span></td>
        <td>${x.clinic_status === "awaiting_clinic" ? html`<div class="row"><button class="btn small primary" data-act="cs" data-id="${x.appointment_id}" data-s="clinic_confirmed">Clinic confirmed</button><button class="btn small quiet" data-act="cs" data-id="${x.appointment_id}" data-s="clinic_declined">Declined</button></div>` : ""}</td></tr>`; })}</tbody></table>`
      : html`<p class="muted">No reserved appointments.</p>`}</div>
    ${Object.entries(groups).map(([k, label]) => { const list = p.providers.filter((x) => x.verification_status === k); return list.length ? html`<div class="card" style="margin-bottom:16px"><h3>${label} <span class="chip">${list.length}</span></h3><ul class="list">
      ${list.map((x) => html`<li class="item"><div class="grow"><div class="item-title">${x.provider_name} <small>(${x.profession})</small> ${x.is_demo ? html`<span class="chip amber">Demo</span>` : ""}</div>
        <small>${[x.location, x.phone, x.email].filter(Boolean).join(" · ")}</small>${x.source_url ? html` · <a href="${x.source_url}" target="_blank" rel="noopener"><small>source ↗</small></a>` : html` <span class="chip amber">no source yet</span>`}
        ${x.verification_note ? html`<p class="hint" style="margin:4px 0 0">Checked${x.verified_at ? " " + fmtDate(x.verified_at) : ""}${x.verified_by ? " by " + x.verified_by : ""}: ${x.verification_note}</p>` : ""}
        ${k === "verified" ? html`<small>${x.open_slots} open time${x.open_slots === 1 ? "" : "s"}</small>` : ""}</div>
        <div class="row"><button class="btn small" data-act="edit" data-id="${x.provider_id}">Edit</button>
        ${k !== "verified" ? html`<button class="btn small primary" data-act="verify" data-id="${x.provider_id}">Verify &amp; list</button>` : html`<button class="btn small" data-act="slots" data-id="${x.provider_id}" data-name="${x.provider_name}">Times</button><button class="btn small quiet" data-act="unlist" data-id="${x.provider_id}">Unlist</button>`}</div></li>`)}</ul></div>` : ""; })}
    ${p.providers.length ? "" : html`<div class="card">${emptyState("🩺", "No providers yet", "Add the first psychiatrist or therapist you have checked.")}</div>`}`.s;
  const find = (id) => p.providers.find((x) => x.provider_id === Number(id));
  bind(main, {
    add: () => dialog({ title: "Add provider", okText: "Save (not listed yet)", wide: true, body: provForm(),
      onOk: async (fd) => { await POST("admin/providers", provBody(fd)); toast("Saved. Verify it to list it."); navigate(); } }),
    edit: (b) => dialog({ title: "Edit provider", okText: "Save", wide: true, body: provForm(find(b.dataset.id)),
      onOk: async (fd) => { await api("PATCH", "admin/providers/" + b.dataset.id, provBody(fd)); toast("Saved."); navigate(); } }),
    verify: (b) => { const x = find(b.dataset.id); dialog({ title: "Verify " + x.provider_name, okText: "Verify & list",
      body: html`${x.source_url ? "" : html`<p class="chip amber">Add a source link first if you can.</p>`}<div class="field"><label for="vn">What did you check?</label><textarea id="vn" name="note" required minlength="5" maxlength="500" placeholder="e.g. MCI registration no. 12345 checked on NMC site 20 Nov; called clinic, they agreed to receive bookings, fee ₹800."></textarea></div><p class="hint">Shown to users. “Verified” means you checked the listing — it is not a clinical endorsement.</p>`,
      onOk: async (fd) => { await POST(`admin/providers/${x.provider_id}/verify`, { verified: true, note: val(fd, "note") }); toast("Listed."); navigate(); } }); },
    unlist: async (b) => { if (await confirmDlg("Unlist this provider?", "They will stop appearing to users. Existing appointments stay.", "Unlist", true)) { await POST(`admin/providers/${b.dataset.id}/verify`, { verified: false, note: "Unlisted by admin" }); navigate(); } },
    slots: async (b) => { const s = await GET(`admin/providers/${b.dataset.id}/slots`);
      dialog({ title: "Times · " + b.dataset.name, okText: "Add time", wide: true, body: html`${s.slots.length ? html`<ul class="list">${s.slots.map((x) => html`<li class="item"><div class="grow">${fmtWhen(x.start_time)} → ${fmtTime(x.end_time)} <span class="chip ${x.status === "available" ? "sage" : ""}">${x.status}</span></div>${x.status === "available" ? html`<button type="button" class="btn small quiet" data-rm="${x.slot_id}">Remove</button>` : ""}</li>`)}</ul>` : html`<p class="muted">No times yet.</p>`}
        <h4>Add a time the clinic agreed to</h4><div class="grid g2"><div class="field"><label for="ss">Start</label><input id="ss" name="start" type="datetime-local" required></div><div class="field"><label for="se">End</label><input id="se" name="end" type="datetime-local" required></div></div>
        <div class="field"><label for="sf">Fee (₹, optional)</label><input id="sf" name="fee" type="number" min="0"></div>`,
        onOk: async (fd) => { await POST(`admin/providers/${b.dataset.id}/slots`, { start_time: fd.get("start"), end_time: fd.get("end"), fee_amount: val(fd, "fee") ? Number(val(fd, "fee")) : null }); toast("Time added."); navigate(); } });
      $$("[data-rm]").forEach((btn) => btn.onclick = async () => { try { await api("DELETE", "admin/slots/" + btn.dataset.rm); btn.closest("li").remove(); toast("Removed."); } catch (e) { fail(e); } }); },
    cs: (b) => { const declined = b.dataset.s === "clinic_declined";
      dialog({ title: declined ? "The clinic declined" : "The clinic confirmed", okText: "Save and notify the person", danger: declined,
        body: html`<div class="field"><label for="cn">${declined ? "Reason to show the person (optional)" : "Note for the person (optional)"}</label><textarea id="cn" name="note" maxlength="500" placeholder="${declined ? "e.g. Doctor on leave that day — please pick another time" : "e.g. Please arrive 10 minutes early with any previous reports"}"></textarea></div>${declined ? html`<p class="hint">The time is released so they can pick another.</p>` : ""}`,
        onOk: async (fd) => { await POST(`admin/appointments/${b.dataset.id}/clinic-status`, { status: b.dataset.s, note: val(fd, "note") }); toast("Updated — the person has been notified."); navigate(); } }); },
  });
});
