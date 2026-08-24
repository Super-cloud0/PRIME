// PRIME result-sharing panel (Telegram share / native share / copy).
//
// NOTE: this file used to also own its own document-level click/pointerup
// interceptors (capture phase + stopImmediatePropagation) as a navigation
// "emergency fallback", and forcibly poked #auth's inline styles. Both were
// redundant: navigation is owned exclusively by app.js's go() (the only
// implementation that also loads each tab's data), and the #auth overlay is
// already permanently disabled via style.css (.auth-overlay{display:none
// !important}). Having multiple systems race for the same clicks is what
// caused tabs to look empty/frozen -- this file now only renders the share
// panel.
(function(){
  const $=id=>document.getElementById(id);
  const t=(...args)=>(window.PrimeI18N?window.PrimeI18N.t(...args):args[0]);
  const scoreTier=s=>{const n=Math.max(1,Math.min(100,Number(s)||1));if(n<=29)return"SUB 3";if(n<=44)return"SUB 5";if(n<=59)return"LTN";if(n<=74)return"MTN";if(n<=79)return"HTN";if(n<=94)return"CHAD";return"TRUE ADAM"};
  const shareUrl=()=>location.origin+location.pathname;
  const shareText=()=>{const score=Number($("faceScore")?.textContent||0),tier=$("type")?.textContent||scoreTier(score),elo=$("elo")?.textContent||"1000";return t("share_text",score,tier,elo)};
  function telegramUrl(){const text=shareText();return `https://t.me/share/url?url=${encodeURIComponent(shareUrl())}&text=${encodeURIComponent(text)}`}

  function render(){
    const result=$("faceResult");
    if(!result||$("primeSharePanel"))return;
    const panel=document.createElement("div");panel.id="primeSharePanel";panel.className="card";
    panel.innerHTML=`<div class="section-title"><span>${escapeAttr(t("share_title"))}</span><small>${escapeAttr(t("share_subtitle"))}</small></div><div style="border-radius:20px;padding:22px;background:linear-gradient(145deg,#090909,#222);color:#fff;text-align:center;border:1px solid rgba(255,255,255,.1)"><div style="font-size:11px;letter-spacing:.18em;opacity:.55">${escapeAttr(t("share_score_label"))}</div><div id="shareScore" style="font-size:64px;font-weight:900;line-height:1.05;margin:8px 0">--</div><div id="shareTier" style="font-size:18px;font-weight:800;letter-spacing:.08em">--</div><div id="shareElo" style="margin-top:10px;opacity:.65">ELO --</div><div style="margin-top:16px;font-size:12px;opacity:.5">${escapeAttr(t("share_footer"))}</div></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px"><button id="shareTelegram" class="secondary">${escapeAttr(t("share_btn_telegram"))}</button><button id="shareNative" class="primary">${escapeAttr(t("share_btn_native"))}</button></div><button id="shareCopy" class="secondary" style="width:100%;margin-top:10px">${escapeAttr(t("share_btn_copy"))}</button>`;
    result.appendChild(panel);
    $("shareTelegram").onclick=()=>window.open(telegramUrl(),"_blank");
    $("shareCopy").onclick=async()=>{try{await navigator.clipboard.writeText(shareText()+`\n${shareUrl()}`);if(window.Telegram?.WebApp?.HapticFeedback)window.Telegram.WebApp.HapticFeedback.notificationOccurred("success");toast(t("share_copied"))}catch(e){toast(t("share_copy_failed"))}};
    $("shareNative").onclick=async()=>{try{if(navigator.share)await navigator.share({title:"PRIME Score",text:shareText(),url:shareUrl()});else await navigator.clipboard.writeText(shareText()+`\n${shareUrl()}`)}catch(e){if(e?.name!=="AbortError")toast(t("share_failed"))}};
    refresh();
  }
  function escapeAttr(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m]))}
  function refresh(){if(!$("primeSharePanel"))return;const score=Number($("faceScore")?.textContent||0),tier=$("type")?.textContent||scoreTier(score),elo=$("elo")?.textContent||"1000";$("shareScore").textContent=score;$("shareTier").textContent=tier;$("shareElo").textContent=`ELO ${elo}`}
  const result=$("faceResult");
  let ob=null;
  function withObserverPaused(fn){
    // render()/refresh() (and, on a language change, removing+rebuilding the
    // panel) write INTO this same subtree (appendChild, textContent), and the
    // observer below watches that subtree with subtree+characterData -- so
    // without disconnecting first, every update the panel makes to itself
    // fires the observer again, forever. That infinite MutationObserver
    // feedback loop was saturating the JS microtask queue on every single
    // page load (#faceResult always exists in the DOM, analyzed or not) --
    // the page painted fine, but the main thread never went idle again, so
    // no click handler anywhere could ever run. This is the actual cause of
    // "page loads, buttons do nothing": it has nothing to do with Telegram
    // or fonts, it is 100% this feedback loop, and it reproduced identically
    // on Render, Railway, and localhost because it never depended on the
    // network at all. Every self-mutation in this file goes through this
    // same disconnect/reconnect guard, not just the original one.
    if(ob)ob.disconnect();
    fn();
    if(ob&&result)ob.observe(result,{subtree:true,childList:true,characterData:true});
  }
  if(result){
    ob=new MutationObserver(()=>withObserverPaused(()=>{render();refresh()}));
    ob.observe(result,{subtree:true,childList:true,characterData:true});
  }
  document.addEventListener("DOMContentLoaded",()=>withObserverPaused(()=>{render();refresh()}));
  setTimeout(()=>withObserverPaused(()=>{render();refresh()}),800);
  document.addEventListener("prime:langchange",()=>withObserverPaused(()=>{$("primeSharePanel")?.remove();render()}));
})();
