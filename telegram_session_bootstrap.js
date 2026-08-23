// PRIME Telegram Mini App session bootstrap.
// A stale local JWT must never block Telegram re-authentication.
// Run this BEFORE app.js so its bootstrap sees an empty token and uses
// Telegram initData to create/refresh the account session.
//
// NOTE: this file used to also own its own document-level click/pointerup/
// touchend interceptors (capture phase + stopImmediatePropagation) as a
// navigation "fallback". That duplicated app.js's real go() handler, which
// is the only implementation that also loads each tab's data (music,
// leaderboard, advice, face history) -- so whichever handler fired first
// silently swallowed clicks meant for app.js and tabs looked empty/frozen
// even though the view technically switched. Navigation is owned by app.js
// alone now; this file only prepares the Telegram session.
(function () {
  // telegram-web-app.js now loads with `async` (see index.html) so a slow or
  // blocked network fetch of that external script can never again stall our
  // own deferred scripts -- but that also means window.Telegram.WebApp is
  // not guaranteed to exist yet the instant this file runs. Poll briefly
  // instead of checking once.
  const TIMEOUT_MS = 4000, POLL_MS = 50;
  const start = Date.now();
  function tryInit() {
    try {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (!tg) {
        if (Date.now() - start < TIMEOUT_MS) { setTimeout(tryInit, POLL_MS); return; }
        return; // Telegram SDK never became available; app.js's own wait handles the "not in Telegram" case.
      }
      const initData = String(tg.initData || "");
      tg.ready();
      tg.expand();
      if (initData) { try { localStorage.removeItem("prime_token"); } catch (e) {} }
    } catch (error) {
      console.warn("PRIME Telegram session bootstrap failed", error);
    }
  }
  tryInit();
})();
