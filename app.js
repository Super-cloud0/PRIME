const tokenKey = "prime_token";
// Wrapped defensively: some WebView configurations (older Android builds,
// certain privacy/storage-partitioning modes) throw a SecurityError just
// *accessing* localStorage. An uncaught throw on this very first line used
// to kill this entire script before a single button handler further down
// got registered -- HTML/CSS still rendered fine (that's the browser, not
// this file), so the page looked "loaded" while being completely dead.
function safeStorageGet(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
function safeStorageSet(key, value) { try { localStorage.setItem(key, value); } catch (e) {} }
function safeStorageRemove(key) { try { localStorage.removeItem(key); } catch (e) {} }
const t = (...args) => (window.PrimeI18N ? window.PrimeI18N.t(...args) : args[0]);
let token = safeStorageGet(tokenKey) || "";
let tracks = [];
let lastEloImage = null;
const $ = (id) => document.getElementById(id);
try {
  document.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));
  $("goFace")?.addEventListener("click", () => go("face"));
  $("musicTop")?.addEventListener("click", () => go("music"));
  $("menu")?.addEventListener("click", () => go("home"));
} catch (e) { console.error("PRIME nav wiring failed", e); }

function waitForTelegram(timeoutMs = 4000) {
  // telegram-web-app.js loads with `async` in <head>, so window.Telegram.WebApp
  // is not guaranteed to exist yet the instant this runs -- poll with a short
  // timeout rather than a single synchronous read. A failure here must degrade
  // to "open PRIME from the bot", never hang the whole app or make every
  // button silently do nothing.
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
    safeStorageRemove(tokenKey);
    showAuth();
    throw new Error(data.error || t("auth_session_expired"));
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
  if (!tg) { showAuth(); setAuth(t("auth_not_found")); return false; }
  // Now that Telegram actually answered, refine the interface language from
  // the user's own Telegram language_code (unless they already picked one
  // manually via the header toggle).
  window.PrimeI18N?.refineFromTelegram(tg.initDataUnsafe?.user?.language_code);
  try {
    setAuth(t("auth_init"));
    tg.ready();
    tg.expand();
    const initData = String(tg.initData || "");
    if (!initData) throw new Error(t("auth_no_initdata"));
    setAuth(t("auth_checking"));
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
      safeStorageSet(tokenKey, token);
      hideAuth();
      await loadProfile();
      toast(t("auth_ready", data.user?.name));
      return true;
    } finally { clearTimeout(abortTimer); }
  } catch (e) {
    showAuth();
    const message = e?.name === "AbortError" ? t("auth_render_timeout") : e.message;
    setAuth(message);
    console.error("PRIME Telegram auth failed", e);
    if (e?.name === "AbortError" || /did not respond|Failed to fetch|NetworkError/i.test(String(e?.message || ""))) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      try {
        setAuth(t("auth_retrying"));
        const retry = await api("/api/auth/telegram", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": initData },
          body: JSON.stringify({ initData })
        });
        token = retry.token;
        safeStorageSet(tokenKey, token);
        hideAuth();
        await loadProfile();
        toast(t("auth_ready", retry.user?.name));
        return true;
      } catch (retryError) { setAuth(t("auth_login_error", retryError.message)); }
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
  if (id === "pro") loadProStatus();
}
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
  toast(t("toast_photo_ready"));
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
      canvas.toBlob(b => b ? resolve(b) : reject(new Error(t("err_prepare_photo"))), "image/jpeg", 0.86);
    };
    img.onerror = () => reject(new Error(t("err_read_photo")));
    img.src = URL.createObjectURL(file);
  });
  return await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error(t("err_read_photo")));
    reader.readAsDataURL(blob);
  });
}
async function analyzeImage(file) {
  const data = await fileToB64(file);
  lastEloImage = { image: data, mime: "image/jpeg" };
  return api("/api/face-ai", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(lastEloImage) });
}
analyze?.addEventListener("click", async () => {
  if (!input?.files?.[0]) return toast(t("toast_pick_photo_first"));
  analyze.disabled = true;
  if ($("faceStatus")) $("faceStatus").textContent = t("status_analyzing");
  try {
    const r = await analyzeImage(input.files[0]);
    if ($("faceScore")) $("faceScore").textContent = r.score;
    if ($("type")) $("type").textContent = r.type || tierForScore(r.score);
    if ($("typeText")) $("typeText").textContent = `${r.summary || t("analysis_default_summary")}${r.confidence != null ? ` • Confidence: ${r.confidence}/100` : ""}`;
    const labels = { symmetry: t("metric_symmetry"), proportion: t("metric_proportion"), grooming: t("metric_grooming"), hair: t("metric_hair"), skin_appearance: t("metric_skin_appearance"), presentation: t("metric_presentation") };
    if ($("metrics")) $("metrics").innerHTML = Object.entries(r.metrics || {}).map(([k,v]) => `<div class="metric"><div class="metric-head"><b>${labels[k] || escapeHtml(k)}</b><span>${v}/100</span></div><div class="meter"><i style="width:${Math.max(0, Math.min(100, Number(v)||0))}%"></i></div></div>`).join("");
    if ($("scalePos")) $("scalePos").style.left = `${Math.max(0, Math.min(100, Number(r.score)||0))}%`;
    if ($("tips")) $("tips").innerHTML = (r.tips || []).map(x => `<li>${escapeHtml(x)}</li>`).join("");
    if ($("faceStatus")) $("faceStatus").textContent = t("status_analysis_done");
    // Tell share.js everything it needs to build the downloadable player-card
    // image (score/tier/metrics + the photo itself) -- the DOM text alone
    // doesn't carry the per-metric numbers or the photo, so this event is
    // the single source of truth for that card. Dispatched before the
    // classList change below so share.js's data is ready by the time its
    // MutationObserver reacts to #faceResult becoming visible.
    document.dispatchEvent(new CustomEvent("prime:analysisResult", {
      detail: { score: r.score, tier: r.type || tierForScore(r.score), metrics: r.metrics || {}, photo: preview?.src || null }
    }));
    $("faceResult")?.classList.remove("hidden");
    await loadProfile(); await loadHistories();
    toast(t("toast_score", r.score, tierForScore(r.score)));
  } catch (e) {
    if ($("faceStatus")) $("faceStatus").textContent = t("status_analysis_failed", e.message);
    toast(e.message);
  } finally { analyze.disabled = false; }
});

