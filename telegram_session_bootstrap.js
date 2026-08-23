// PRIME Telegram Mini App session bootstrap.
// A stale local JWT must never block Telegram re-authentication.
// Run this BEFORE app.js so its bootstrap sees an empty token and uses
// Telegram initData to create/refresh the account session.
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

  // Navigation must work even while Telegram auth/network is still pending.
  function go(id) {
    if (!id) return;
    const views = document.querySelectorAll(".view");
    views.forEach(v => v.classList.toggle("active", v.id === id));
    document.querySelectorAll(".nav button").forEach(b => b.classList.toggle("active", b.dataset.go === id));
    try { window.scrollTo(0, 0); } catch (_) {}
  }

  function resolveId(target) {
    const button = target?.closest?.("button,[data-go]");
    if (!button) return null;
    return button.dataset.go ||
      (button.id === "goFace" ? "face" :
       button.id === "musicTop" ? "music" :
       button.id === "menu" ? "home" : null);
  }

  function handle(e) {
    const id = resolveId(e.target);
    if (!id) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    go(id);
  }

  document.addEventListener("pointerup", handle, true);
  document.addEventListener("touchend", handle, true);
  document.addEventListener("click", handle, true);
})();

// Deploy trigger: 2026-08-23-touch-fix
