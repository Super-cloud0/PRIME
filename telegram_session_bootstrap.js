// PRIME Telegram Mini App session bootstrap.
// A stale local JWT must never block Telegram re-authentication.
// Run this BEFORE app.js so its bootstrap sees an empty token and uses
// Telegram initData to create/refresh the account session.
(function () {
  try {
    const tg = window.Telegram && window.Telegram.WebApp;
    const initData = String(tg?.initData || "");
    if (tg && initData) {
      localStorage.removeItem("prime_token");
    }
  } catch (error) {
    console.warn("PRIME Telegram session bootstrap failed", error);
  }
})();
