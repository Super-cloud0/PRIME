const tokenKey = "prime_token";
let token = localStorage.getItem(tokenKey) || "";
let tracks = [];
let lastEloImage = null;
const $ = (id) => document.getElementById(id);
function waitForTelegram(timeoutMs = 4000) {
  // telegram-web-app.js loads with `async` now, so it can finish after our
  // own deferred scripts start running. Poll briefly instead of assuming
  // window.Telegram.WebApp already exists -- a slow/blocked fetch of that
  // external script must degrade to "open PRIME from the bot", never hang
  // the whole app or make every button silently do nothing.
  return new Promise(resolve => {
    const start = Date.now();
    (function check() {
      const w = window.Telegram && window.Telegram.WebApp;
      if (w) return resolve(w);
      if (Date.now() - start >= timeoutMs) return resolve(null);
      setTimeout(check, 50);
    })();
  });
}

const withTimeout = (promise, ms = 30000) => Promise.race([
  promise,
  new Promise((_, reject) => setTimeout(() => reject(new Error(`PRIME server did not respond within ${Math.round(ms / 1000)} seconds`)), ms))
]);

const setAuth = (text) => {
  const e = $("authStatus"); if (e) e.textContent = text;
  // #authStatus lives inside #auth, which style.css permanently hides -- so
  // without this, a slow Render cold-start or a failed connection produced
  // zero visible feedback and looked identical to "the site is broken".
  const n = $("netStatus");
  if (n) { n.textContent = text; n.classList.toggle("hidden", !text); }
};
function showAuth() { $("auth")?.classList.remove("hidden"); }
function hideAuth() { $("auth")?.classList.add("hidden"); setAuth(""); }
function toast(text) { const e = $("toast"); if (!e) return; e.textContent = text; e.classList.add("show"); setTimeout(() => e.classList.remove("show"), 1800); }
function escapeHtml(s) { return String(s ?? "").replace(/[&<>"']/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m])); }

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (!headers["X-Requested-With"]) headers["X-Requested-With"] = "PRIME-Mini-App";
  const request = fetch(path, { ...options, headers, cache: "no-store" });
  const response = await withTimeout(request, 30000);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    token = "";
    localStorage.removeItem(tokenKey);
    showAuth();
    throw new Error(data.error || "Сессия истекла. Открываем Telegram-вход…");
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function tierForScore(score) {
  const n = Math.max(1, Math.min(100, Number(score) || 1));
  if (n <= 29) return "SUB 3";
  if (n <= 44) return "SUB 5";
  if (n <= 59) return "LTN";
  if (n <= 74) return "MTN";
  if (n <= 79) return "HTN";
  if (n <= 94) return "CHAD";
  return "TRUE ADAM";
}

async function authenticateTelegram() {
  const tg = await waitForTelegram();
  if (!tg) { showAuth(); setAuth("Telegram WebApp не найден. Открой PRIME через кнопку бота."); return false; }
  try {
    setAuth("Инициализация Telegram…");
    tg.ready();
    tg.expand();
    const initData = String(tg.initData || "");
    if (!initData) throw new Error("Telegram не передал initData. Закрой PRIME и открой заново через кнопку бота.");
    setAuth("Проверяем Telegram…");
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), 30000);
    try {
      const data = await api("/api/auth/telegram", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": initData },
        body: JSON.stringify({ initData }),
        signal: controller.signal
      });
      token = data.token;
      localStorage.setItem(tokenKey, token);
      hideAuth();
      await loadProfile();
      toast(`PRIME готов${data.user?.name ? `, ${data.user.name}` : ""}`);
      return true;
    } finally { clearTimeout(abortTimer); }
  } catch (e) {
    showAuth();
    const message = e?.name === "AbortError" ? "Render не ответил за 30 секунд. Повторяю…" : e.message;
    setAuth(message);
    console.error("PRIME Telegram auth failed", e);
    if (e?.name === "AbortError" || /did not respond|Failed to fetch|NetworkError/i.test(String(e?.message || ""))) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      try {
        setAuth("Повторная попытка подключения…");
        const retry = await api("/api/auth/telegram", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": initData },
          body: JSON.stringify({ initData })
        });
        token = retry.token;
        localStorage.setItem(tokenKey, token);
        hideAuth();
        await loadProfile();
        toast(`PRIME готов${retry.user?.name ? `, ${retry.user.name}` : ""}`);
        return true;
      } catch (retryError) { setAuth(`Ошибка входа: ${retryError.message}`); }
    }
    return false;
  }
}

