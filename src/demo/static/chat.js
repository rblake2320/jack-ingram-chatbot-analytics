"use strict";
const messages = document.getElementById("messages");
const form = document.getElementById("chatForm");
const input = document.getElementById("message");
const status = document.getElementById("chatStatus");
const consent = document.getElementById("consent");
let busy = false;

function setBusy(value) {
  busy = value;
  document.querySelectorAll("button, #message, #consent").forEach(el => { el.disabled = value; });
  status.textContent = value ? "Preparing your reply…" : "";
}
function addMessage(text, role, source) {
  const div = document.createElement("div");
  div.className = "message " + role;
  div.textContent = text;
  if (source) {
    const tag = document.createElement("small");
    tag.className = "source";
    tag.textContent = source.replaceAll("_", " ");
    div.appendChild(tag);
  }
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
}
async function post(url, body) {
  const response = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body), signal: AbortSignal.timeout(25000)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.response || "Request unavailable. Please try again.");
  return data;
}
async function send(text) {
  if (busy || !text.trim()) return;
  addMessage(text.trim(), "user");
  input.value = "";
  setBusy(true);
  try {
    const data = await post("/api/chat", { message: text.trim(), analytics_consent: consent.checked });
    if (typeof data.response !== "string" || !data.response.trim()) throw new Error("The reply was empty. Please retry.");
    addMessage(data.response, "assistant", data.source);
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
  setBusy(true);
  try {
    await post(forget ? "/api/privacy" : "/api/reset", {});
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
