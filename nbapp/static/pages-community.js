/* NeuroBridge — Community Connect, Events & groups (in-site bookings), moderation, boot. */
"use strict";

const POST_KINDS = { discussion: "💬 Discussion", question: "❓ Question", experience: "🌱 Experience", resource: "📎 Resource", win: "🎉 Win" };
const REACTS = { support: "🫶 Support", same: "🙋 Same here", helpful: "💡 Helpful" };

async function communityProfileGate(main) {
  const p = await GET("community/profile");
  if (p.profile) return p;
  main.innerHTML = html`${head(t("Community"), "Interest groups, peer support and friendly clubs — with real safety protections.")}
    <div class="grid g2"><div class="card"><h3>Set up your community profile</h3><form data-form="save">
      <div class="field"><label for="ch">Handle</label><input id="ch" name="handle" type="text" required pattern="[a-z0-9_]{3,24}" placeholder="e.g. trainfan_42"><div class="hint">3–24 lowercase letters, numbers or _. Please don't use your full real name.</div></div>
      <div class="field"><label for="cb">About you (optional)</label><textarea id="cb" name="bio" maxlength="300"></textarea></div>
      <div class="field"><label for="ci">Interests (comma separated)</label><input id="ci" name="interests" type="text" placeholder="trains, drawing, coding"></div>
      ${p.is_minor ? html`<p class="alert info">Because you're under 18, private connections and messages are switched off, and you can join groups marked “Under-18 friendly”.</p>`
        : html`<label class="check field"><input type="checkbox" name="open"> Let other adults find me and send a connection request</label>`}
      <label class="check field"><input type="checkbox" name="accept" required> I've read and agree to the community guidelines</label>
      <button class="btn primary">Join the community</button></form></div>
    <div class="card tint-teal"><h3>Community guidelines</h3><ol>${p.guidelines.map((g) => html`<li>${g}</li>`)}</ol></div></div>`.s;
  bind(main, { save: async (fd) => { await PUT("community/profile", { handle: val(fd, "handle"), bio: val(fd, "bio"), interests: String(fd.get("interests") || "").split(",").map((x) => x.trim()).filter(Boolean), open_to_connect: !!fd.get("open"), accept_guidelines: !!fd.get("accept") }); navigate(); } });
  return null;
}

route("community", async (main, sub, arg) => {
  const prof = await communityProfileGate(main); if (!prof) return;
  if (sub === "group") return groupPage(main, Number(arg), prof);
  if (sub === "messages" && arg) return messageThread(main, Number(arg));
  const tab = sub || "groups";
  const tabs = html`<div class="tabs" role="tablist">${[["groups", "Groups"], ["people", "People"], ["profile", "My profile & safety"]].concat(isAdmin() ? [["mod", "Moderation"]] : []).map(([k, l]) => html`<button role="tab" aria-selected="${tab === k}" data-act="tab" data-t="${k}">${l}</button>`)}</div>`;
  let body = "";
  if (tab === "groups") {
    const g = await GET("community/groups");
    const mine = g.groups.filter((x) => x.joined), rest = g.groups.filter((x) => !x.joined);
    const card = (x) => html`<div class="card"><div class="card-head"><h3>${x.name}</h3>${x.minor_safe ? html`<span class="chip sage">Under-18 friendly</span>` : x.audience !== "everyone" ? html`<span class="chip">${x.audience}</span>` : ""}</div>
      <p class="muted">${x.description || ""}</p><small>${x.members} members · ${x.topic}${x.is_official ? " · official" : ""}</small>
      <div class="row" style="margin-top:10px">${x.joined ? html`<a class="btn small primary" href="#/community/group/${x.id}">Open</a><button class="btn small quiet" data-act="leave" data-id="${x.id}">Leave</button>`
        : x.can_join ? html`<button class="btn small" data-act="join" data-id="${x.id}">Join</button>` : html`<small>${x.join_note}</small>`}</div></div>`;
    body = html`${mine.length ? html`<h2>My groups</h2><div class="grid gauto" style="margin-bottom:24px">${mine.map(card)}</div>` : ""}
      <div class="row between"><h2>Discover</h2>${!S.user.is_minor ? html`<button class="btn small" data-act="newgroup">+ Start a group</button>` : ""}</div>
      <div class="grid gauto">${rest.map(card)}</div>
      <p class="hint" style="margin-top:16px">Looking for in-person or online meetups? See <a href="#/events">Events &amp; groups</a> for clubs, workshops and support circles you can book.</p>`;
  } else if (tab === "people") {
    const [pp, cc] = await Promise.all([GET("community/people"), GET("community/connections")]);
    body = S.user.is_minor ? html`<div class="card">${emptyState("🛡", "Private connections are for adults", "You can still take part in Under-18 friendly groups.")}</div>` : html`<div class="grid g2">
      <div class="card"><h3>My connections</h3>${cc.connections.length ? html`<ul class="list">${cc.connections.map((c) => html`<li class="item"><div class="grow"><strong>@${c.other_handle || "member"}</strong> <small>${c.status}</small>${c.note ? html`<br><small>“${c.note}”</small>` : ""}</div>
        ${c.incoming ? html`<button class="btn small primary" data-act="answer" data-id="${c.id}" data-a="true">Accept</button><button class="btn small" data-act="answer" data-id="${c.id}" data-a="false">Decline</button>`
          : c.status === "accepted" ? html`<a class="btn small" href="#/community/messages/${c.other_id}">Message</a>` : ""}
        <button class="btn small quiet" data-act="block" data-id="${c.other_id}">Block</button></li>`)}</ul>` : html`<p class="muted">No connections yet.</p>`}</div>
      <div class="card"><h3>Find people</h3><p class="hint">Only adults who chose to be findable appear here.</p>
        ${pp.people.length ? html`<ul class="list">${pp.people.map((x) => html`<li class="item"><div class="grow"><strong>@${x.handle}</strong>${x.bio ? html`<br><small>${x.bio}</small>` : ""}<div class="row">${x.interests.map((i) => html`<span class="chip">${i}</span>`)}</div></div>
          <button class="btn small" data-act="connect" data-id="${x.user_id}" data-h="${x.handle}">Connect</button></li>`)}</ul>` : html`<p class="muted">No one is listed yet.</p>`}</div></div>`;
  } else if (tab === "profile") {
    const b = await GET("community/blocks"); const pr = prof.profile;
    body = html`<div class="grid g2"><div class="card"><h3>My profile</h3><form data-form="profile">
      <div class="field"><label for="eh">Handle</label><input id="eh" name="handle" type="text" value="${pr.handle}" required pattern="[a-z0-9_]{3,24}"></div>
      <div class="field"><label for="eb">About</label><textarea id="eb" name="bio" maxlength="300">${pr.bio || ""}</textarea></div>
      <div class="field"><label for="ei">Interests</label><input id="ei" name="interests" type="text" value="${pr.interests.join(", ")}"></div>
      ${!S.user.is_minor ? html`<label class="check field"><input type="checkbox" name="open" ${raw(pr.open_to_connect ? "checked" : "")}> Findable by other adults</label>` : ""}
      <button class="btn primary">${t("Save")}</button></form></div>
      <div class="card"><h3>Safety</h3><p>Use <strong>Report</strong> on any post, comment or message. Moderators review every report. Posts with personal details or worrying content are checked by a person before anyone sees them.</p>
        <h4>Blocked</h4>${b.blocks.length ? html`<ul class="list">${b.blocks.map((x) => html`<li class="item"><span class="grow">@${x.handle || "member"}</span><button class="btn small" data-act="unblock" data-id="${x.blocked_id}">Unblock</button></li>`)}</ul>` : html`<p class="muted">You haven't blocked anyone.</p>`}
        <h4>Guidelines</h4><ol>${prof.guidelines.map((g) => html`<li>${g}</li>`)}</ol></div></div>`;
  } else if (tab === "mod") { return ROUTES.moderation(main); }
  main.innerHTML = html`${head(t("Community"), "Find your people. Kindness first; safety always.")}${tabs}${body}`.s;
  bind(main, {
    tab: (b) => { location.hash = "#/community/" + b.dataset.t; },
    join: async (b) => { await POST(`community/groups/${b.dataset.id}/join`); location.hash = "#/community/group/" + b.dataset.id; },
    leave: async (b) => { await POST(`community/groups/${b.dataset.id}/leave`); navigate(); },
    newgroup: () => dialog({ title: "Start a group", body: html`<div class="field"><label for="gn2">Name</label><input id="gn2" name="name" type="text" required minlength="3" maxlength="60"></div>
      <div class="field"><label for="gd2">What's it about?</label><textarea id="gd2" name="description" maxlength="300"></textarea></div>
      <div class="grid g2"><div class="field"><label for="gt2">Topic</label><select id="gt2" name="topic">${["hobbies", "autism", "adhd", "sensory", "caregiving", "work", "local"].map((x) => html`<option>${x}</option>`)}</select></div>
      <div class="field"><label for="ga2">Who can join</label><select id="ga2" name="audience"><option value="everyone">Everyone 18+</option><option value="adults">Adults only</option><option value="caregivers">Caregivers only</option></select></div></div>
      <p class="hint">You'll be the group's moderator. New groups are adult-only; only admins can mark a group Under-18 friendly.</p>`,
      onOk: async (fd) => { const g = await POST("community/groups", { name: val(fd, "name"), description: val(fd, "description"), topic: fd.get("topic"), audience: fd.get("audience") }); location.hash = "#/community/group/" + g.id; } }),
    connect: (b) => dialog({ title: `Connect with @${b.dataset.h}?`, okText: "Send request", body: html`<div class="field"><label for="cn3">A short note (optional)</label><input id="cn3" name="note" type="text" maxlength="200" placeholder="e.g. I love trains too!"></div>`,
      onOk: async (fd) => { await POST("community/connections", { user_id: Number(b.dataset.id), note: val(fd, "note") }); toast("Request sent."); navigate(); } }),
    answer: async (b) => { await POST(`community/connections/${b.dataset.id}?accept=${b.dataset.a}`); navigate(); },
    block: async (b) => { if (await confirmDlg("Block this person?", "You won't see each other's posts, and they can't message or connect with you. They aren't told.", "Block", true)) { await POST("community/blocks", { user_id: Number(b.dataset.id) }); navigate(); } },
    unblock: async (b) => { await DEL("community/blocks/" + b.dataset.id); navigate(); },
    profile: async (fd) => { await PUT("community/profile", { handle: val(fd, "handle"), bio: val(fd, "bio"), interests: String(fd.get("interests") || "").split(",").map((x) => x.trim()).filter(Boolean), open_to_connect: !!fd.get("open"), accept_guidelines: true }); toast("Saved."); navigate(); },
  });
});

function reportDialog(type, id) {
  dialog({ title: "Report", okText: "Send report", body: html`<div class="field"><label for="rr">What's wrong?</label><select id="rr" name="reason">
      ${["Harassment or bullying", "Hate or discrimination", "Unsafe advice", "Someone may be at risk", "Sexual content", "Spam or selling", "Personal information", "Other"].map((r) => html`<option>${r}</option>`)}</select></div>
    <div class="field"><label for="rd">Details (optional)</label><textarea id="rd" name="details" maxlength="1000"></textarea></div>
    <p class="hint">If someone is in immediate danger, call 112.</p>`,
    onOk: async (fd) => { const r = await POST("community/reports", { target_type: type, target_id: id, reason: String(fd.get("reason")).slice(0, 40), details: val(fd, "details") }); toast(r.message); } });
}

async function groupPage(main, gid, prof) {
  const g = await GET(`community/groups/${gid}/posts`);
  main.innerHTML = html`<p><a href="#/community" class="btn small quiet">← Community</a></p>${head(g.group.name, g.group.description)}
    ${g.joined ? html`<form class="card" data-form="post" style="margin-bottom:16px"><label for="pb">Share with the group</label>
      <textarea id="pb" name="body" required maxlength="4000" placeholder="A question, an experience, a win, a tip…"></textarea>
      <div class="row between" style="margin-top:8px"><select name="kind" aria-label="Post type" style="width:auto">${Object.entries(POST_KINDS).map(([k, l]) => html`<option value="${k}">${l}</option>`)}</select><button class="btn primary">Post</button></div>
      <p class="hint">Share experience, not medical advice. Keep personal details out of posts.</p></form>`
      : html`<div class="alert info">Join this group to post and reply. <button class="btn small" data-act="join">Join</button></div>`}
    <div class="card">${g.posts.length ? g.posts.map((p) => html`<article class="post"><div class="row between"><div class="row"><strong>@${p.handle || "member"}</strong><span class="chip">${POST_KINDS[p.kind] || p.kind}</span>
        ${p.status === "held" ? html`<span class="chip amber">Waiting for a moderator</span>` : ""}<small>${fmtWhen(p.created_at)}</small></div>
        <div class="row">${p.mine || g.is_moderator ? html`<button class="btn small quiet" data-act="delpost" data-id="${p.id}">Remove</button>` : ""}
          ${!p.mine ? html`<button class="btn small quiet" data-act="report" data-t="post" data-id="${p.id}">Report</button><button class="btn small quiet" data-act="block" data-u="${p.author_id}">Block</button>` : ""}</div></div>
      <div class="post-body">${p.body}</div>
      ${p.status === "visible" ? html`<div class="row">${Object.entries(REACTS).map(([k, l]) => html`<button class="btn small ${p.my_reactions.includes(k) ? "primary" : ""}" data-act="react" data-id="${p.id}" data-k="${k}" aria-pressed="${p.my_reactions.includes(k)}">${l} ${p.reactions[k] || ""}</button>`)}</div>` : ""}
      ${p.comments.map((c) => html`<div class="comment"><div class="row between"><span><strong>@${c.handle || "member"}</strong> <small>${fmtWhen(c.created_at)}</small>${c.status === "held" ? html` <span class="chip amber">Waiting for a moderator</span>` : ""}</span>
        ${c.author_id !== S.user.id ? html`<button class="btn small quiet" data-act="report" data-t="comment" data-id="${c.id}">Report</button>` : ""}</div><div style="white-space:pre-wrap">${c.body}</div></div>`)}
      ${g.joined && p.status === "visible" ? html`<form class="row" data-form="comment" data-id="${p.id}" style="margin-top:8px"><label class="sr-only" for="c${p.id}">Reply</label><input id="c${p.id}" name="body" type="text" maxlength="2000" placeholder="Write a kind reply…" required style="flex:1"><button class="btn small">Reply</button></form>` : ""}
      </article>`) : emptyState("🌱", "No posts yet", "Be the first to say hello.")}</div>`.s;
  bind(main, {
    join: async () => { await POST(`community/groups/${gid}/join`); navigate(); },
    post: async (fd) => { const r = await POST(`community/groups/${gid}/posts`, { body: fd.get("body"), kind: fd.get("kind") }); if (r.message) dialog({ title: r.status === "held" ? "Held for a moderator" : "Posted", body: html`<p>${r.message}</p>`, okText: "OK", cancelText: "" }); navigate(); },
    comment: async (fd, f) => { const r = await POST(`community/posts/${f.dataset.id}/comments`, { body: fd.get("body") }); if (r.message) toast(r.message, r.status === "held"); navigate(); },
    react: async (b) => { await POST(`community/posts/${b.dataset.id}/react?kind=${b.dataset.k}`); navigate(); },
    report: (b) => reportDialog(b.dataset.t, Number(b.dataset.id)),
    block: async (b) => { if (await confirmDlg("Block this person?", "You won't see their posts and they can't contact you.", "Block", true)) { await POST("community/blocks", { user_id: Number(b.dataset.u) }); navigate(); } },
    delpost: async (b) => { await DEL("community/posts/" + b.dataset.id); navigate(); },
  });
}

async function messageThread(main, other) {
  const r = await GET("community/messages/" + other);
  main.innerHTML = html`<p><a href="#/community/people" class="btn small quiet">← People</a></p>${head("Messages", "Private between connected adults. You can report or block at any time.")}
    <div class="card"><div class="thread" id="thread">${r.messages.length ? r.messages.map((m) => html`<div class="msg ${m.sender_id === S.user.id ? "user" : "assistant"}">${m.body}
      ${m.status === "held" ? html`<br><small>(held for review)</small>` : ""}${m.sender_id !== S.user.id ? html`<br><button class="btn small quiet" data-act="report" data-id="${m.id}">Report</button>` : ""}</div>`) : html`<p class="muted">Say hello.</p>`}</div>
    <form class="row" data-form="send" style="margin-top:12px"><label class="sr-only" for="dm">Message</label><input id="dm" name="body" type="text" maxlength="2000" required style="flex:1"><button class="btn primary">${t("Send")}</button></form>
    <p class="hint">Never share passwords or money details. If something feels wrong, block and report.</p>
    <button class="btn small danger" data-act="block">Block this person</button></div>`.s;
  const th = $("#thread"); th.scrollTop = th.scrollHeight;
  bind(main, {
    send: async (fd) => { const res = await POST("community/messages/" + other, { body: fd.get("body") }); if (res.message) toast(res.message, true); navigate(); },
    report: (b) => reportDialog("message", Number(b.dataset.id)),
    block: async () => { if (await confirmDlg("Block this person?", "They won't be able to message you.", "Block", true)) { await POST("community/blocks", { user_id: other }); location.hash = "#/community/people"; } },
  });
}

/* ============================================================ events & groups */
const EV_TYPES = { support_group: "Support group", workshop: "Workshop", social_gathering: "Gathering", club: "Club", community_meeting: "Community meeting", activity: "Activity", clinic_session: "Clinic session" };
const ACCESS = { sensory_friendly: "Sensory-friendly", quiet_room: "Quiet room", wheelchair_access: "Wheelchair access", captioning: "Captions", sign_language: "Sign language", low_lighting: "Low lighting", online: "Online" };
route("events", async (main, sub) => {
  const qs = new URLSearchParams(sub ? decodeURIComponent(sub) : "");
  const [ev, mine] = await Promise.all([GET("events?" + qs.toString()), GET("events-mine")]);
  const regs = mine.registrations.filter((r) => r.status !== "cancelled");
  main.innerHTML = html`${head(t("Events & groups"), "Support circles, clubs, workshops, gatherings and activities. You approve the exact details before anything is booked.",
      html`<a class="btn" href="#/assistant/new/${encodeURIComponent("Find an event for me and sign me up: ")}/agent">✨ Ask the agent to find & book</a>${!S.user.is_minor ? html`<button class="btn" data-act="propose">+ Propose an event</button>` : ""}`)}
    ${regs.length ? html`<div class="card tint-teal" style="margin-bottom:16px"><h3>My bookings</h3><ul class="list">${regs.map((r) => html`<li class="item"><div class="grow"><div class="item-title">${r.title} ${r.is_demo ? html`<span class="chip amber">Demo listing</span>` : ""}</div>
      <small>${fmtWhen(r.start_time)} · ${r.is_online ? "Online" : r.location}</small><div class="row"><span class="chip ${r.status === "confirmed" ? "sage" : "amber"}">${r.status === "confirmed" ? "Confirmed" : "Waitlisted"}</span>${r.confirmation_code ? html`<span class="chip">Ref ${r.confirmation_code}</span>` : ""}</div></div>
      <button class="btn small quiet" data-act="cancel" data-id="${r.registration_id}">Cancel</button></li>`)}</ul></div>` : ""}
    <form class="card soft row" data-form="filter" style="margin-bottom:16px;align-items:flex-end">
      <div style="flex:2;min-width:180px"><label for="eq">Search</label><input id="eq" name="q" type="search" value="${qs.get("q") || ""}" placeholder="e.g. ADHD, parents, art"></div>
      <div style="flex:1;min-width:150px"><label for="et3">Type</label><select id="et3" name="event_type"><option value="">Any</option>${Object.entries(EV_TYPES).map(([k, l]) => html`<option value="${k}" ${raw(qs.get("event_type") === k ? "selected" : "")}>${l}</option>`)}</select></div>
      <div style="flex:1;min-width:150px"><label for="ea">Accessibility</label><select id="ea" name="accessibility"><option value="">Any</option>${Object.entries(ACCESS).map(([k, l]) => html`<option value="${k}" ${raw(qs.get("accessibility") === k ? "selected" : "")}>${l}</option>`)}</select></div>
      <button class="btn">Filter</button></form>
    ${ev.note ? html`<div class="alert warn">${ev.note}</div>` : ""}
    ${ev.events.length ? html`<div class="grid g2">${ev.events.map((e) => html`<article class="card"><div class="row"><span class="chip teal">${EV_TYPES[e.event_type] || e.event_type}</span>${e.is_demo ? html`<span class="chip amber">Demo listing — not a real event</span>` : ""}</div>
      <h3 style="margin-top:8px">${e.title}</h3><p class="muted">${e.description || ""}</p>
      <dl class="kv"><dt>When</dt><dd>${fmtWhen(e.start_time)}–${fmtTime(e.end_time)}</dd><dt>Where</dt><dd>${e.is_online ? "Online" : e.location}</dd><dt>Cost</dt><dd>${e.fee_amount ? `₹${e.fee_amount}` : "Free"}</dd>
        <dt>Seats</dt><dd>${e.seats_left ? `${e.seats_left} left` : "Full — waitlist"}</dd>${e.organizer ? html`<dt>Organiser</dt><dd>${e.organizer}</dd>` : ""}</dl>
      ${e.accessibility.length ? html`<div class="row" style="margin-top:8px">${e.accessibility.map((a) => html`<span class="chip sage">${ACCESS[a] || a}</span>`)}</div>` : ""}
      <p style="margin-top:12px"><button class="btn primary small" data-act="book" data-id="${e.event_id}">${e.seats_left ? "Book a place" : "Join waitlist"}</button></p></article>`)}</div>`
      : html`<div class="card">${emptyState("📅", "No events match", "Try fewer filters — or propose one!")}</div>`}`.s;
  bind(main, {
    filter: (fd) => { const p = new URLSearchParams(); for (const k of ["q", "event_type", "accessibility"]) if (fd.get(k)) p.set(k, fd.get(k)); location.hash = "#/events/" + encodeURIComponent(p.toString()); },
    book: async (b) => {
      const id = Number(b.dataset.id); let att = 1;
      const show = async () => {
        const pr = await GET(`events/${id}/prepare?attendees=${att}`); const s = pr.summary;
        const d = dialog({ title: "Check the details", okText: s.seats_left >= att ? "Confirm booking" : "Join waitlist", body: html`
          <p>NeuroBridge will book <strong>exactly</strong> this. If anything changes before it's done, I'll ask you again.</p>
          <dl class="kv"><dt>Event</dt><dd>${s.title}</dd><dt>When</dt><dd>${fmtWhen(s.start)}–${fmtTime(s.end)}</dd><dt>Where</dt><dd>${s.where}</dd><dt>Cost</dt><dd>${s.fee}</dd><dt>Organiser</dt><dd>${s.organizer || "—"}</dd></dl>
          ${s.demo_listing ? html`<div class="alert warn" style="margin-top:12px">This is a demo listing for trying NeuroBridge — not a real event.</div>` : ""}
          <div class="grid g2" style="margin-top:12px"><div class="field"><label for="ba">People attending</label><input id="ba" name="att" type="number" min="1" max="6" value="${att}"></div>
          <div class="field"><label for="bn">Access needs to share with the organiser (optional)</label><input id="bn" name="needs" type="text" maxlength="500"></div></div>
          <label class="check"><input type="checkbox" name="ok" required> I approve these exact details.</label>`,
          onOk: async (fd) => {
            const n = Number(fd.get("att") || 1); if (n !== att) { att = n; setTimeout(show, 0); return; }
            if (!fd.get("ok")) throw new Error("Tick the box to approve.");
            try { const r = await POST(`events/${id}/register`, { attendees: att, needs: val(fd, "needs"), approved_details_hash: pr.details_hash, explicit_approval: true });
              dialog({ title: r.status === "confirmed" ? "You're booked 🎉" : "You're on the waitlist", okText: "OK", cancelText: "", body: html`<p>${r.message}</p>${r.confirmation_code ? html`<p>Reference: <strong>${r.confirmation_code}</strong></p>` : ""}<p class="hint">${r.scope}</p>` }); navigate();
            } catch (e) { if (e.data?.detail?.approval_stale) { toast("The details changed — please check again.", true); setTimeout(show, 0); } else throw e; }
          } });
        $("#ba", d).onchange = (e) => { att = Number(e.target.value) || 1; d.close(); d.remove(); show(); };
      };
      await show();
    },
    cancel: async (b) => { if (await confirmDlg("Cancel this booking?", "Your place will go to the next person on the waitlist.", "Cancel booking", true)) { const r = await POST(`events/registrations/${b.dataset.id}/cancel`); toast("Cancelled."); navigate(); } },
    propose: () => dialog({ title: "Propose an event", wide: true, body: html`<p class="muted">Clubs, meetups, workshops, gatherings… An admin reviews it before it's listed.</p>
      <div class="grid g2"><div class="field"><label for="pt">Title</label><input id="pt" name="title" type="text" required minlength="3" maxlength="120"></div>
      <div class="field"><label for="pty">Type</label><select id="pty" name="event_type">${Object.entries(EV_TYPES).filter(([k]) => k !== "clinic_session").map(([k, l]) => html`<option value="${k}">${l}</option>`)}</select></div></div>
      <div class="field"><label for="pd">Description</label><textarea id="pd" name="description" maxlength="2000"></textarea></div>
      <div class="grid g2"><div class="field"><label for="ps">Starts</label><input id="ps" name="start" type="datetime-local" required></div><div class="field"><label for="pe">Ends</label><input id="pe" name="end" type="datetime-local" required></div>
      <div class="field"><label for="pl">Place</label><input id="pl" name="location" type="text" maxlength="200"></div><div class="field"><label for="pc">Capacity</label><input id="pc" name="capacity" type="number" min="1" max="500" value="10" required></div></div>
      <label class="check"><input type="checkbox" name="online"> Online</label>
      <fieldset style="border:0;padding:0;margin-top:12px"><legend style="font-weight:550">Accessibility</legend><div class="row">${Object.entries(ACCESS).map(([k, l]) => html`<label class="check" style="margin-right:12px"><input type="checkbox" name="acc" value="${k}"> ${l}</label>`)}</div></fieldset>`,
      onOk: async (fd) => { const r = await POST("events/propose", { title: val(fd, "title"), event_type: fd.get("event_type"), description: val(fd, "description"), start_time: fd.get("start") + ":00", end_time: fd.get("end") + ":00",
        capacity: Number(fd.get("capacity")), location: val(fd, "location"), is_online: !!fd.get("online"), accessibility: fd.getAll("acc") }); toast(r.message); } }),
  });
});

/* ============================================================ moderation (admins) */
route("moderation", async (main) => {
  const [q, pe] = await Promise.all([GET("community/moderation"), isAdmin() ? GET("admin/events/pending") : { events: [] }]);
  const item = (type, x) => html`<li class="item"><div class="grow"><div style="white-space:pre-wrap">${x.body}</div><small>${type} #${x.id} · ${fmtWhen(x.created_at)}${x.hold_reason ? " · held: " + x.hold_reason : ""}</small></div>
    <div class="row"><button class="btn small primary" data-act="m" data-t="${type}" data-id="${x.id}" data-a="approve">Approve</button><button class="btn small danger" data-act="m" data-t="${type}" data-id="${x.id}" data-a="remove">Remove</button></div></li>`;
  main.innerHTML = html`${head(t("Moderation"), "Review held content, reports and proposed events. Be fair, explain decisions, protect people.")}
    <div class="grid g2"><div class="card"><h3>Held posts & comments</h3>${q.held_posts.length + q.held_comments.length + q.held_messages.length ? html`<ul class="list">${q.held_posts.map((x) => item("post", x))}${q.held_comments.map((x) => item("comment", x))}${q.held_messages.map((x) => item("message", x))}</ul>` : html`<p class="muted">Nothing waiting.</p>`}
      <p class="hint">Posts held for “safety” may be from someone in distress: consider reaching out with support resources (112, Tele-MANAS 14416).</p></div>
    <div class="card"><h3>Open reports</h3>${q.reports.length ? html`<ul class="list">${q.reports.map((r) => html`<li class="item"><div class="grow"><strong>${r.reason}</strong> — ${r.target_type} #${r.target_id}${r.details ? html`<br><small>${r.details}</small>` : ""}<br><small>${fmtWhen(r.created_at)}</small></div>
      <div class="row">${r.target_type !== "user" ? html`<button class="btn small danger" data-act="m" data-t="${r.target_type}" data-id="${r.target_id}" data-a="remove">Remove item</button>` : html`<button class="btn small danger" data-act="m" data-t="user" data-id="${r.target_id}" data-a="disable_user">Disable user</button>`}
      <button class="btn small" data-act="dismiss" data-id="${r.id}" data-t="${r.target_type}" data-tid="${r.target_id}">Dismiss</button></div></li>`)}</ul>` : html`<p class="muted">No open reports.</p>`}</div>
    ${isAdmin() ? html`<div class="card"><h3>Proposed events</h3>${pe.events.length ? html`<ul class="list">${pe.events.map((e) => html`<li class="item"><div class="grow"><strong>${e.title}</strong> (${EV_TYPES[e.event_type]})<br><small>${fmtWhen(e.start_time)} · ${e.is_online ? "Online" : e.location} · by ${e.organizer}</small><p>${e.description || ""}</p></div>
      <div class="row"><button class="btn small primary" data-act="ev" data-id="${e.event_id}" data-ok="true">Publish</button><button class="btn small" data-act="ev" data-id="${e.event_id}" data-ok="false">Reject</button></div></li>`)}</ul>` : html`<p class="muted">None waiting.</p>`}</div>` : ""}</div>`.s;
  bind(main, {
    m: async (b) => { await POST("community/moderation", { target_type: b.dataset.t, target_id: Number(b.dataset.id), action: b.dataset.a }); toast("Done."); navigate(); },
    dismiss: async (b) => { await POST("community/moderation", { target_type: b.dataset.t, target_id: Number(b.dataset.tid), action: "dismiss_report", report_id: Number(b.dataset.id) }); navigate(); },
    ev: async (b) => { await POST(`admin/events/${b.dataset.id}/review?approve=${b.dataset.ok}`); navigate(); },
  });
});

/* ============================================================ boot */
async function boot(fresh = false) {
  if (!S.token) return renderAuth();
  try {
    const me = await GET("me");
    S.user = me.user; S.prefs = me.prefs; S.unread = me.unread_notifications; S.people = null; S.status = null;
    applyPrefs(); renderShell();
    if (fresh) location.hash = "#/home";
    await navigate();
    clearInterval(boot.timer); boot.timer = setInterval(pollNotifications, 60000); pollNotifications();
  } catch (e) { if (!S.user) renderAuth(); else fail(e); }
}
window.addEventListener("hashchange", navigate);
boot();