async function loadProfile() {
  const p = await api("/api/me");
  if ($("primeScore")) $("primeScore").textContent = p.prime_score ?? 0;
  if ($("elo")) $("elo").textContent = p.elo ?? 1200;
  if ($("rankLabel")) $("rankLabel").textContent = tierForScore(p.prime_score);
}

function go(id) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  $(id)?.classList.add("active");
  document.querySelectorAll(".nav button").forEach(b => b.classList.toggle("active", b.dataset.go === id));
  if (id === "advice") loadAdvice();
  if (id === "music") loadMusic();
  if (id === "face") loadHistories();
  if (id === "leaderboard") loadLeaderboard();
}
document.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));
$("goFace")?.addEventListener("click", () => go("face"));
$("musicTop")?.addEventListener("click", () => go("music"));
$("menu")?.addEventListener("click", () => go("home"));

const input = $("photoInput");
const preview = $("preview");
const analyze = $("analyze");
$("pickPhoto")?.addEventListener("click", () => input?.click());
input?.addEventListener("change", e => {
  const file = e.target.files?.[0];
  if (!file) return;
  preview.src = URL.createObjectURL(file);
  preview.classList.remove("hidden");
  if (analyze) analyze.disabled = false;
  toast("Фото готово");
});

async function fileToB64(file) {
  const blob = await new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const max = 1400;
      const scale = Math.min(1, max / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(img.width * scale));
      canvas.height = Math.max(1, Math.round(img.height * scale));
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(b => b ? resolve(b) : reject(new Error("Не удалось подготовить фото")), "image/jpeg", 0.86);
    };
    img.onerror = () => reject(new Error("Не удалось прочитать фото"));
    img.src = URL.createObjectURL(file);
  });
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("Не удалось прочитать фото"));
    reader.readAsDataURL(blob);
  });
}
async function analyzeImage(file) {
  const data = await fileToB64(file);
  lastEloImage = { image: data, mime: "image/jpeg" };
  return api("/api/face-ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(lastEloImage) });
}
analyze?.addEventListener("click", async () => {
  if (!input?.files?.[0]) return toast("Сначала выбери фото");
  analyze.disabled = true;
  if ($("faceStatus")) $("faceStatus").textContent = "AI анализирует фото…";
  try {
    const r = await analyzeImage(input.files[0]);
    if ($("faceScore")) $("faceScore").textContent = r.score;
    if ($("type")) $("type").textContent = r.type || tierForScore(r.score);
    if ($("typeText")) $("typeText").textContent = `${r.summary || "Анализ завершён."}${r.confidence != null ? ` • Confidence: ${r.confidence}/100` : ""}`;
    const labels = { symmetry: "Симметрия", proportion: "Пропорции", grooming: "Уход", hair: "Волосы", skin_appearance: "Внешний вид кожи", presentation: "Презентация" };
    if ($("metrics")) $("metrics").innerHTML = Object.entries(r.metrics || {}).map(([k,v]) => `<div class="metric"><div class="metric-head"><b>${labels[k] || escapeHtml(k)}</b><span>${v}/100</span></div><div class="meter"><i style="width:${Math.max(0, Math.min(100, Number(v)||0))}%"></i></div></div>`).join("");
    if ($("scalePos")) $("scalePos").style.left = `${Math.max(0, Math.min(100, Number(r.score)||0))}%`;
    if ($("tips")) $("tips").innerHTML = (r.tips || []).map(x => `<li>${escapeHtml(x)}</li>`).join("");
    if ($("faceStatus")) $("faceStatus").textContent = "AI анализ завершён.";
    $("faceResult")?.classList.remove("hidden");
    await loadProfile(); await loadHistories();
    toast(`PRIME Score: ${r.score} • ${tierForScore(r.score)}`);
  } catch (e) {
    if ($("faceStatus")) $("faceStatus").textContent = `AI analysis failed: ${e.message}`;
    toast(e.message);
  } finally { analyze.disabled = false; }
});

function ensureEloUI() {
  let box = $("eloBox"); if (box) return box;
  const add = $("addElo"); if (!add) return null;
  box = document.createElement("div"); box.id = "eloBox"; box.className = "card";
  box.innerHTML = `<div class="section-title"><span>⚔ PRIME ELO</span><small>участие добровольное</small></div><p class="muted">Последнее проанализированное фото используется только для ELO-матчей.</p><button id="eloConsent" class="secondary">ВКЛЮЧИТЬ ELO</button><div id="eloStatus" class="status">Проверка…</div><div id="eloArena" class="hidden"><div style="display:flex;align-items:center;gap:10px;justify-content:center"><div style="text-align:center;flex:1"><img id="eloYouPhoto" style="width:100%;max-width:140px;aspect-ratio:1;object-fit:cover;border-radius:18px"><b id="eloYouName" style="display:block">ТЫ</b></div><strong style="font-size:24px">VS</strong><div style="text-align:center;flex:1"><img id="eloOppPhoto" style="width:100%;max-width:140px;aspect-ratio:1;object-fit:cover;border-radius:18px"><b id="eloOppName" style="display:block">?</b></div></div><div id="eloResult" class="status" style="text-align:center;margin-top:14px">Готов</div></div>`;
  add.insertAdjacentElement("beforebegin", box); $("eloConsent")?.addEventListener("click", toggleElo); return box;
}
async function loadEloStatus() {
  try { const s = await api("/api/elo/status"); const box = ensureEloUI(); if (!box) return; $("eloConsent").textContent = s.enabled ? "ВЫКЛЮЧИТЬ ELO" : "ВКЛЮЧИТЬ ELO"; $("eloStatus").textContent = s.enabled ? `ELO включён • ${s.elo} • ${s.games} матчей` : `ELO выключен • ${s.has_photo ? "фото готово" : "сначала нужен анализ фото"}`; } catch (e) { console.warn("ELO status:", e); }
}
async function toggleElo() {
  try { const s = await api("/api/elo/status"); if (!s.enabled) { if (!lastEloImage) throw new Error("Сначала сделай новый анализ фото"); await api("/api/elo/photo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(lastEloImage) }); await api("/api/elo/opt-in", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: true }) }); toast("ELO включён"); } else { await api("/api/elo/opt-in", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: false }) }); toast("ELO выключен"); } await loadEloStatus(); } catch (e) { toast(e.message); }
}
async function runEloMatch() {
  try { let s = await api("/api/elo/status"); if (!s.enabled) { await toggleElo(); s = await api("/api/elo/status"); if (!s.enabled) return; } if (!lastEloImage) throw new Error("Сначала сделай анализ фото"); const arena = $("eloArena"); arena?.classList.remove("hidden"); if ($("eloResult")) $("eloResult").textContent = "🔎 Ищем участника…"; const r = await api("/api/elo/match-v2", { method: "POST" }); if ($("eloYouPhoto")) $("eloYouPhoto").src = `data:image/jpeg;base64,${r.you.photo}`; if ($("eloOppPhoto")) $("eloOppPhoto").src = `data:${r.opponent.mime || "image/jpeg"};base64,${r.opponent.photo}`; if ($("eloYouName")) $("eloYouName").textContent = `${r.you.name} • ${r.you.elo_before}`; if ($("eloOppName")) $("eloOppName").textContent = `${r.opponent.name} • ${r.opponent.elo_before}`; if ($("eloResult")) $("eloResult").textContent = "⚡ СРАВНИВАЕМ…"; arena?.animate?.([{ transform: "scale(.94)", opacity: .4 }, { transform: "scale(1.03)", opacity: 1 }, { transform: "scale(1)", opacity: 1 }], { duration: 850, easing: "ease-out" }); await new Promise(resolve => setTimeout(resolve, 1000)); const won = r.result === "A", tie = r.result === "TIE"; if ($("eloResult")) $("eloResult").textContent = tie ? `🤝 НИЧЬЯ • ELO ${r.you.elo_after}` : won ? `🏆 ПОБЕДА • +${r.you.delta} ELO` : `💥 ПОРАЖЕНИЕ • ${r.you.delta} ELO`; await loadProfile(); await loadHistories(); toast(tie ? "ELO: ничья" : `${won ? "WIN" : "LOSS"} • ELO ${r.you.elo_after}`); } catch (e) { toast(e.message); if ($("eloResult")) $("eloResult").textContent = e.message; }
}
$("addElo")?.addEventListener("click", runEloMatch);
async function loadHistories() {
  try { if ($("faceHistory")) { const rows = await api("/api/face/history"); $("faceHistory").innerHTML = rows.length ? rows.map(x => `<div class="song"><b>${x.score}/100 · ${escapeHtml(x.type || tierForScore(x.score))}</b><small>${new Date(x.created_at).toLocaleString()}</small></div>`).join("") : "<div class='muted'>История пуста.</div>"; } if ($("eloHistory")) { const rows = await api("/api/elo/history"); $("eloHistory").innerHTML = rows.length ? rows.map(x => `<div class="song"><b>${x.delta >= 0 ? "+" : ""}${x.delta} ELO</b><small>vs ${escapeHtml(x.opponent)} · ${new Date(x.created_at).toLocaleString()}</small></div>`).join("") : "<div class='muted'>Матчей пока нет.</div>"; } await loadEloStatus(); } catch (e) { console.warn("history:", e); }
}
async function loadLeaderboard() { try { const rows = await api("/api/leaderboard"); if ($("leaderboardList")) $("leaderboardList").innerHTML = rows.length ? rows.map(x => `<div class="song"><b>#${x.rank} · ${escapeHtml(x.name)}</b><span>${x.elo} ELO · ${x.prime_score}/100 · ${tierForScore(x.prime_score)} · ${x.wins}W/${x.losses}L</span></div>`).join("") : "<div class='muted'>Пока нет игроков.</div>"; } catch (e) { toast(e.message); } }
async function loadMusic() { try { tracks = await api("/api/music"); if ($("songs")) $("songs").innerHTML = tracks.length ? tracks.map(t => `<div class="song"><button data-play="${t.id}">▶</button><b>${escapeHtml(t.name)}</b><button data-del="${t.id}">×</button></div>`).join("") : "<div class='song'>Пока нет треков.</div>"; document.querySelectorAll("[data-play]").forEach(b => b.addEventListener("click", () => playTrack(b.dataset.play))); document.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => { await api(`/api/music/${b.dataset.del}`, { method: "DELETE" }); await loadMusic(); toast("Трек удалён"); })); } catch (e) { toast(e.message); } }
async function playTrack(id) { const t = tracks.find(x => String(x.id) === String(id)); if (!t) return; if ($("audio")) { $("audio").src = t.url; $("nowPlaying").textContent = t.name; await $("audio").play().catch(() => {}); } }
$("addMusic")?.addEventListener("click", () => $("musicInput")?.click());
$("musicInput")?.addEventListener("change", async e => { for (const file of e.target.files || []) { const fd = new FormData(); fd.append("file", file); try { await api("/api/music", { method: "POST", body: fd }); } catch (err) { toast(err.message); } } e.target.value = ""; await loadMusic(); });
async function loadAdvice() { try { const r = await api("/api/advice", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request: "Give concise practical advice" }) }); if ($("adviceList")) $("adviceList").innerHTML = (r.tips || []).map(x => `<div><b>AI</b><span>${escapeHtml(x)}</span></div>`).join("") || "<div><b>AI</b><span>Нет рекомендаций.</span></div>"; } catch (e) { toast(e.message); } }
$("refreshAdvice")?.addEventListener("click", loadAdvice);

