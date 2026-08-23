// PRIME touch/navigation safety layer.
// Must work even when Telegram auth/network bootstrap is slow.
(function () {
  function navigate(id) {
    if (!id) return;
    var views = document.querySelectorAll('.view');
    for (var i = 0; i < views.length; i++) {
      views[i].classList.toggle('active', views[i].id === id);
    }
    var nav = document.querySelectorAll('.nav button');
    for (var j = 0; j < nav.length; j++) {
      nav[j].classList.toggle('active', nav[j].getAttribute('data-go') === id);
    }
    try { window.scrollTo(0, 0); } catch (_) {}
  }

  function idFromTarget(target) {
    var el = target && target.closest ? target.closest('button,[data-go]') : null;
    if (!el) return null;
    var id = el.getAttribute('data-go');
    if (id) return id;
    if (el.id === 'goFace') return 'face';
    if (el.id === 'musicTop') return 'music';
    if (el.id === 'menu') return 'home';
    return null;
  }

  function handle(e) {
    var id = idFromTarget(e.target);
    if (!id) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    navigate(id);
  }

  document.addEventListener('pointerup', handle, true);
  document.addEventListener('touchend', handle, true);
  document.addEventListener('click', handle, true);

  // Make the Telegram WebApp ready immediately; never wait for auth to render UI.
  try {
    var tg = window.Telegram && window.Telegram.WebApp;
    if (tg) { tg.ready(); tg.expand(); }
  } catch (_) {}

  window.__primeTouchFix = true;
})();
