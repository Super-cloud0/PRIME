// PRIME i18n: RU/EN interface translation.
//
// Language is picked in this order:
//   1. explicit user choice, saved in localStorage (set by the header toggle button)
//   2. Telegram's own language_code for this user (available once telegram-web-app.js
//      has loaded and Telegram has handed us initData -- may not be ready yet the
//      instant this file runs, so telegram_session_bootstrap.js calls refineFromTelegram()
//      again once it is, but only if the user never made an explicit choice)
//   3. the browser's own language (navigator.language) as a last resort
//   4. "ru" as the final fallback, since that's this app's original language
//
// Loaded first (before telegram_session_bootstrap.js/app.js/share.js) so t() and
// applyStaticTranslations() are available to every other script from the start.
(function () {
  const STORAGE_KEY = "prime_lang";

  const DICT = {
    ru: {
      auth_intro: "Открой PRIME из Telegram — аккаунт создастся автоматически.",
      auth_checking: "Проверяем Telegram…",
      nav_home: "Главная",
      home_score_eyebrow: "YOUR PRIME SCORE",
      home_rank_placeholder: "ANALYZE YOUR PHOTO",
      home_elo_label: "FACE ELO",
      home_go_face: "📸 ОЦЕНИТЬ ВНЕШНОСТЬ",
      home_section_title: "Что сейчас",
      home_section_count: "5 функций",
      home_row_face_title: "Оценка по фото",
      home_row_face_sub: "Score + history",
      home_row_music_title: "Mogger Music",
      home_row_music_sub: "Твоя библиотека",
      home_row_advice_title: "Советы",
      home_row_advice_sub: "AI coach",
      home_row_leaderboard_title: "Global Leaderboard",
      home_row_leaderboard_sub: "Рейтинг PRIME",
      home_row_compare_title: "Сравнить лица",
      home_row_compare_sub: "Кто выглядит лучше?",
      home_mini_text: "Фото → score → Elo → музыка → советы. Данные сохраняются отдельно для каждого Telegram-аккаунта.",
      back: "‹ Назад",
      face_eyebrow: "FACE ANALYSIS",
      face_title: "Оценка внешности",
      face_sub: "Развлекательная визуальная оценка, не медицинский или научный диагноз.",
      face_pick_photo: "Выбрать фото",
      face_pick_photo_hint: "JPG / PNG",
      face_status_ready: "Готов к анализу",
      face_analyze_btn: "АНАЛИЗИРОВАТЬ",
      face_visual_score_eyebrow: "YOUR VISUAL SCORE",
      face_reference_scale_title: "Reference scale",
      face_reference_scale_sub: "твоя позиция",
      face_next_steps_title: "Следующие шаги",
      face_next_steps_sub: "AI",
      face_play_elo: "⚔ СЫГРАТЬ ELO-МАТЧ",
      face_history_title: "История анализа",
      face_history_sub: "100 последних",
      face_elo_history_title: "ELO история",
      face_elo_history_sub: "100 матчей",
      progress_title: "Прогресс",
      progress_sub: "раз в неделю",
      progress_loading: "Загрузка…",
      progress_empty: "Пока нет ни одного анализа.",
      progress_before: "Было",
      progress_after: "Сейчас",
      progress_need_more: "Сделай ещё один анализ через неделю, чтобы увидеть прогресс.",
      progress_span: (weeks) => {
        const n = Math.abs(Number(weeks) || 0);
        const mod10 = n % 10, mod100 = n % 100;
        let word;
        if (mod10 === 1 && mod100 !== 11) word = "неделю";
        else if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) word = "недели";
        else word = "недель";
        return `За ${n} ${word}`;
      },
      progress_remind_enable: "🔔 Напоминать раз в неделю",
      progress_remind_disable: "🔕 Отключить напоминания",
      toast_reminders_on: "Напоминания включены — раз в неделю пришлём сообщение в Telegram",
      toast_reminders_off: "Напоминания выключены",
      music_eyebrow: "MOGGER MODE",
      music_title: "Музыка",
      music_sub: "Треки хранятся в твоей персональной библиотеке на сервере.",
      music_now_playing_empty: "Ничего не играет",
      music_add_track: "＋ ДОБАВИТЬ ТРЕК",
      advice_eyebrow: "COACH",
      advice_title: "Советы",
      advice_sub: "Персональные безопасные рекомендации от AI.",
      advice_loading_title: "Загрузка…",
      advice_loading_sub: "AI coach готовит рекомендации.",
      advice_refresh: "ОБНОВИТЬ",
      leaderboard_eyebrow: "RANKING",
      leaderboard_title: "Leaderboard",
      compare_eyebrow: "FACE BATTLE",
      compare_title: "Сравнение",
      compare_sub: "Загрузи два фото — узнай у кого выше PRIME Score.",
      compare_slot_a: "Фото 1",
      compare_slot_b: "Фото 2",
      compare_status_ready: "Загрузи оба фото",
      compare_status_both_ready: "Готово к сравнению",
      compare_status_comparing: "AI сравнивает…",
      compare_status_done: "Сравнение завершено",
      compare_button: "СРАВНИТЬ",
      compare_winner_label: "🏆 Победитель",
      compare_tie_label: "🤝 Ничья",
      compare_reset: "Новое сравнение",
      compare_error_need_both: "Сначала загрузи оба фото",
      lang_toggle_label: "EN",

      toast_photo_ready: "Фото готово",
      toast_pick_photo_first: "Сначала выбери фото",
      status_analyzing: "AI анализирует фото…",
      status_analysis_done: "AI анализ завершён.",
      status_analysis_failed: (msg) => `Ошибка AI: ${msg}`,
      analysis_default_summary: "Анализ завершён.",
      toast_score: (score, tier) => `PRIME Score: ${score} • ${tier}`,
      metric_symmetry: "Симметрия",
      metric_proportion: "Пропорции",
      metric_grooming: "Уход",
      metric_hair: "Волосы",
      metric_skin_appearance: "Внешний вид кожи",
      metric_presentation: "Презентация",
      elo_title: "⚔ PRIME ELO",
      elo_voluntary: "участие добровольное",
      elo_hint: "Последнее проанализированное фото используется только для ELO-матчей.",
      elo_enable: "ВКЛЮЧИТЬ ELO",
      elo_disable: "ВЫКЛЮЧИТЬ ELO",
      elo_checking: "Проверка…",
      elo_you: "ТЫ",
      elo_ready: "Готов",
      elo_enabled_status: (elo, games) => `ELO включён • ${elo} • ${games} матчей`,
      elo_disabled_status_needs_photo: "ELO выключен • сначала нужен анализ фото",
      elo_disabled_status_photo_ready: "ELO выключен • фото готово",
      toast_elo_enabled: "ELO включён",
      toast_elo_disabled: "ELO выключен",
      err_need_new_analysis: "Сначала сделай новый анализ фото",
      err_need_analysis: "Сначала сделай анализ фото",
      elo_searching: "🔎 Ищем участника…",
      elo_comparing: "⚡ СРАВНИВАЕМ…",
      elo_tie: (elo) => `🤝 НИЧЬЯ • ELO ${elo}`,
      elo_win: (delta) => `🏆 ПОБЕДА • +${delta} ELO`,
      elo_loss: (delta) => `💥 ПОРАЖЕНИЕ • ${delta} ELO`,
      toast_elo_tie: "ELO: ничья",
      history_empty: "История пуста.",
      elo_history_empty: "Матчей пока нет.",
      leaderboard_empty: "Пока нет игроков.",
      music_empty: "Пока нет треков.",
      toast_track_deleted: "Трек удалён",
      advice_empty: "Нет рекомендаций.",
      auth_not_found: "Telegram WebApp не найден. Открой PRIME через кнопку бота.",
      auth_init: "Инициализация Telegram…",
      auth_no_initdata: "Telegram не передал initData. Закрой PRIME и открой заново через кнопку бота.",
      auth_session_expired: "Сессия истекла. Открываем Telegram-вход…",
      auth_render_timeout: "Render не ответил за 30 секунд. Повторяю…",
      auth_retrying: "Повторная попытка подключения…",
      auth_login_error: (msg) => `Ошибка входа: ${msg}`,
      auth_ready: (name) => `PRIME готов${name ? `, ${name}` : ""}`,
      auth_connecting: "Подключаемся к серверу… (если он спал, это может занять до минуты)",
      auth_restoring: "Восстанавливаем сессию…",
      auth_load_error: (msg) => `Ошибка загрузки PRIME: ${msg}`,
      err_prepare_photo: "Не удалось подготовить фото",
      err_read_photo: "Не удалось прочитать фото",

      share_title: "🔥 Твоя карточка",
      share_subtitle: "готова для тикток и сторис",
      share_score_label: "PRIME SCORE",
      share_card_eyebrow: "FACE RATING",
      share_footer: "Проверь себя в PRIME ⚡",
      share_btn_telegram: "✈️ TELEGRAM",
      share_btn_native: "↗ ПОДЕЛИТЬСЯ",
      share_btn_copy: "⧉ СКОПИРОВАТЬ",
      share_btn_download: "⬇️ СКАЧАТЬ",
      share_building: "Собираем карточку…",
      share_downloaded: "Карточка сохранена",
      share_card_failed: "Не удалось собрать карточку",
      share_copied: "Результат скопирован",
      share_copy_failed: "Не удалось скопировать",
      share_failed: "Не удалось поделиться",
      share_text: (score, tier, elo) => `Мой PRIME Score: ${score}/100 • ${tier}\nELO: ${elo}\n\nПроверь себя в PRIME ⚡`,
    },
    en: {
      auth_intro: "Open PRIME from Telegram — your account is created automatically.",
      auth_checking: "Checking Telegram…",
      nav_home: "Home",
      home_score_eyebrow: "YOUR PRIME SCORE",
      home_rank_placeholder: "ANALYZE YOUR PHOTO",
      home_elo_label: "FACE ELO",
      home_go_face: "📸 RATE MY LOOKS",
      home_section_title: "Right now",
      home_section_count: "5 features",
      home_row_face_title: "Photo rating",
      home_row_face_sub: "Score + history",
      home_row_music_title: "Mogger Music",
      home_row_music_sub: "Your library",
      home_row_advice_title: "Advice",
      home_row_advice_sub: "AI coach",
      home_row_leaderboard_title: "Global Leaderboard",
      home_row_leaderboard_sub: "PRIME ranking",
      home_row_compare_title: "Face Battle",
      home_row_compare_sub: "Who looks better?",
      home_mini_text: "Photo → score → Elo → music → advice. Data is saved separately for every Telegram account.",
      back: "‹ Back",
      face_eyebrow: "FACE ANALYSIS",
      face_title: "Face rating",
      face_sub: "A fun visual rating, not a medical or scientific diagnosis.",
      face_pick_photo: "Choose a photo",
      face_pick_photo_hint: "JPG / PNG",
      face_status_ready: "Ready to analyze",
      face_analyze_btn: "ANALYZE",
      face_visual_score_eyebrow: "YOUR VISUAL SCORE",
      face_reference_scale_title: "Reference scale",
      face_reference_scale_sub: "your position",
      face_next_steps_title: "Next steps",
      face_next_steps_sub: "AI",
      face_play_elo: "⚔ PLAY AN ELO MATCH",
      face_history_title: "Analysis history",
      face_history_sub: "last 100",
      face_elo_history_title: "ELO history",
      face_elo_history_sub: "last 100 matches",
      progress_title: "Progress",
      progress_sub: "once a week",
      progress_loading: "Loading…",
      progress_empty: "No analyses yet.",
      progress_before: "Before",
      progress_after: "Now",
      progress_need_more: "Run another scan next week to start seeing progress.",
      progress_span: (weeks) => {
        const n = Math.abs(Number(weeks) || 0);
        return `Over ${n} week${n === 1 ? "" : "s"}`;
      },
      progress_remind_enable: "🔔 Remind me weekly",
      progress_remind_disable: "🔕 Turn off reminders",
      toast_reminders_on: "Reminders on — we'll ping you in Telegram once a week",
      toast_reminders_off: "Reminders off",
      music_eyebrow: "MOGGER MODE",
      music_title: "Music",
      music_sub: "Tracks are stored in your personal library on the server.",
      music_now_playing_empty: "Nothing playing",
      music_add_track: "＋ ADD TRACK",
      advice_eyebrow: "COACH",
      advice_title: "Advice",
      advice_sub: "Personal, safe recommendations from AI.",
      advice_loading_title: "Loading…",
      advice_loading_sub: "AI coach is preparing recommendations.",
      advice_refresh: "REFRESH",
      leaderboard_eyebrow: "RANKING",
      leaderboard_title: "Leaderboard",
      compare_eyebrow: "FACE BATTLE",
      compare_title: "Compare",
      compare_sub: "Upload two photos — see whose PRIME Score is higher.",
      compare_slot_a: "Photo 1",
      compare_slot_b: "Photo 2",
      compare_status_ready: "Upload both photos",
      compare_status_both_ready: "Ready to compare",
      compare_status_comparing: "AI is comparing…",
      compare_status_done: "Comparison complete",
      compare_button: "COMPARE",
      compare_winner_label: "🏆 Winner",
      compare_tie_label: "🤝 Tie",
      compare_reset: "New comparison",
      compare_error_need_both: "Upload both photos first",
      lang_toggle_label: "RU",

      toast_photo_ready: "Photo ready",
      toast_pick_photo_first: "Choose a photo first",
      status_analyzing: "AI is analyzing the photo…",
      status_analysis_done: "AI analysis complete.",
      status_analysis_failed: (msg) => `AI error: ${msg}`,
      analysis_default_summary: "Analysis complete.",
      toast_score: (score, tier) => `PRIME Score: ${score} • ${tier}`,
      metric_symmetry: "Symmetry",
      metric_proportion: "Proportion",
      metric_grooming: "Grooming",
      metric_hair: "Hair",
      metric_skin_appearance: "Skin appearance",
      metric_presentation: "Presentation",
      elo_title: "⚔ PRIME ELO",
      elo_voluntary: "participation is optional",
      elo_hint: "Your last analyzed photo is used only for ELO matches.",
      elo_enable: "ENABLE ELO",
      elo_disable: "DISABLE ELO",
      elo_checking: "Checking…",
      elo_you: "YOU",
      elo_ready: "Ready",
      elo_enabled_status: (elo, games) => `ELO on • ${elo} • ${games} matches`,
      elo_disabled_status_needs_photo: "ELO off • analyze a photo first",
      elo_disabled_status_photo_ready: "ELO off • photo ready",
      toast_elo_enabled: "ELO enabled",
      toast_elo_disabled: "ELO disabled",
      err_need_new_analysis: "Analyze a new photo first",
      err_need_analysis: "Analyze a photo first",
      elo_searching: "🔎 Finding an opponent…",
      elo_comparing: "⚡ COMPARING…",
      elo_tie: (elo) => `🤝 TIE • ELO ${elo}`,
      elo_win: (delta) => `🏆 WIN • +${delta} ELO`,
      elo_loss: (delta) => `💥 LOSS • ${delta} ELO`,
      toast_elo_tie: "ELO: tie",
      history_empty: "No history yet.",
      elo_history_empty: "No matches yet.",
      leaderboard_empty: "No players yet.",
      music_empty: "No tracks yet.",
      toast_track_deleted: "Track deleted",
      advice_empty: "No recommendations.",
      auth_not_found: "Telegram WebApp not found. Open PRIME via the bot button.",
      auth_init: "Initializing Telegram…",
      auth_no_initdata: "Telegram didn't send initData. Close PRIME and reopen it via the bot button.",
      auth_session_expired: "Session expired. Opening Telegram sign-in…",
      auth_render_timeout: "Render didn't respond in 30 seconds. Retrying…",
      auth_retrying: "Retrying connection…",
      auth_login_error: (msg) => `Login error: ${msg}`,
      auth_ready: (name) => `PRIME is ready${name ? `, ${name}` : ""}`,
      auth_connecting: "Connecting to the server… (if it was asleep, this can take up to a minute)",
      auth_restoring: "Restoring your session…",
      auth_load_error: (msg) => `PRIME failed to load: ${msg}`,
      err_prepare_photo: "Couldn't prepare the photo",
      err_read_photo: "Couldn't read the photo",

      share_title: "🔥 Your card",
      share_subtitle: "ready for tiktok & stories",
      share_score_label: "PRIME SCORE",
      share_card_eyebrow: "FACE RATING",
      share_footer: "Check yourself on PRIME ⚡",
      share_btn_telegram: "✈️ TELEGRAM",
      share_btn_native: "↗ SHARE",
      share_btn_copy: "⧉ COPY",
      share_btn_download: "⬇️ DOWNLOAD",
      share_building: "Building your card…",
      share_downloaded: "Card saved",
      share_card_failed: "Couldn't build the card",
      share_copied: "Result copied",
      share_copy_failed: "Couldn't copy",
      share_failed: "Couldn't share",
      share_text: (score, tier, elo) => `My PRIME Score: ${score}/100 • ${tier}\nELO: ${elo}\n\nCheck yourself on PRIME ⚡`,
    },
  };

  function detectInitial() {
    let saved = null;
    try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) {}
    if (saved === "ru" || saved === "en") return { lang: saved, explicit: true };
    const nav = String((navigator.languages && navigator.languages[0]) || navigator.language || "").toLowerCase();
    return { lang: nav.startsWith("ru") ? "ru" : "en", explicit: false };
  }

  const initial = detectInitial();
  let currentLang = initial.lang;
  let isExplicit = initial.explicit;

  function t(key, ...args) {
    const entry = (DICT[currentLang] || DICT.ru)[key];
    if (entry === undefined) return key;
    return typeof entry === "function" ? entry(...args) : entry;
  }

  function applyStaticTranslations(root) {
    (root || document).querySelectorAll("[data-i18n]").forEach(el => {
      const val = t(el.getAttribute("data-i18n"));
      if (typeof val === "string") el.textContent = val;
    });
    const toggle = document.getElementById("langToggle");
    if (toggle) toggle.textContent = t("lang_toggle_label");
  }

  function setLang(lang, persist) {
    if (lang !== "ru" && lang !== "en") return;
    currentLang = lang;
    if (persist) {
      isExplicit = true;
      try { localStorage.setItem(STORAGE_KEY, lang); } catch (e) {}
    }
    applyStaticTranslations();
    document.dispatchEvent(new CustomEvent("prime:langchange", { detail: { lang } }));
  }

  // Called once Telegram's initData is actually available (from
  // telegram_session_bootstrap.js), to refine the initial guess -- but only
  // if the user hasn't already made an explicit choice via the toggle.
  function refineFromTelegram(languageCode) {
    if (isExplicit || !languageCode) return;
    const lang = String(languageCode).toLowerCase().startsWith("ru") ? "ru" : "en";
    if (lang !== currentLang) setLang(lang, false);
  }

  window.PrimeI18N = {
    t,
    setLang,
    refineFromTelegram,
    applyStaticTranslations,
    getLang: () => currentLang,
    isExplicit: () => isExplicit,
  };

  // This file is loaded with `defer`, so by the time it runs the DOM is
  // already fully parsed (that's what `defer` guarantees) -- no need to
  // wait for DOMContentLoaded.
  applyStaticTranslations();
  document.getElementById("langToggle")?.addEventListener("click", () => setLang(currentLang === "ru" ? "en" : "ru", true));
})();