const compareInputA = $("compareInputA");
const compareInputB = $("compareInputB");
const previewCompareA = $("previewCompareA");
const previewCompareB = $("previewCompareB");
const runCompareBtn = $("runCompare");
let compareFileA = null, compareFileB = null;

$("pickCompareA")?.addEventListener("click", () => compareInputA?.click());
$("pickCompareB")?.addEventListener("click", () => compareInputB?.click());

function handleCompareFile(slot, file) {
  if (!file) return;
  const url = URL.createObjectURL(file);
  if (slot === "a") {
    compareFileA = file;
    if (previewCompareA) { previewCompareA.src = url; previewCompareA.classList.remove("hidden"); }
  } else {
    compareFileB = file;
    if (previewCompareB) { previewCompareB.src = url; previewCompareB.classList.remove("hidden"); }
  }
  if (runCompareBtn) runCompareBtn.disabled = !(compareFileA && compareFileB);
  if ($("compareStatus")) $("compareStatus").textContent = (compareFileA && compareFileB) ? t("compare_status_both_ready") : t("compare_status_ready");
}
compareInputA?.addEventListener("change", e => handleCompareFile("a", e.target.files?.[0]));
compareInputB?.addEventListener("change", e => handleCompareFile("b", e.target.files?.[0]));

async function runCompare() {
  if (!compareFileA || !compareFileB) return toast(t("compare_error_need_both"));
  runCompareBtn.disabled = true;
  if ($("compareStatus")) $("compareStatus").textContent = t("compare_status_comparing");
  try {
    const [dataA, dataB] = await Promise.all([fileToB64(compareFileA), fileToB64(compareFileB)]);
    const r = await api("/api/face/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a: { image: dataA, mime: "image/jpeg" }, b: { image: dataB, mime: "image/jpeg" } })
    });
    if (r.pro_locked) {
      if ($("compareStatus")) $("compareStatus").textContent = t("compare_locked_status", r.limit);
      toast(t("compare_locked_toast"));
      return;
    }
    if ($("compareResultPhotoA") && previewCompareA) $("compareResultPhotoA").src = previewCompareA.src;
    if ($("compareResultPhotoB") && previewCompareB) $("compareResultPhotoB").src = previewCompareB.src;
    if ($("compareScoreA")) $("compareScoreA").textContent = r.a.score;
    if ($("compareScoreB")) $("compareScoreB").textContent = r.b.score;
    if ($("compareTierA")) $("compareTierA").textContent = r.a.tier;
    if ($("compareTierB")) $("compareTierB").textContent = r.b.tier;
    $("compareCardA")?.classList.toggle("winner", r.winner === "a");
    $("compareCardB")?.classList.toggle("winner", r.winner === "b");
    $("compareBadgeA")?.classList.toggle("hidden", r.winner !== "a");
    $("compareBadgeB")?.classList.toggle("hidden", r.winner !== "b");
    if ($("compareStatus")) $("compareStatus").textContent = r.winner === "tie" ? t("compare_tie_label") : t("compare_status_done");
    $("compareResult")?.classList.remove("hidden");
  } catch (e) {
    if ($("compareStatus")) $("compareStatus").textContent = e.message;
    toast(e.message);
  } finally {
    runCompareBtn.disabled = false;
  }
}
$("runCompare")?.addEventListener("click", runCompare);
$("resetCompare")?.addEventListener("click", () => {
  compareFileA = null; compareFileB = null;
  if (compareInputA) compareInputA.value = "";
  if (compareInputB) compareInputB.value = "";
  previewCompareA?.classList.add("hidden");
  previewCompareB?.classList.add("hidden");
  $("compareResult")?.classList.add("hidden");
  $("compareCardA")?.classList.remove("winner");
  $("compareCardB")?.classList.remove("winner");
  if (runCompareBtn) runCompareBtn.disabled = true;
  if ($("compareStatus")) $("compareStatus").textContent = t("compare_status_ready");
});

