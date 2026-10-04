"use strict";
const messages = document.getElementById("messages");
const form = document.getElementById("chatForm");
const input = document.getElementById("message");
const status = document.getElementById("chatStatus");
const consent = document.getElementById("consent");
const locationPicker = document.getElementById("location");
let sessionToken = document.body.dataset.sessionToken || "";
let busy = false;
let expired = false;

function setBusy(value) {
  busy = value;
  document.querySelectorAll("button, #message, #consent, #location").forEach(el => { el.disabled = value; });
  status.textContent = value ? "Preparing your reply…" : "";
}
function addMessage(text, role, source, links = [], citations = []) {
  const div = document.createElement("div");
  div.className = "message " + role;
  div.textContent = text;
  if (source) {
    const tag = document.createElement("small");
    tag.className = "source";
    tag.textContent = source.replaceAll("_", " ");
    div.appendChild(tag);
  }
  for (const item of [...links, ...citations.map(c => ({label: "Source: " + c.label + " · reviewed " + c.reviewed_at, url: c.url}))]) {
    try {
      const url = new URL(item.url);
      const hosts = ["www.jackingram.com", "www.audimontgomery.com", "www.jackingrammercedes.com",
        "www.jackingramnissan.com", "jackingrammotors.porsche.com", "service-booking.aftersales.porsche.com",
        "www.jackingramvolkswagen.com", "www.jackingramvolvocars.com", "www.jackingramsignatureusedcars.com", "www.jackingrambodyshop.com"];
      if (url.protocol !== "https:" || !hosts.includes(url.hostname) || url.username || url.password) continue;
      const a = document.createElement("a");
      a.className = "answer-link";
      a.textContent = item.label + " ↗";
      a.href = url.href; a.target = "_blank"; a.rel = "noopener noreferrer";
      div.appendChild(a);
    } catch { /* Reject non-URLs. */ }
  }
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}
async function post(url, body) {
  const response = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json", ...(sessionToken ? {"X-Chat-Session": sessionToken} : {}) },
    body: JSON.stringify(body), signal: AbortSignal.timeout(25000)
  });
  const data = await response.json();
  if (!response.ok) {
    if (data.error === "session_expired") {
      expired = true;
      document.getElementById("reset").textContent = "Start fresh";
      throw new Error("Your session expired. Select Start fresh to begin again.");
    }
    throw new Error(data.response || "Request unavailable. Please try again.");
  }
  return data;
}
async function send(text) {
  if (busy || !text.trim()) return;
  addMessage(text.trim(), "user");
  input.value = "";
  setBusy(true);
  try {
    const data = await post("/api/chat", { message: text.trim(), analytics_consent: consent.checked,
      location_id: locationPicker.value || null });
    if (typeof data.response !== "string" || !data.response.trim()) throw new Error("The reply was empty. Please retry.");
    addMessage(data.response, "assistant", data.source, data.links, data.citations);
    if (data.location_id) locationPicker.value = data.location_id;
  } catch (error) {
    addMessage(error.name === "TimeoutError" ? "The reply timed out. Please try again." : error.message, "assistant", "error");
  } finally {
    setBusy(false);
    input.focus({ preventScroll: true });
  }
}
form.addEventListener("submit", e => { e.preventDefault(); send(input.value); });
document.querySelectorAll("[data-question]").forEach(el => {
  el.addEventListener("click", () => send(el.dataset.question));
});
async function reset(forget = false) {
  if (busy) return;
  if (expired) { window.location.reload(); return; }
  setBusy(true);
  try {
    const data = await post(forget ? "/api/privacy" : "/api/reset", {});
    if (data.session_token) sessionToken = data.session_token;
    messages.replaceChildren();
    if (forget) consent.checked = false;
    addMessage(forget ? "Your conversation and analytics for this browser session have been deleted."
      : "A fresh start. How can I help you today?", "assistant");
  } catch (error) { addMessage(error.message, "assistant", "error"); }
  finally { setBusy(false); }
}
document.getElementById("reset").addEventListener("click", () => reset());
document.getElementById("forget").addEventListener("click", () => reset(true));
consent.addEventListener("change", () => { if (!consent.checked) reset(true); });
if (document.body.classList.contains("embedded") && window.parent !== window) {
  const parentOrigin = new URLSearchParams(window.location.search).get("parent");
  window.addEventListener("keydown", event => {
    if (event.key === "Escape" && parentOrigin) window.parent.postMessage({type: "jack-ingram-close"}, parentOrigin);
  });
}
