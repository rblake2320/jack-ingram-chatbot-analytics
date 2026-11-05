/* Customer chat client. All server/user text is rendered with textContent (no innerHTML). */
(function () {
  "use strict";

  const TOKEN_KEY = "jim.conversation";
  const MAX_CHARS = 2000;
  const els = {
    messages: document.getElementById("messages"),
    typing: document.getElementById("typing"),
    form: document.getElementById("composer"),
    input: document.getElementById("input"),
    send: document.getElementById("send"),
    counter: document.getElementById("counter"),
    chips: document.getElementById("chips"),
    banner: document.getElementById("handoff-banner"),
  };
  const state = { lastId: 0, busy: false, polling: null, rendered: new Set() };

  function store(key, value) {
    try {
      if (value === null) sessionStorage.removeItem(key);
      else sessionStorage.setItem(key, value);
    } catch (e) { /* storage unavailable: conversation lasts for this page only */ }
  }
  function load(key) {
    try { return sessionStorage.getItem(key); } catch (e) { return null; }
  }
  let token = load(TOKEN_KEY);

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "id-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  }

  async function api(path, options) {
    const opts = Object.assign({ method: "GET", headers: {} }, options || {});
    opts.headers = Object.assign({}, opts.headers);
    if (token) opts.headers["X-Conversation-Token"] = token;
    if (opts.body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const response = await fetch(path, opts);
    let data = null;
    try { data = await response.json(); } catch (e) { data = null; }
    return { ok: response.ok, status: response.status, data: data || {}, headers: response.headers };
  }

  function errorMessage(result) {
    const d = result.data || {};
    if (result.status === 429) {
      const wait = result.headers.get("Retry-After");
      return "You're sending requests quickly. Please wait" + (wait ? " " + wait + " seconds" : " a moment") + ".";
    }
    if (d.message) return d.message;
    if (Array.isArray(d.details) && d.details.length) {
      return d.details.map(function (x) { return (x.loc || []).slice(-1)[0] + ": " + x.msg; }).join("; ");
    }
    if (result.status === 409) return "Still working on your previous message…";
    return "Something went wrong. Please try again.";
  }

  function addMessage(role, text, opts) {
    opts = opts || {};
    if (opts.id) {
      if (state.rendered.has(opts.id)) return;
      state.rendered.add(opts.id);
      state.lastId = Math.max(state.lastId, opts.id);
    }
    const wrap = document.createElement("div");
    wrap.className = "msg " + role;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    if ((role === "assistant" || role === "agent") && opts.id) {
      const meta = document.createElement("div");
      meta.className = "meta feedback";
      if (role === "agent") {
        const who = document.createElement("span");
        who.textContent = "Team member";
        meta.appendChild(who);
      }
      [["Helpful", 1], ["Not helpful", -1]].forEach(function (pair) {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = pair[0];
        b.setAttribute("aria-pressed", "false");
        b.addEventListener("click", function () { rate(opts.id, pair[1], meta, b); });
        meta.appendChild(b);
      });
      wrap.appendChild(meta);
    }
    els.messages.appendChild(wrap);
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  async function rate(messageId, rating, meta, button) {
    const r = await api("/api/feedback", { method: "POST", body: { message_id: messageId, rating: rating } });
    if (r.ok) {
      meta.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
      button.setAttribute("aria-pressed", "true");
    }
  }

  function setHandoff(handoff, status) {
    if (!handoff && status !== "agent") {
      els.banner.classList.add("hidden");
      stopPolling();
      return;
    }
    let text;
    if (status === "agent" || (handoff && handoff.status === "claimed")) {
      text = "You're chatting with a member of our team.";
    } else if (handoff && handoff.within_hours) {
      text = "A team member has been notified and will join shortly.";
    } else {
      text = "Our team is away right now" + (handoff && handoff.next_opening ? " and will follow up " + handoff.next_opening : "") +
        ". Use “Contact me” to leave your number.";
    }
    els.banner.textContent = text;
    els.banner.classList.remove("hidden");
    startPolling();
  }

  async function poll() {
    if (!token) return;
    const r = await api("/api/chat/messages?after=" + state.lastId);
    if (r.status === 401 || r.status === 404) { stopPolling(); return; }
    if (!r.ok) return;
    (r.data.messages || []).forEach(function (m) { addMessage(m.role, m.content, { id: m.id }); });
    setHandoff(r.data.handoff, r.data.status);
  }
  function startPolling() { if (!state.polling) state.polling = setInterval(poll, 4000); }
  function stopPolling() { if (state.polling) { clearInterval(state.polling); state.polling = null; } }

  async function send(text) {
    text = (text || "").trim();
    if (!text || state.busy) return;
    if (text.length > MAX_CHARS) { addMessage("system", "Messages are limited to " + MAX_CHARS + " characters."); return; }
    state.busy = true;
    els.send.disabled = true;
    els.typing.textContent = "Assistant is typing…";
    addMessage("user", text);
    try {
      const r = await api("/api/chat", { method: "POST", body: { message: text } });
      if (!r.ok) { addMessage("system", errorMessage(r)); return; }
      const d = r.data;
      if (d.conversation_token && d.conversation_token !== token) {
        token = d.conversation_token;
        store(TOKEN_KEY, token);
      }
      if (d.user_message_id) {
        state.rendered.add(d.user_message_id);
        state.lastId = Math.max(state.lastId, d.user_message_id);
      }
      if (d.reply) addMessage("assistant", d.reply, { id: d.message_id });
      else if (d.source === "agent") addMessage("system", "Sent to our team member.");
      (d.appointments || []).forEach(offerCalendar);
      setHandoff(d.handoff, d.source === "agent" ? "agent" : null);
    } catch (e) {
      addMessage("system", "Connection problem. Please check your network and try again.");
    } finally {
      state.busy = false;
      els.send.disabled = false;
      els.typing.textContent = "";
    }
  }

  function offerCalendar(appointment) {
    if (!appointment || !appointment.ics) return;
    const wrap = document.createElement("div");
    wrap.className = "msg system";
    const b = document.createElement("button");
    b.className = "btn";
    b.type = "button";
    b.textContent = "Add " + appointment.confirmation_code + " to calendar";
    b.addEventListener("click", function () { downloadIcs(appointment); });
    wrap.appendChild(b);
    els.messages.appendChild(wrap);
  }
  function downloadIcs(appointment) {
    const blob = new Blob([appointment.ics], { type: "text/calendar" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "appointment-" + appointment.confirmation_code + ".ics";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  async function restore() {
    if (!token) { welcome(); return; }
    const r = await api("/api/chat/messages?after=0");
    if (!r.ok) { token = null; store(TOKEN_KEY, null); welcome(); return; }
    (r.data.messages || []).forEach(function (m) { addMessage(m.role, m.content, { id: m.id }); });
    if (!(r.data.messages || []).length) welcome();
    setHandoff(r.data.handoff, r.data.status);
  }
  function welcome() {
    addMessage("assistant", "Hi! I can search inventory, estimate payments and trade-ins, check recalls, book service or a test drive, or connect you with our team. How can I help?");
  }

  // ----- composer -----
  els.form.addEventListener("submit", function (e) {
    e.preventDefault();
    const text = els.input.value;
    els.input.value = "";
    updateCounter();
    send(text);
  });
  els.input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); els.form.requestSubmit(); }
  });
  function updateCounter() {
    els.counter.textContent = els.input.value.length + " / " + MAX_CHARS;
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight, 160) + "px";
  }
  els.input.addEventListener("input", updateCounter);
  els.chips.addEventListener("click", function (e) {
    const chip = e.target.closest("[data-prompt]");
    if (chip) send(chip.getAttribute("data-prompt"));
  });
  document.getElementById("new-chat").addEventListener("click", async function () {
    stopPolling();
    token = null;
    store(TOKEN_KEY, null);
    state.lastId = 0;
    state.rendered.clear();
    els.messages.textContent = "";
    els.banner.classList.add("hidden");
    welcome();
  });

  // ----- dialogs -----
  document.querySelectorAll("dialog [data-close]").forEach(function (b) {
    b.addEventListener("click", function () { b.closest("dialog").close(); });
  });

  const booking = {
    dialog: document.getElementById("booking-dialog"),
    form: document.getElementById("booking-form"),
    dept: document.getElementById("b-dept"),
    date: document.getElementById("b-date"),
    slots: document.getElementById("b-slots"),
    error: document.getElementById("b-error"),
    success: document.getElementById("b-success"),
    ics: document.getElementById("b-ics"),
    submit: document.getElementById("b-submit"),
    key: null,
    last: null,
  };
  async function loadSlots() {
    booking.slots.textContent = "Loading…";
    const params = new URLSearchParams({ department: booking.dept.value, days: "5" });
    if (booking.date.value) params.set("date_from", booking.date.value);
    const r = await api("/api/appointments/availability?" + params.toString());
    booking.slots.textContent = "";
    if (!r.ok) { booking.slots.textContent = errorMessage(r); return; }
    const slots = r.data.slots || [];
    if (!slots.length) { booking.slots.textContent = "No open times in this range. Try a later date."; return; }
    slots.slice(0, 40).forEach(function (slot, i) {
      const label = document.createElement("label");
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "slot";
      radio.value = slot.start;
      if (i === 0) radio.checked = true;
      label.appendChild(radio);
      label.appendChild(document.createTextNode(slot.label));
      booking.slots.appendChild(label);
    });
  }
  document.getElementById("open-booking").addEventListener("click", function () {
    booking.key = uuid();
    booking.error.textContent = "";
    booking.success.classList.add("hidden");
    booking.ics.classList.add("hidden");
    booking.submit.disabled = false;
    booking.dialog.showModal();
    loadSlots();
  });
  booking.dept.addEventListener("change", loadSlots);
  booking.date.addEventListener("change", loadSlots);
  booking.ics.addEventListener("click", function () { if (booking.last) downloadIcs(booking.last); });
  booking.form.addEventListener("submit", async function (e) {
    e.preventDefault();
    booking.error.textContent = "";
    const slot = booking.form.querySelector("input[name=slot]:checked");
    if (!slot) { booking.error.textContent = "Choose a time."; return; }
    if (!document.getElementById("b-consent").checked) { booking.error.textContent = "Please agree to be contacted about this appointment."; return; }
    const body = {
      department: booking.dept.value,
      slot_start: slot.value,
      first_name: document.getElementById("b-first").value,
      last_name: document.getElementById("b-last").value,
      phone: document.getElementById("b-phone").value,
      email: document.getElementById("b-email").value || null,
      notes: document.getElementById("b-notes").value || null,
      consent_to_contact: true,
    };
    booking.submit.disabled = true;
    const r = await api("/api/appointments", { method: "POST", body: body, headers: { "Idempotency-Key": booking.key } });
    if (!r.ok) {
      booking.submit.disabled = false;
      booking.error.textContent = errorMessage(r);
      if (r.status === 409) loadSlots();
      return;
    }
    booking.last = r.data;
    booking.success.textContent = "Booked: " + r.data.label + " on " + r.data.start_label + ". Confirmation code " + r.data.confirmation_code + ".";
    booking.success.classList.remove("hidden");
    booking.ics.classList.remove("hidden");
    booking.key = uuid();
  });

  const lead = {
    dialog: document.getElementById("lead-dialog"),
    form: document.getElementById("lead-form"),
    error: document.getElementById("l-error"),
    success: document.getElementById("l-success"),
    submit: document.getElementById("l-submit"),
    key: null,
  };
  document.getElementById("open-lead").addEventListener("click", function () {
    lead.key = uuid();
    lead.error.textContent = "";
    lead.success.classList.add("hidden");
    lead.submit.disabled = false;
    lead.dialog.showModal();
  });
  lead.form.addEventListener("submit", async function (e) {
    e.preventDefault();
    lead.error.textContent = "";
    if (!document.getElementById("l-consent").checked) { lead.error.textContent = "Please agree to be contacted."; return; }
    const body = {
      first_name: document.getElementById("l-first").value,
      last_name: document.getElementById("l-last").value || null,
      phone: document.getElementById("l-phone").value || null,
      email: document.getElementById("l-email").value || null,
      interest: document.getElementById("l-interest").value,
      preferred_contact: document.getElementById("l-pref").value,
      comments: document.getElementById("l-comments").value || null,
      consent_to_contact: true,
    };
    lead.submit.disabled = true;
    const r = await api("/api/leads", { method: "POST", body: body, headers: { "Idempotency-Key": lead.key } });
    if (!r.ok) { lead.submit.disabled = false; lead.error.textContent = errorMessage(r); return; }
    lead.success.textContent = "Thanks, " + r.data.first_name + "! Our team will reach out soon.";
    lead.success.classList.remove("hidden");
  });

  restore();
})();