function ensureEloUI() {
  let box = $("eloBox"); if (box) return box;
  const add = $("addElo"); if (!add) return null;
  box = document.createElement("div"); box.id = "eloBox"; box.className = "card";
  box.innerHTML = `<div class="section-title"><span>${escapeHtml(t("elo_title"))}</span><small>${escapeHtml(t("elo_voluntary"))}</small></div><p class="muted">${escapeHtml(t("elo_hint"))}</p><button id="eloConsent" class="secondary">${escapeHtml(t("elo_enable"))}</button><div id="eloStatus" class="status">${escapeHtml(t("elo_checking"))}</div><div id="eloArena" class="hidden"><div style="display:flex;align-items:center;gap:10px;justify-content:center"><div style="text-align:center;flex:1"><img id="eloYouPhoto" style="width:100%;max-width:140px;aspect-ratio:1;object-fit:cover;border-radius:18px"><b id="eloYouName" style="display:block">${escapeHtml(t("elo_you"))}</b></div><strong style="font-size:24px">VS</strong><div style="text-align:center;flex:1"><img id="eloOppPhoto" style="width:100%;max-width:140px;aspect-ratio:1;object-fit:cover;border-radius:18px"><b id="eloOppName" style="display:block">?</b></div></div><div id="eloResult" class="status" style="text-align:center;margin-top:14px">${escapeHtml(t("elo_ready"))}</div></div>`;
  add.insertAdjacentElement("beforebegin", box); $("eloConsent")?.addEventListener("click", toggleElo); return box;
}
async function loadEloStatus() {
  try { const s = await api("/api/elo/status"); const box = ensureEloUI(); if (!box) return; $("eloConsent").textContent = s.enabled ? t("elo_disable") : t("elo_enable"); $("eloStatus").textContent = s.enabled ? t("elo_enabled_status", s.elo, s.games) : (s.has_photo ? t("elo_disabled_status_photo_ready") : t("elo_disabled_status_needs_photo")); } catch (e) { console.warn("ELO status:", e); }
}
async function toggleElo() {
  try { const s = await api("/api/elo/status"); if (!s.enabled) { if (!lastEloImage) throw new Error(t("err_need_new_analysis")); await api("/api/elo/photo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(lastEloImage) }); await api("/api/elo/opt-in", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: true }) }); toast(t("toast_elo_enabled")); } else { await api("/api/elo/opt-in", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: false }) }); toast(t("toast_elo_disabled")); } await loadEloStatus(); } catch (e) { toast(e.message); }
}
async function runEloMatch() {
  try { let s = await api("/api/elo/status"); if (!s.enabled) { await toggleElo(); s = await api("/api/elo/status"); if (!s.enabled) return; } if (!lastEloImage) throw new Error(t("err_need_analysis")); const arena = $("eloArena"); arena?.classList.remove("hidden"); if ($("eloResult")) $("eloResult").textContent = t("elo_searching"); const r = await api("/api/elo/match-v2", { method: "POST" }); if ($("eloYouPhoto")) $("eloYouPhoto").src = `data:image/jpeg;base64,${r.you.photo}`; if ($("eloOppPhoto")) $("eloOppPhoto").src = `data:${r.opponent.mime || "image/jpeg"};base64,${r.opponent.photo}`; if ($("eloYouName")) $("eloYouName").textContent = `${r.you.name} • ${r.you.elo_before}`; if ($("eloOppName")) $("eloOppName").textContent = `${r.opponent.name} • ${r.opponent.elo_before}`; if ($("eloResult")) $("eloResult").textContent = t("elo_comparing"); arena?.animate?.([{ transform: "scale(.94)", opacity: .4 }, { transform: "scale(1.03)", opacity: 1 }, { transform: "scale(1)", opacity: 1 }], { duration: 850, easing: "ease-out" }); await new Promise(resolve => setTimeout(resolve, 1000)); const won = r.result === "A", tie = r.result === "TIE"; if ($("eloResult")) $("eloResult").textContent = tie ? t("elo_tie", r.you.elo_after) : won ? t("elo_win", r.you.delta) : t("elo_loss", r.you.delta); await loadProfile(); await loadHistories(); toast(tie ? t("toast_elo_tie") : `${won ? "WIN" : "LOSS"} • ELO ${r.you.elo_after}`); } catch (e) { toast(e.message); if ($("eloResult")) $("eloResult").textContent = e.message; }
}
$("addElo")?.addEventListener("click", runEloMatch);
// ISO-8601 week key ("2026-W07") so multiple check-ins in the same week
// collapse to one point on the progress timeline/chart instead of making
// the trend look noisier than it is -- the feature is "score once a week",
// not "score every time you happen to open the tab".
function isoWeekKey(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = (d.getUTCDay() + 6) % 7;
  d.setUTCDate(d.getUTCDate() - dayNum + 3);
  const firstThursday = new Date(Date.UTC(d.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round(((d - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
  return `${d.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

function drawProgressChart(scores) {
  const canvas = $("progressChart");
  if (!canvas || scores.length < 2) return;
  const cssWidth = canvas.parentElement?.clientWidth || 300;
  const cssHeight = 90;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = cssWidth * dpr; canvas.height = cssHeight * dpr;
  canvas.style.width = `${cssWidth}px`; canvas.style.height = `${cssHeight}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const pad = 14;
  const min = Math.min(...scores), max = Math.max(...scores);
  const range = Math.max(1, max - min);
  const stepX = scores.length > 1 ? (cssWidth - pad * 2) / (scores.length - 1) : 0;
  const points = scores.map((s, i) => ({ x: pad + i * stepX, y: pad + (1 - (s - min) / range) * (cssHeight - pad * 2) }));
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  const grad = ctx.createLinearGradient(0, 0, 0, cssHeight);
  grad.addColorStop(0, "rgba(255,56,62,0.35)"); grad.addColorStop(1, "rgba(255,56,62,0)");
  ctx.beginPath(); ctx.moveTo(points[0].x, cssHeight - pad);
  points.forEach(p => ctx.lineTo(p.x, p.y));
  ctx.lineTo(points[points.length - 1].x, cssHeight - pad); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();
  ctx.beginPath();
  points.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
  ctx.strokeStyle = "#ff383e"; ctx.lineWidth = 2.5; ctx.lineJoin = "round"; ctx.stroke();
  points.forEach((p, i) => {
    ctx.beginPath(); ctx.arc(p.x, p.y, i === points.length - 1 ? 5 : 3, 0, Math.PI * 2);
    ctx.fillStyle = i === points.length - 1 ? "#ff383e" : "#fff"; ctx.fill();
  });
}

// `rows` is newest-first, straight from /api/face/history.
function renderProgress(rows) {
  const wrap = $("progressBody");
  if (!wrap) return;
  if (!rows.length) { wrap.innerHTML = `<div class="status">${escapeHtml(t("progress_empty"))}</div>`; return; }
  const chrono = [...rows].reverse(); // oldest -> newest
  const weekMap = new Map();
  chrono.forEach(row => weekMap.set(isoWeekKey(new Date(row.created_at)), row)); // last check-in per week wins, insertion order stays chronological
  const weekly = [...weekMap.values()];
  const baseline = chrono[0], current = chrono[chrono.length - 1];
  const delta = current.score - baseline.score;
  const deltaClass = delta > 0 ? "up" : delta < 0 ? "down" : "flat";

  let compareHtml;
  if (chrono.length >= 2) {
    const weeks = Math.max(0, weekly.length - 1);
    compareHtml = `<div class="progress-compare">
      <div class="progress-photo">${baseline.photo_url ? `<img src="${baseline.photo_url}" alt="">` : `<div class="progress-photo-placeholder"></div>`}<small>${escapeHtml(t("progress_before"))}</small><b>${baseline.score}</b></div>
      <div class="progress-delta ${deltaClass}">${delta > 0 ? "+" : ""}${delta}</div>
      <div class="progress-photo">${current.photo_url ? `<img src="${current.photo_url}" alt="">` : `<div class="progress-photo-placeholder"></div>`}<small>${escapeHtml(t("progress_after"))}</small><b>${current.score}</b></div>
    </div><div class="muted progress-note">${escapeHtml(t("progress_span", weeks))}</div>`;
  } else {
    compareHtml = `<div class="status">${escapeHtml(t("progress_need_more"))}</div>`;
  }

  const timelineHtml = `<div class="progress-timeline">${rows.slice(0, 12).map(row => `<div class="progress-tl-item">${row.photo_url ? `<img src="${row.photo_url}" alt="">` : `<div class="progress-tl-placeholder"></div>`}<b>${row.score}</b><small>${new Date(row.created_at).toLocaleDateString()}</small></div>`).join("")}</div>`;

  wrap.innerHTML = `${compareHtml}${timelineHtml}<canvas id="progressChart" class="progress-chart"></canvas>`;
  if (weekly.length >= 2) drawProgressChart(weekly.map(row => row.score));
}

async function loadHistories() {
  try {
    if ($("faceHistory")) {
      const rows = await api("/api/face/history");
      $("faceHistory").innerHTML = rows.length ? rows.map(x => `<div class="song">${x.photo_url ? `<img class="history-thumb" src="${x.photo_url}" alt="">` : ""}<b>${x.score}/100 · ${escapeHtml(x.type || tierForScore(x.score))}</b><small>${new Date(x.created_at).toLocaleString()}</small></div>`).join("") : `<div class='muted'>${escapeHtml(t("history_empty"))}</div>`;
      renderProgress(rows);
    }
    if ($("eloHistory")) { const rows = await api("/api/elo/history"); $("eloHistory").innerHTML = rows.length ? rows.map(x => `<div class="song"><b>${x.delta >= 0 ? "+" : ""}${x.delta} ELO</b><small>vs ${escapeHtml(x.opponent)} · ${new Date(x.created_at).toLocaleString()}</small></div>`).join("") : `<div class='muted'>${escapeHtml(t("elo_history_empty"))}</div>`; }
    await loadEloStatus();
    await loadReminderStatus();
  } catch (e) { console.warn("history:", e); }
}
// Weekly check-in reminder toggle, shown on the Face tab's progress card
// once we know Telegram has a chat to send to (set on every Telegram login).
async function loadReminderStatus() {
  const btn = $("remindToggle");
  if (!btn) return;
  try {
    const r = await api("/api/reminders/status");
    if (!r.linked) { btn.classList.add("hidden"); return; }
    btn.classList.remove("hidden");
    btn.dataset.enabled = r.enabled ? "1" : "0";
    btn.textContent = r.enabled ? t("progress_remind_disable") : t("progress_remind_enable");
  } catch (e) { console.warn("reminders:", e); }
}
async function toggleReminders() {
  const btn = $("remindToggle");
  if (!btn) return;
  const next = btn.dataset.enabled !== "1";
  try {
    const r = await api("/api/reminders/opt-in", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: next }) });
    btn.dataset.enabled = r.enabled ? "1" : "0";
    btn.textContent = r.enabled ? t("progress_remind_disable") : t("progress_remind_enable");
    toast(r.enabled ? t("toast_reminders_on") : t("toast_reminders_off"));
  } catch (e) { toast(e.message); }
}
$("remindToggle")?.addEventListener("click", toggleReminders);
async function loadLeaderboard() { try { const rows = await api("/api/leaderboard"); if ($("leaderboardList")) $("leaderboardList").innerHTML = rows.length ? rows.map(x => `<div class="song"><b>#${x.rank} · ${escapeHtml(x.name)}</b><span>${x.elo} ELO · ${x.prime_score}/100 · ${tierForScore(x.prime_score)} · ${x.wins}W/${x.losses}L</span></div>`).join("") : `<div class='muted'>${escapeHtml(t("leaderboard_empty"))}</div>`; } catch (e) { toast(e.message); } }
async function loadMusic() { try { tracks = await api("/api/music"); if ($("songs")) $("songs").innerHTML = tracks.length ? tracks.map(tr => `<div class="song"><button data-play="${tr.id}">▶</button><b>${escapeHtml(tr.name)}</b><button data-del="${tr.id}">×</button></div>`).join("") : `<div class='song'>${escapeHtml(t("music_empty"))}</div>`; document.querySelectorAll("[data-play]").forEach(b => b.addEventListener("click", () => playTrack(b.dataset.play))); document.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", async () => { await api(`/api/music/${b.dataset.del}`, { method: "DELETE" }); await loadMusic(); toast(t("toast_track_deleted")); })); } catch (e) { toast(e.message); } }
async function playTrack(id) { const tr = tracks.find(x => String(x.id) === String(id)); if (!tr) return; if ($("audio")) { $("audio").src = tr.url; $("nowPlaying").textContent = tr.name; await $("audio").play().catch(() => {}); } }
$("addMusic")?.addEventListener("click", () => $("musicInput")?.click());
$("musicInput")?.addEventListener("change", async e => { for (const file of e.target.files || []) { const fd = new FormData(); fd.append("file", file); try { await api("/api/music", { method: "POST", body: fd }); } catch (err) { toast(err.message); } } e.target.value = ""; await loadMusic(); });
async function loadAdvice() {
  try {
    const r = await api("/api/advice", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request: "Give concise practical advice" }) });
    if (r.pro_locked) {
      $("adviceLocked")?.classList.remove("hidden");
      if ($("adviceFocus")) $("adviceFocus").innerHTML = "";
      if ($("adviceList")) $("adviceList").innerHTML = "";
      return;
    }
    $("adviceLocked")?.classList.add("hidden");
    const focus = r.focus || [];
    if ($("adviceFocus")) {
      $("adviceFocus").innerHTML = focus.length
        ? focus.map(f => `<div class="card focus-card"><div class="focus-head"><b>${escapeHtml(f.label || f.metric || "")}</b>${f.score != null ? `<span class="focus-score">${f.score}/100</span>` : ""}</div><p>${escapeHtml(f.action || "")}</p></div>`).join("")
        : "";
    }
    if ($("adviceList")) $("adviceList").innerHTML = (r.tips || []).map(x => `<div><b>AI</b><span>${escapeHtml(x)}</span></div>`).join("") || `<div><b>AI</b><span>${escapeHtml(t("advice_empty"))}</span></div>`;
  } catch (e) { toast(e.message); }
}
$("refreshAdvice")?.addEventListener("click", loadAdvice);

// PRIME Pro: subscription paid with Telegram Stars via
// Telegram.WebApp.openInvoice -- the invoice link itself is minted
// server-side (POST /api/pay/create-invoice) so the price and payload
// signature never live in client code.
async function loadProStatus() {
  try {
    const s = await api("/api/pay/status");
    if ($("proStatus")) $("proStatus").textContent = s.is_pro
      ? t("pro_status_active", new Date(s.pro_until).toLocaleDateString("ru-RU"))
      : t("pro_status_free");
    if ($("proBenefit2")) $("proBenefit2").textContent = t("pro_benefit_2", s.battle_daily_limit);
    if ($("proPrice")) $("proPrice").textContent = t("pro_price_label", s.price_stars, s.duration_days);
    if ($("buyProBtn")) $("buyProBtn").textContent = s.is_pro ? t("pro_buy_btn_renew") : t("pro_buy_btn");
    if ($("rankLabel") && s.is_pro && !$("rankLabel").textContent.includes("PRO")) {
      $("rankLabel").textContent = `${$("rankLabel").textContent} · PRO`;
    }
    return s;
  } catch (e) { console.warn("Pro status:", e); return null; }
}

async function buyPro() {
  const btn = $("buyProBtn");
  if (btn) btn.disabled = true;
  if ($("proStatus")) $("proStatus").textContent = t("pro_buy_pending");
  try {
    const r = await api("/api/pay/create-invoice", { method: "POST" });
    const link = r.invoice_link;
    const wa = window.Telegram && window.Telegram.WebApp;
    if (wa && typeof wa.openInvoice === "function") {
      wa.openInvoice(link, (status) => {
        if (btn) btn.disabled = false;
        if (status === "paid") {
          toast(t("pro_buy_success"));
          loadProStatus(); loadProfile();
          if (document.querySelector(".view.active")?.id === "advice") loadAdvice();
        } else if (status === "cancelled") {
          toast(t("pro_buy_cancelled"));
          loadProStatus();
        } else {
          loadProStatus();
        }
      });
    } else {
      // Not running inside Telegram's WebApp (e.g. opened in a plain
      // browser tab) -- Stars invoice links are also valid t.me links, so
      // opening one directly still lets Telegram handle the payment.
      window.open(link, "_blank");
      if (btn) btn.disabled = false;
      loadProStatus();
    }
  } catch (e) {
    toast(t("pro_buy_failed", e.message));
    if ($("proStatus")) $("proStatus").textContent = "";
    if (btn) btn.disabled = false;
  }
}
$("buyProBtn")?.addEventListener("click", buyPro);
$("adviceUnlockBtn")?.addEventListener("click", buyPro);

// Re-render whatever the current view already shows (menus, statuses,
// empty-states) when the language changes -- new fetches naturally come
// back in the new language, but already-rendered chrome needs a nudge.
document.addEventListener("prime:langchange", () => {
  const active = document.querySelector(".view.active")?.id;
  if (active === "advice") loadAdvice();
  if (active === "music") loadMusic();
  if (active === "face") loadHistories();
  if (active === "leaderboard") loadLeaderboard();
  if ($("eloBox")) loadEloStatus();
  if ($("remindToggle")) loadReminderStatus();
});

(async function bootstrap() {
  setAuth(t("auth_connecting"));
  try {
    if (token) { setAuth(t("auth_restoring")); await withTimeout(loadProfile(), 30000); hideAuth(); await loadEloStatus(); loadProStatus(); return; }
    await authenticateTelegram();
  } catch (e) { console.error("PRIME bootstrap failed", e); token = ""; safeStorageRemove(tokenKey); showAuth(); setAuth(t("auth_load_error", e.message)); }
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
