/* Install with one external script. All chat UI and requests stay on the chat service origin. */
(() => {
  "use strict";
  const script = document.currentScript;
  if (!script || document.getElementById("jack-ingram-chat-widget")) return;
  const base = new URL(script.src).origin;
  const host = document.createElement("div");
  host.id = "jack-ingram-chat-widget";
  const root = host.attachShadow({mode: "open"});
  const style = document.createElement("link");
  style.rel = "stylesheet"; style.href = base + "/static/embed.css";
  const launcher = document.createElement("button");
  launcher.className = "launcher"; launcher.type = "button";
  launcher.textContent = "Chat with Jack Ingram";
  launcher.setAttribute("aria-expanded", "false"); launcher.setAttribute("aria-controls", "ji-panel");
  const panel = document.createElement("section");
  panel.className = "panel"; panel.id = "ji-panel"; panel.hidden = true;
  panel.setAttribute("aria-label", "Jack Ingram chat");
  const bar = document.createElement("div"); bar.className = "bar";
  const label = document.createElement("span"); label.textContent = "How can we help?";
  const close = document.createElement("button"); close.type = "button"; close.textContent = "Close ×";
  close.setAttribute("aria-label", "Close assistant");
  bar.append(label, close); panel.append(bar);
  let frame;
  function toggle(open) {
    panel.hidden = !open; launcher.setAttribute("aria-expanded", String(open));
    if (open && !frame) {
      frame = document.createElement("iframe"); frame.title = "Jack Ingram dealership assistant";
      const url = new URL("/widget", base);
      url.searchParams.set("parent", window.location.origin);
      if (script.dataset.location) url.searchParams.set("location", script.dataset.location);
      frame.src = url.href; frame.referrerPolicy = "no-referrer";
      frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox");
      panel.append(frame);
    }
    if (open) close.focus(); else launcher.focus();
  }
  launcher.addEventListener("click", () => toggle(panel.hidden));
  close.addEventListener("click", () => toggle(false));
  root.addEventListener("keydown", event => { if (event.key === "Escape") toggle(false); });
  window.addEventListener("message", event => {
    if (frame && event.origin === base && event.source === frame.contentWindow &&
        event.data && event.data.type === "jack-ingram-close") toggle(false);
  });
  root.append(style, panel, launcher); document.body.append(host);
})();
