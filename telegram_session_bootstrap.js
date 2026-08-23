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
  try {
    const tg = window.Telegram && window.Telegram.WebApp;
    const initData = String(tg?.initData || "");
    if (tg) {
      tg.ready();
      tg.expand();
    }
    if (tg && initData) {
      localStorage.removeItem("prime_token");
    }
  } catch (error) {
    console.warn("PRIME Telegram session bootstrap failed", error);
  }
})();
