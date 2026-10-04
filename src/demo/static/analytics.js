"use strict";
let token = "";
let selectedWindow = "all";
let requestVersion = 0;
const auth = document.getElementById("authForm");
const dashboard = document.getElementById("dashboard");
const status = document.getElementById("dashboardStatus");
const labels = { messages: "Consented messages", visitors: "Browser sessions", errors: "Service errors", average_latency_ms: "Average reply · ms" };
async function load() {
  const version = ++requestVersion;
  status.textContent = "Loading insights…";
  try {
    const response = await fetch("/api/analytics?window=" + selectedWindow,
      { headers: { Authorization: "Bearer " + token }, signal: AbortSignal.timeout(10000) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error === "unauthorized" ? "Access denied. Check your admin token."
      : data.error === "analytics_admin_not_configured" ? "Admin analytics is not configured on this server." : "Insights unavailable.");
    if (version !== requestVersion) return;
    auth.hidden = true;
    dashboard.hidden = false;
    status.textContent = data.messages ? "Analytics updated." : "No consented activity in this period.";
    document.getElementById("metrics").replaceChildren();
    for (const [key, label] of Object.entries(labels)) {
      const tile = document.createElement("div"); tile.className = "metric";
      const value = document.createElement("strong"); value.textContent = Math.round(data[key] || 0).toLocaleString();
      const name = document.createElement("span"); name.textContent = label;
      tile.append(value, name); document.getElementById("metrics").appendChild(tile);
    }
    document.getElementById("coverage").textContent = data.coverage_start
      ? "Coverage: " + new Date(data.coverage_start * 1000).toLocaleString() + " — " + new Date(data.coverage_end * 1000).toLocaleString()
      : "Coverage: no records. All time covers retained records (up to 90 days).";
    for (const group of ["intents", "brands", "sources"]) {
      const container = document.getElementById(group); container.replaceChildren();
      if (!data[group].length) container.textContent = "No activity yet.";
      for (const row of data[group]) {
        const line = document.createElement("div"); line.className = "bar-row";
        const label = document.createElement("span"); label.textContent = row.label.replaceAll("_", " ");
        const count = document.createElement("strong"); count.textContent = row.count;
        line.append(label, count); container.appendChild(line);
      }
    }
  } catch (error) {
    if (version !== requestVersion) return;
    dashboard.hidden = true; auth.hidden = false;
    status.textContent = error.message;
  }
}
auth.addEventListener("submit", e => {
  e.preventDefault(); token = document.getElementById("adminToken").value;
  document.getElementById("adminToken").value = ""; load();
});
document.querySelectorAll("[data-window]").forEach(button => button.addEventListener("click", () => {
  selectedWindow = button.dataset.window;
  document.querySelectorAll("[data-window]").forEach(el => el.setAttribute("aria-pressed", String(el === button)));
  load();
}));
document.getElementById("signOut").addEventListener("click", () => {
  ++requestVersion; token = ""; dashboard.hidden = true; auth.hidden = false;
  document.getElementById("metrics").replaceChildren();
  status.textContent = "Signed out.";
});
