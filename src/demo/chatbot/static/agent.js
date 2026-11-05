/* Agent console: claim queued handoffs, read the transcript, reply, close. textContent only. */
(function () {
  "use strict";

  const $ = function (id) { return document.getElementById(id); };
  const state = { token: null, agent: null, selected: null, lastId: 0, timer: null };
  try {
    state.token = sessionStorage.getItem("jim.admin");
    state.agent = sessionStorage.getItem("jim.agent");
  } catch (e) { /* memory only */ }

  async function api(path, options) {
    const opts = Object.assign({ method: "GET", headers: {} }, options || {});
    opts.headers = Object.assign({ Authorization: "Bearer " + state.token }, opts.headers);
    if (opts.body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.body); }
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    return { ok: r.ok, status: r.status, data: data || {} };
  }

  function bubble(m) {
    const wrap = document.createElement("div");
    const role = m.role === "user" ? "user" : m.role === "agent" ? "agent" : m.role === "system" ? "system" : "assistant";
    wrap.className = "msg " + (role === "user" ? "assistant" : role === "assistant" ? "user" : role);
    const b = document.createElement("div");
    b.className = "bubble";
    b.textContent = m.content;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = (m.role === "user" ? "Customer" : m.role === "assistant" ? "Bot" : m.role === "agent" ? "Agent" : "System") +
      " · " + new Date(m.created_at).toLocaleTimeString();
    wrap.appendChild(b);
    wrap.appendChild(meta);
    return wrap;
  }

  async function loadQueue() {
    const r = await api("/api/admin/handoffs");
    if (r.status === 401 || r.status === 503) {
      $("auth-error").textContent = r.status === 503 ? "Admin access disabled (set ADMIN_TOKEN)." : "Invalid token.";
      $("console").classList.add("hidden");
      return false;
    }
    if (!r.ok) return true;
    const list = $("queue");
    list.textContent = "";
    const items = r.data.handoffs || [];
    $("queue-count").textContent = items.length + " open";
    items.forEach(function (h) {
      const item = document.createElement("div");
      item.className = "queue-item" + (state.selected === h.id ? " active" : "");
      item.setAttribute("role", "listitem");
      item.tabIndex = 0;
      const title = document.createElement("div");
      title.textContent = (h.status === "queued" ? "Waiting" : "Claimed by " + h.agent_name) + " · " + new Date(h.created_at).toLocaleTimeString();
      const reason = document.createElement("div");
      reason.className = "muted small";
      reason.textContent = h.reason || "No reason given";
      item.appendChild(title);
      item.appendChild(reason);
      item.addEventListener("click", function () { select(h.id); });
      item.addEventListener("keydown", function (e) { if (e.key === "Enter") select(h.id); });
      list.appendChild(item);
    });
    return true;
  }

  async function select(id) {
    state.selected = id;
    state.lastId = 0;
    $("transcript").textContent = "";
    await loadTranscript();
    loadQueue();
  }

  async function loadTranscript() {
    if (!state.selected) return;
    const r = await api("/api/admin/handoffs/" + encodeURIComponent(state.selected) + "?after=" + state.lastId);
    if (!r.ok) return;
    const h = r.data.handoff;
    $("conv-title").textContent = h.status === "closed" ? "Closed conversation" : h.status === "queued" ? "Waiting for an agent" : "Claimed by " + h.agent_name;
    (r.data.messages || []).forEach(function (m) {
      state.lastId = Math.max(state.lastId, m.id);
      $("transcript").appendChild(bubble(m));
    });
    $("transcript").scrollTop = $("transcript").scrollHeight;
    const mine = h.status === "claimed" && h.agent_name === state.agent;
    $("claim").disabled = h.status !== "queued";
    $("close").disabled = h.status === "closed";
    $("reply").disabled = !mine;
    $("send").disabled = !mine;
  }

  function startLoop() {
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(function () { loadQueue(); loadTranscript(); }, 3000);
  }

  $("auth-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    state.token = $("token").value.trim();
    state.agent = $("agent-name").value.trim();
    try { sessionStorage.setItem("jim.admin", state.token); sessionStorage.setItem("jim.agent", state.agent); } catch (err) { /* memory only */ }
    if (await loadQueue()) { $("auth-error").textContent = ""; $("console").classList.remove("hidden"); startLoop(); }
  });
  $("claim").addEventListener("click", async function () {
    const r = await api("/api/admin/handoffs/" + encodeURIComponent(state.selected) + "/claim", { method: "POST", body: { agent_name: state.agent } });
    $("console-error").textContent = r.ok ? "" : (r.data.message || "Could not claim.");
    loadTranscript(); loadQueue();
  });
  $("close").addEventListener("click", async function () {
    const r = await api("/api/admin/handoffs/" + encodeURIComponent(state.selected) + "/close", { method: "POST", body: {} });
    $("console-error").textContent = r.ok ? "" : (r.data.message || "Could not close.");
    loadTranscript(); loadQueue();
  });
  $("reply-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    const content = $("reply").value.trim();
    if (!content) return;
    const r = await api("/api/admin/handoffs/" + encodeURIComponent(state.selected) + "/messages", { method: "POST", body: { content: content } });
    if (r.ok) { $("reply").value = ""; loadTranscript(); } else { $("console-error").textContent = r.data.message || "Send failed."; }
  });
  $("reply").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("reply-form").requestSubmit(); }
  });
  if (state.token) { $("token").value = state.token; }
  if (state.agent) { $("agent-name").value = state.agent; }
})();