(async function bootstrap() {
  setAuth("Подключаемся к серверу… (если он спал, это может занять до минуты)");
  try {
    if (token) { setAuth("Восстанавливаем сессию…"); await withTimeout(loadProfile(), 30000); hideAuth(); await loadEloStatus(); return; }
    await authenticateTelegram();
  } catch (e) { console.error("PRIME bootstrap failed", e); token = ""; localStorage.removeItem(tokenKey); showAuth(); setAuth(`Ошибка загрузки PRIME: ${e.message}`); }
})();

// Defensive CSS only: #auth is already permanently disabled via style.css
// (.auth-overlay{display:none!important}); this is a second, independent
// guarantee in case that rule is ever reverted. It intentionally does NOT
// register its own click handler anymore -- go() above (bound to each
// button individually, further up this file) is the single owner of
// navigation. A second document-level capture-phase listener here used to
// race with it and swallow clicks meant for the real handler, which is why
// tabs could look like they "switched" without ever loading their data.
(function forceInteractiveUI() {
  const css = document.createElement("style");
  css.id = "prime-touch-safety";
  css.textContent = `
    #auth.hidden { display:none !important; pointer-events:none !important; visibility:hidden !important; }
    button, a, input, select, textarea, label { touch-action:manipulation; }
  `;
  (document.head || document.documentElement).appendChild(css);
})();
