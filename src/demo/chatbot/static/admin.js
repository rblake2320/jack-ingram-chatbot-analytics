/* Admin dashboard. Charts are hand-built SVG; every label goes through textContent. */
(function () {
  "use strict";

  const KEY = "jim.admin";
  const SVG = "http://www.w3.org/2000/svg";
  let token = null;
  try { token = sessionStorage.getItem(KEY); } catch (e) { token = null; }

  const $ = function (id) { return document.getElementById(id); };
  const fmt = new Intl.NumberFormat("en-US");
  const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
  const css = function (name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); };

  async function api(path, options) {
    const opts = Object.assign({ headers: {} }, options || {});
    opts.headers = Object.assign({ Authorization: "Bearer " + token }, opts.headers);
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    return { ok: r.ok, status: r.status, data: data || {} };
  }

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(function (kv) { node.setAttribute(kv[0], kv[1]); });
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function svg(tag, attrs) {
    const node = document.createElementNS(SVG, tag);
    Object.entries(attrs || {}).forEach(function (kv) { node.setAttribute(kv[0], kv[1]); });
    return node;
  }
  function pct(value) { return value === null || value === undefined ? "–" : (value * 100).toFixed(1) + "%"; }
  function ms(value) { return value === null || value === undefined ? "–" : fmt.format(Math.round(value)) + " ms"; }
  // Integer-friendly scale for counts: 4 intervals on a 1/2/5 x 10^k step (0/10/20/30/40, never 12.5).
  function niceScale(v) {
    const raw = Math.max(v, 1) / 4;
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const n = raw / p;
    const step = Math.max(1, (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p);
    return { step: step, max: step * Math.max(1, Math.ceil(v / step)) };
  }

  // ---------- tooltip ----------
  function tooltip(container) {
    let tip = container.querySelector(".tooltip");
    if (!tip) { tip = el("div", { class: "tooltip hidden", role: "status" }); container.appendChild(tip); }
    return {
      show: function (x, y, head, rows) {
        tip.textContent = "";
        tip.appendChild(el("div", { class: "t-head" }, head));
        rows.forEach(function (row) {
          const line = el("div", { class: "t-row" });
          if (row.color) { const k = el("span", { class: "t-key" }); k.style.background = row.color; line.appendChild(k); }
          line.appendChild(el("strong", {}, row.value));
          line.appendChild(el("span", { class: "muted" }, row.label));
          tip.appendChild(line);
        });
        tip.classList.remove("hidden");
        const maxX = container.clientWidth - tip.offsetWidth - 4;
        tip.style.left = Math.max(0, Math.min(x + 12, maxX)) + "px";
        tip.style.top = Math.max(0, y - 10) + "px";
      },
      hide: function () { tip.classList.add("hidden"); },
    };
  }

  // ---------- line chart (one axis, <=3 series, crosshair) ----------
  function lineChart(container, rows, series) {
    container.textContent = "";
    const W = Math.max(container.clientWidth || 640, 320), H = 240;
    const m = { l: 40, r: 120, t: 12, b: 28 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const scale = niceScale(Math.max(1, ...rows.flatMap(function (r) { return series.map(function (s) { return r[s.key]; }); })));
    const max = scale.max;
    const x = function (i) { return m.l + (rows.length <= 1 ? iw / 2 : (i * iw) / (rows.length - 1)); };
    const y = function (v) { return m.t + ih - (v / max) * ih; };
    const root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Daily activity line chart" });
    for (let v = 0; v <= max + 1e-9; v += scale.step) {
      root.appendChild(svg("line", { x1: m.l, x2: m.l + iw, y1: y(v), y2: y(v), stroke: css("--grid"), "stroke-width": 1 }));
      const t = svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end", "font-size": 11, fill: css("--text-muted") });
      t.textContent = v >= 10000 ? compact.format(v) : fmt.format(v);
      root.appendChild(t);
    }
    [0, Math.floor((rows.length - 1) / 2), rows.length - 1].forEach(function (i) {
      if (!rows[i]) return;
      const t = svg("text", { x: x(i), y: H - 8, "text-anchor": "middle", "font-size": 11, fill: css("--text-muted") });
      t.textContent = rows[i].date.slice(5);
      root.appendChild(t);
    });
    const ends = [];
    series.forEach(function (s) {
      const d = rows.map(function (r, i) { return (i ? "L" : "M") + x(i).toFixed(1) + "," + y(r[s.key]).toFixed(1); }).join("");
      root.appendChild(svg("path", { d: d, fill: "none", stroke: css(s.color), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      const last = rows[rows.length - 1];
      if (last) {
        root.appendChild(svg("circle", { cx: x(rows.length - 1), cy: y(last[s.key]), r: 4, fill: css(s.color), stroke: css("--surface-1"), "stroke-width": 2 }));
        ends.push({ y: y(last[s.key]), text: s.label + " " + fmt.format(last[s.key]) });
      }
    });
    ends.sort(function (a, b) { return a.y - b.y; });
    const collide = ends.some(function (e, i) { return i > 0 && e.y - ends[i - 1].y < 14; });
    if (!collide) {  // label endpoints only when they separate; otherwise legend + tooltip carry identity
      ends.forEach(function (e) {
        const t = svg("text", { x: m.l + iw + 10, y: e.y + 4, "font-size": 12, fill: css("--text-secondary") });
        t.textContent = e.text;
        root.appendChild(t);
      });
    }
    const cross = svg("line", { y1: m.t, y2: m.t + ih, stroke: css("--axis"), "stroke-width": 1, visibility: "hidden" });
    root.appendChild(cross);
    const overlay = svg("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent", tabindex: 0,
      "aria-label": "Use arrow keys to read daily values" });
    root.appendChild(overlay);
    container.appendChild(root);
    const tip = tooltip(container);
    let index = rows.length - 1;
    function show(i) {
      index = Math.max(0, Math.min(rows.length - 1, i));
      const row = rows[index];
      cross.setAttribute("x1", x(index)); cross.setAttribute("x2", x(index)); cross.setAttribute("visibility", "visible");
      const scale = container.clientWidth / W;
      tip.show(x(index) * scale, m.t * scale, row.date, series.map(function (s) {
        return { color: css(s.color), value: fmt.format(row[s.key]), label: s.label };
      }));
    }
    overlay.addEventListener("pointermove", function (e) {
      const box = root.getBoundingClientRect();
      const px = ((e.clientX - box.left) / box.width) * W;
      show(Math.round(((px - m.l) / iw) * (rows.length - 1)));
    });
    overlay.addEventListener("pointerleave", function () { cross.setAttribute("visibility", "hidden"); tip.hide(); });
    overlay.addEventListener("focus", function () { show(index); });
    overlay.addEventListener("blur", function () { cross.setAttribute("visibility", "hidden"); tip.hide(); });
    overlay.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { e.preventDefault(); show(index - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); show(index + 1); }
    });
  }

  // ---------- horizontal bars (single series) ----------
  function barChart(container, entries, unit) {
    container.textContent = "";
    if (!entries.length) { container.appendChild(el("p", { class: "muted small" }, "No data in this range.")); return; }
    const W = Math.max(container.clientWidth || 420, 280), row = 28, bar = 16;
    const H = entries.length * row + 8, labelW = 120, valueW = 48;
    const iw = W - labelW - valueW;
    const max = Math.max(...entries.map(function (e) { return e[1]; }), 1);
    const root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Bar chart" });
    root.appendChild(svg("line", { x1: labelW, x2: labelW, y1: 0, y2: H, stroke: css("--axis"), "stroke-width": 1 }));
    const tip = tooltip(container);
    entries.forEach(function (entry, i) {
      const y0 = i * row + (row - bar) / 2 + 4;
      const w = Math.max(2, (entry[1] / max) * iw);
      const label = svg("text", { x: labelW - 8, y: y0 + bar / 2 + 4, "text-anchor": "end", "font-size": 12, fill: css("--text-secondary") });
      label.textContent = entry[0].replace(/_/g, " ");
      root.appendChild(label);
      const r = Math.min(4, w / 2), x0 = labelW + 1, x1 = labelW + 1 + w;
      const d = "M" + x0 + "," + y0 + "H" + (x1 - r) + "Q" + x1 + "," + y0 + " " + x1 + "," + (y0 + r) + "V" + (y0 + bar - r) +
        "Q" + x1 + "," + (y0 + bar) + " " + (x1 - r) + "," + (y0 + bar) + "H" + x0 + "Z";
      const path = svg("path", { d: d, fill: css("--series-1"), tabindex: 0 });
      const hit = svg("rect", { x: labelW, y: i * row + 4, width: iw + valueW, height: row, fill: "transparent" });
      const value = svg("text", { x: x1 + 6, y: y0 + bar / 2 + 4, "font-size": 12, fill: css("--text-primary") });
      value.textContent = fmt.format(entry[1]);
      root.appendChild(path); root.appendChild(value); root.appendChild(hit);
      const show = function () {
        const scale = container.clientWidth / W;
        path.setAttribute("opacity", "0.8");
        tip.show(x1 * scale, y0 * scale, entry[0].replace(/_/g, " "), [{ value: fmt.format(entry[1]), label: unit }]);
      };
      const hide = function () { path.removeAttribute("opacity"); tip.hide(); };
      hit.addEventListener("pointermove", show); hit.addEventListener("pointerleave", hide);
      path.addEventListener("focus", show); path.addEventListener("blur", hide);
    });
    container.appendChild(root);
  }

  // ---------- heatmap (sequential single hue) ----------
  function heatmap(container, data) {
    container.textContent = "";
    const W = Math.max(container.clientWidth || 420, 300), left = 34, top = 14, gap = 2;
    const cw = (W - left) / 24, ch = 18, H = top + 7 * ch + 34;
    const flat = data.values.flat(), max = Math.max(...flat, 0);
    const steps = ["--seq-0", "--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5", "--seq-6"];
    const root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Messages by weekday and hour" });
    const tip = tooltip(container);
    [0, 6, 12, 18, 23].forEach(function (h) {
      const t = svg("text", { x: left + h * cw + cw / 2, y: 10, "text-anchor": "middle", "font-size": 10, fill: css("--text-muted") });
      t.textContent = String(h).padStart(2, "0");
      root.appendChild(t);
    });
    data.values.forEach(function (rowVals, r) {
      const lbl = svg("text", { x: left - 6, y: top + r * ch + ch / 2 + 3, "text-anchor": "end", "font-size": 10, fill: css("--text-muted") });
      lbl.textContent = data.rows[r];
      root.appendChild(lbl);
      rowVals.forEach(function (v, h) {
        const step = v === 0 || max === 0 ? 0 : 1 + Math.min(5, Math.floor((v / max) * 5.999));
        const cell = svg("rect", { x: left + h * cw + gap / 2, y: top + r * ch + gap / 2, width: cw - gap, height: ch - gap, rx: 2,
          fill: css(steps[step]), tabindex: -1 });
        const show = function () {
          const scale = container.clientWidth / W;
          cell.setAttribute("stroke", css("--text-primary"));
          tip.show((left + h * cw) * scale, (top + r * ch) * scale, data.rows[r] + " " + String(h).padStart(2, "0") + ":00",
            [{ value: fmt.format(v), label: "messages" }]);
        };
        const hide = function () { cell.removeAttribute("stroke"); tip.hide(); };
        cell.addEventListener("pointermove", show); cell.addEventListener("pointerleave", hide);
        root.appendChild(cell);
      });
    });
    const ly = top + 7 * ch + 14;
    const fewer = svg("text", { x: left, y: ly + 9, "font-size": 10, fill: css("--text-muted") }); fewer.textContent = "Fewer";
    root.appendChild(fewer);
    steps.forEach(function (s, i) { root.appendChild(svg("rect", { x: left + 40 + i * 16, y: ly, width: 14, height: 10, rx: 2, fill: css(s) })); });
    const more = svg("text", { x: left + 40 + steps.length * 16 + 4, y: ly + 9, "font-size": 10, fill: css("--text-muted") }); more.textContent = "More";
    root.appendChild(more);
    container.appendChild(root);
  }

  function table(target, headers, rows, numeric) {
    target.textContent = "";
    const head = el("tr");
    headers.forEach(function (h, i) { head.appendChild(el("th", numeric && numeric[i] ? { class: "num" } : {}, h)); });
    target.appendChild(head);
    rows.forEach(function (r) {
      const tr = el("tr");
      r.forEach(function (cell, i) { tr.appendChild(el("td", numeric && numeric[i] ? { class: "num" } : {}, cell)); });
      target.appendChild(tr);
    });
    if (!rows.length) { const tr = el("tr"); tr.appendChild(el("td", { colspan: headers.length, class: "muted" }, "No data")); target.appendChild(tr); }
  }

  function tiles(s) {
    const box = $("tiles");
    box.textContent = "";
    [
      ["Messages", compact.format(s.totals.messages)],
      ["Leads", fmt.format(s.totals.leads)],
      ["Appointments", fmt.format(s.totals.appointments)],
      ["Chat-to-lead rate", pct(s.conversion.lead_rate)],
      ["Handoff rate", pct(s.conversion.handoff_rate)],
      ["Satisfaction", s.satisfaction.rate === null ? "–" : pct(s.satisfaction.rate)],
      ["Response p50", ms(s.latency_ms.p50)],
      ["Response p95", ms(s.latency_ms.p95)],
      ["Model refusals", fmt.format(s.refusals)],
      ["Rate-limited", fmt.format(s.totals.rate_limited)],
    ].forEach(function (t) {
      const tile = el("div", { class: "card tile" });
      tile.appendChild(el("div", { class: "label" }, t[0]));
      tile.appendChild(el("div", { class: "value" }, t[1]));
      box.appendChild(tile);
    });
  }

  const SERIES = [
    { key: "conversations", label: "Conversations", color: "--series-1" },
    { key: "leads", label: "Leads", color: "--series-2" },
    { key: "appointments", label: "Appointments", color: "--series-3" },
  ];

  let lastSummary = null;
  function render(s) {
    lastSummary = s;
    $("hero-value").textContent = fmt.format(s.totals.conversations);
    $("generated").textContent = "Updated " + new Date(s.generated_at).toLocaleString();
    tiles(s);
    const legend = $("daily-legend");
    legend.textContent = "";
    SERIES.forEach(function (ser) {
      const item = el("span");
      const key = el("span", { class: "key" });
      key.style.background = css(ser.color);
      item.appendChild(key);
      item.appendChild(document.createTextNode(ser.label));
      legend.appendChild(item);
    });
    lineChart($("daily-chart"), s.daily, SERIES);
    table($("daily-table"), ["Date", "Conversations", "Messages", "Leads", "Appointments"],
      s.daily.map(function (d) { return [d.date, d.conversations, d.messages, d.leads, d.appointments]; }), [false, true, true, true, true]);
    barChart($("topics-chart"), Object.entries(s.topics).slice(0, 10), "messages");
    heatmap($("heatmap"), s.heatmap);
    table($("tools-table"), ["Tool", "Calls", "Errors"],
      Object.entries(s.tools).map(function (kv) { return [kv[0].replace(/_/g, " "), kv[1].calls, kv[1].errors]; }), [false, true, true]);
    const integrations = Object.entries(s.integrations || {}).map(function (kv) { return ["Integration: " + kv[0], kv[1] ? "configured" : "off"]; });
    table($("health-table"), ["Check", "Status"], [
      ["Response sources", Object.entries(s.response_sources).map(function (kv) { return kv[0] + " " + kv[1]; }).join(", ") || "–"],
      ["Model fallbacks", fmt.format(s.model_fallbacks)],
      ["Tokens in / out", compact.format(s.tokens.input) + " / " + compact.format(s.tokens.output)],
      ["CRM outbox", Object.entries(s.outbox).map(function (kv) { return kv[0] + " " + kv[1]; }).join(", ") || "empty"],
      ["Inventory", (s.inventory ? s.inventory.vehicles : 0) + " vehicles" + (s.inventory && s.inventory.is_sample ? " (sample feed)" : "")],
    ].concat(integrations));
  }

  async function loadLeads() {
    const r = await api("/api/admin/leads?limit=20");
    if (!r.ok) return;
    table($("leads-table"), ["Created", "Name", "Phone", "Email", "Interest", "Source"],
      (r.data.leads || []).map(function (l) {
        return [new Date(l.created_at).toLocaleString(), [l.first_name, l.last_name].filter(Boolean).join(" "), l.phone || "", l.email || "", l.interest, l.source];
      }));
  }

  async function refresh() {
    const dash = $("dashboard");
    dash.style.opacity = "0.6";  // refetch keeps the frame
    const r = await api("/api/admin/analytics/summary?days=" + $("range").value);
    dash.style.opacity = "";
    if (r.status === 401 || r.status === 503) {
      $("auth-error").textContent = r.status === 503 ? "Admin access is disabled (set ADMIN_TOKEN)." : "Invalid token.";
      dash.classList.add("hidden");
      return;
    }
    if (!r.ok) { $("auth-error").textContent = "Could not load analytics."; return; }
    $("auth-error").textContent = "";
    dash.classList.remove("hidden");
    render(r.data);
    loadLeads();
  }

  $("auth-form").addEventListener("submit", function (e) {
    e.preventDefault();
    token = $("token").value.trim();
    try { sessionStorage.setItem(KEY, token); } catch (err) { /* memory only */ }
    refresh();
  });
  $("range").addEventListener("change", refresh);
  $("refresh").addEventListener("click", refresh);
  $("verify-ledger").addEventListener("click", async function () {
    const r = await api("/api/admin/ledger/verify");
    const out = $("verify-result");
    out.className = "small " + (r.ok && r.data.ok ? "status-ok" : "status-bad");
    out.textContent = r.ok ? (r.data.ok ? "Ledger intact: " + r.data.entries + " entries, head " + r.data.head_hash.slice(0, 16) + "…"
      : "Ledger FAILED verification at seq " + r.data.failures.map(function (f) { return f.seq; }).join(", ")) : "Verification request failed.";
  });
  $("verify-records").addEventListener("click", async function () {
    const r = await api("/api/admin/records/verify");
    const out = $("verify-result");
    out.className = "small " + (r.ok && r.data.ok ? "status-ok" : "status-bad");
    out.textContent = r.ok ? (r.data.ok ? "All " + r.data.checked + " lead/appointment rows match their ledger digests."
      : r.data.mismatches.length + " row(s) do not match the ledger.") : "Verification request failed.";
  });
  $("leads-csv").addEventListener("click", async function (e) {
    e.preventDefault();
    const r = await fetch("/api/admin/leads.csv", { headers: { Authorization: "Bearer " + token } });
    if (!r.ok) return;
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "leads.csv";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  });
  let resizeTimer = null;  // re-layout from cached data; never refetch on resize
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (lastSummary) render(lastSummary); }, 200);
  });
  if (token) { $("token").value = token; refresh(); }
})();
