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
function addMessage(text, role, source, links = [], citations = [], cards = [], recalls = []) {
  const div = document.createElement("div");
  div.className = "message " + role;
  div.textContent = text;
  if (source) {
    const tag = document.createElement("small");
    tag.className = "source";
    tag.textContent = cards.length ? "model guides · stock unverified" : source.replaceAll("_", " ");
    div.appendChild(tag);
  }
  for (const card of cards) {
    const box = document.createElement("article"); box.className = "vehicle-card";
    const title = document.createElement("strong"); title.textContent = card.name;
    const details = document.createElement("small");
    details.textContent = card.reference_year + (card.seats_max ? " · up to " + card.seats_max + " seats" : "") + " · model guide, not stock";
    box.append(title, details);
    if (["/vehicle-atlas", "/vehicle-atlas?subject=systems"].includes(card.explorer_url)) {
      const action = document.createElement("a"); action.href = card.explorer_url; action.target = "_blank";
      action.rel = "noopener"; action.className = "explore-action"; action.textContent = "Explore this model in 3D →";
      box.append(action);
    }
    div.append(box);
  }
  for (const recall of recalls) {
    const box=document.createElement('article');box.className='recall-card';box.dataset.campaign=recall.campaign;
    const title=document.createElement('strong');title.textContent=recall.campaign+' · '+recall.title;box.append(title);
    if(recall.do_not_drive){const urgent=document.createElement('p');urgent.className='recall-urgent';urgent.textContent='DO NOT DRIVE — follow the manufacturer remedy for affected vehicles.';box.append(urgent);}
    for(const [label,text] of [['Vehicle scope',recall.model_scope],['Issue',recall.summary],['Safety consequence',recall.consequence],['Manufacturer remedy',recall.remedy],['3D illustration scope',recall.geometry_scope]]){if(!text)continue;const p=document.createElement('p');p.textContent=label+': '+text;box.append(p);}
    if(/^\/vehicle-atlas\?subject=systems&recall=\d{2}V\d{6}&year=20\d{2}$/.test(recall.explorer_url || '')){const a=document.createElement('a');a.className='explore-action';a.href=recall.explorer_url;a.target='_blank';a.rel='noopener';a.textContent='Open this notice and show the system in 3D →';box.append(a);}
    const a=document.createElement('a');a.href='https://www.nhtsa.gov/recalls?nhtsaId='+encodeURIComponent(recall.campaign);a.target='_blank';a.rel='noopener noreferrer';a.textContent='Official campaign and VIN check ↗';box.append(a);div.append(box);
  }
  const citationBox = document.createElement("details"); citationBox.className = "answer-sources";
  const citationLabel = document.createElement("summary"); citationLabel.textContent = "Reviewed sources (" + citations.length + ")";
  citationBox.append(citationLabel);
  for (const item of [...links, ...citations.map(c => ({label: c.label + " · reviewed " + c.reviewed_at, url: c.url, citation: true}))]) {
    try {
      const url = new URL(item.url);
      const hosts = ["www.jackingram.com", "www.audimontgomery.com", "www.jackingrammercedes.com",
        "www.jackingramnissan.com", "jackingrammotors.porsche.com", "service-booking.aftersales.porsche.com",
        "www.jackingramvolkswagen.com", "www.jackingramvolvocars.com", "www.jackingramsignatureusedcars.com", "www.jackingrambodyshop.com",
        "www.nissanusa.com", "www.vw.com", "www.volvocars.com", "www.audiusa.com", "emea-dam.audi.com", "www.mbusa.com", "www.nhtsa.gov", "newsroom.porsche.com"];
      if (url.protocol !== "https:" || !hosts.includes(url.hostname) || url.username || url.password) continue;
      const a = document.createElement("a");
      a.className = "answer-link";
      a.textContent = item.label + " ↗";
      a.href = url.href; a.target = "_blank"; a.rel = "noopener noreferrer";
      (item.citation ? citationBox : div).appendChild(a);
    } catch { /* Reject non-URLs. */ }
  }
  if (citationBox.querySelector("a")) div.append(citationBox);
  messages.appendChild(div);
  if (role === "assistant") messages.scrollTop += div.getBoundingClientRect().top - messages.getBoundingClientRect().top - 8;
  else messages.scrollTop = messages.scrollHeight;
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
    addMessage(data.response, "assistant", data.source, data.links, data.citations, data.vehicle_cards, data.recall_cards);
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
