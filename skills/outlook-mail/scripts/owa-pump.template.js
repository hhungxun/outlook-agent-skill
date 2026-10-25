// ==UserScript==
// @name         Outlook Mail — private local session bridge
// @namespace    outlook-mail-local
// @version      0.1.0
// @description  Copies this user's authorised Outlook mail token only to their paired loopback helper. No external service.
// @match        https://outlook.cloud.microsoft/*
// @match        https://outlook.office.com/*
// @match        https://outlook.office365.com/*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @grant        unsafeWindow
// @connect      127.0.0.1
// ==/UserScript==
(function () {
  "use strict";
  const endpoint = __ENDPOINT_JSON__;
  const pairing = __PAIRING_JSON__;
  const page = typeof unsafeWindow === "undefined" ? window : unsafeWindow;
  let lastSuccess = "", pending = "", retryAfter = 0;
  const status = { state: "watching", delivered: 0 };
  // Only non-secret diagnostics are made visible to the page.
  try { page.__outlookMailPump = status; } catch (_) {}

  function observe(auth) {
    if (typeof auth !== "string" || !/^Bearer\s+/i.test(auth)) return;
    const token = auth.replace(/^Bearer\s+/i, "");
    if (token === lastSuccess || token === pending || Date.now() < retryAfter) return;
    try {
      const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      const claims = JSON.parse(atob(part + "=".repeat((4 - part.length % 4) % 4)));
      if (claims.aud !== "https://outlook.office.com" ||
          !String(claims.scp || "").split(/\s+/).includes("Mail.ReadWrite") ||
          claims.exp < Date.now() / 1000 + 60) return;
    } catch (_) { return; }
    pending = token;
    status.state = "delivering";
    function fail() { pending = ""; status.state = "reconnect-helper"; retryAfter = Date.now() + 30000; }
    GM_xmlhttpRequest({
      method: "POST", url: endpoint, data: token,
      headers: { "Content-Type": "text/plain", "X-Outlook-Pairing": pairing },
      timeout: 10000,
      onload: function (response) {
        pending = "";
        if (response.status === 200) {
          lastSuccess = token; status.delivered++; status.state = "connected";
        } else { fail(); }
      },
      onerror: fail, ontimeout: fail
    });
  }
  function headers(value) {
    if (!value) return;
    try {
      if (typeof value.get === "function") observe(value.get("authorization"));
      else if (Array.isArray(value)) {
        for (const item of value) if (String(item[0]).toLowerCase() === "authorization") observe(item[1]);
      } else {
        for (const key of Object.keys(value)) if (key.toLowerCase() === "authorization") observe(value[key]);
      }
    } catch (_) {}
  }
  let installedFetch;
  let installedHeader;
  function hook() {
    if (page.fetch !== installedFetch) {
      const original = page.fetch;
      installedFetch = function (input, init) {
        try { headers(init && init.headers); headers(input && input.headers); } catch (_) {}
        return original.apply(this, arguments);
      };
      page.fetch = installedFetch;
    }
    const proto = page.XMLHttpRequest && page.XMLHttpRequest.prototype;
    if (proto && proto.setRequestHeader !== installedHeader) {
      const original = proto.setRequestHeader;
      installedHeader = function (name, value) {
        if (String(name).toLowerCase() === "authorization") observe(value);
        return original.apply(this, arguments);
      };
      proto.setRequestHeader = installedHeader;
    }
  }
  try { hook(); } catch (_) { status.state = "hook-unavailable"; }
  setInterval(function () { try { hook(); } catch (_) {} }, 5000);
})();
