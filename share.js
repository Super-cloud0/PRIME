(function(){
  const $=id=>document.getElementById(id);
  const scoreTier=s=>{const n=Math.max(1,Math.min(100,Number(s)||1));if(n<=29)return"SUB 3";if(n<=44)return"SUB 5";if(n<=59)return"LTN";if(n<=74)return"MTN";if(n<=79)return"HTN";if(n<=94)return"CHAD";return"TRUE ADAM"};
  const shareUrl=()=>location.origin+location.pathname;
  const shareText=()=>{const score=Number($("faceScore")?.textContent||0),tier=$("type")?.textContent||scoreTier(score),elo=$("elo")?.textContent||"1000";return `Мой PRIME Score: ${score}/100 • ${tier}\nELO: ${elo}\n\nПроверь себя в PRIME ⚡`};
  function telegramUrl(){const text=shareText();return `https://t.me/share/url?url=${encodeURIComponent(shareUrl())}&text=${encodeURIComponent(text)}`}
  function render(){
    const result=$("faceResult");
    if(!result||$("primeSharePanel"))return;
    const panel=document.createElement("div");panel.id="primeSharePanel";panel.className="card";
    panel.innerHTML='<div class="section-title"><span>🔥 Твой результат</span><small>поделись PRIME</small></div><div style="border-radius:20px;padding:22px;background:linear-gradient(145deg,#090909,#222);color:#fff;text-align:center;border:1px solid rgba(255,255,255,.1)"><div style="font-size:11px;letter-spacing:.18em;opacity:.55">PRIME SCORE</div><div id="shareScore" style="font-size:64px;font-weight:900;line-height:1.05;margin:8px 0">--</div><div id="shareTier" style="font-size:18px;font-weight:800;letter-spacing:.08em">--</div><div id="shareElo" style="margin-top:10px;opacity:.65">ELO --</div><div style="margin-top:16px;font-size:12px;opacity:.5">Проверь себя в PRIME ⚡</div></div><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px"><button id="shareTelegram" class="secondary">✈️ TELEGRAM</button><button id="shareNative" class="primary">↗ ПОДЕЛИТЬСЯ</button></div><button id="shareCopy" class="secondary" style="width:100%;margin-top:10px">⧉ СКОПИРОВАТЬ</button>';
    result.appendChild(panel);
    $("shareTelegram").onclick=()=>window.open(telegramUrl(),"_blank");
    $("shareCopy").onclick=async()=>{try{await navigator.clipboard.writeText(shareText()+`\n${shareUrl()}`);if(window.Telegram?.WebApp?.HapticFeedback)window.Telegram.WebApp.HapticFeedback.notificationOccurred("success");toast("Результат скопирован")}catch(e){toast("Не удалось скопировать")}};
    $("shareNative").onclick=async()=>{try{if(navigator.share)await navigator.share({title:"PRIME Score",text:shareText(),url:shareUrl()});else await navigator.clipboard.writeText(shareText()+`\n${shareUrl()}`)}catch(e){if(e?.name!=="AbortError")toast("Не удалось поделиться")}};
    refresh();
  }
  function refresh(){if(!$("primeSharePanel"))return;const score=Number($("faceScore")?.textContent||0),tier=$("type")?.textContent||scoreTier(score),elo=$("elo")?.textContent||"1000";$("shareScore").textContent=score;$("shareTier").textContent=tier;$("shareElo").textContent=`ELO ${elo}`}
  const result=$("faceResult");if(result){const ob=new MutationObserver(()=>{render();refresh()});ob.observe(result,{subtree:true,childList:true,characterData:true})}
  document.addEventListener("DOMContentLoaded",()=>{render();refresh()});setTimeout(()=>{render();refresh()},800);
})();