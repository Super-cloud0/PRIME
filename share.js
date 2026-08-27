// PRIME result-sharing panel.
//
// This file renders a downloadable/shareable "player card" image (like a
// football/FIFA-style stat card: photo + big rating + attribute grid) built
// on a <canvas>, plus a small set of share/download actions -- the goal is
// a single self-contained PNG someone can post straight to TikTok/Stories,
// not just a text link.
//
// NOTE: this file used to also own its own document-level click/pointerup
// interceptors (capture phase + stopImmediatePropagation) as a navigation
// "emergency fallback", and forcibly poked #auth's inline styles. Both were
// redundant: navigation is owned exclusively by app.js's go() (the only
// implementation that also loads each tab's data), and the #auth overlay is
// already permanently disabled via style.css (.auth-overlay{display:none
// !important}). Having multiple systems race for the same clicks is what
// caused tabs to look empty/frozen -- this file now only renders the share
// panel and the card image. Every DOM self-mutation below still goes
// through withObserverPaused (see the comment on that function) to avoid
// resurrecting that infinite-loop bug.
(function(){
  const $=id=>document.getElementById(id);
  const t=(...args)=>(window.PrimeI18N?window.PrimeI18N.t(...args):args[0]);
  const scoreTier=s=>{const n=Math.max(1,Math.min(100,Number(s)||1));if(n<=29)return"SUB 3";if(n<=44)return"SUB 5";if(n<=59)return"LTN";if(n<=74)return"MTN";if(n<=79)return"HTN";if(n<=94)return"CHAD";return"TRUE ADAM"};
  // Rarity ladder for the card: each tier gets its own accent color and a
  // filled-star count (like a trading-card rarity indicator), so the image
  // instantly signals how rare the result is instead of always looking the
  // same.
  const TIER_ORDER=["SUB 3","SUB 5","LTN","MTN","HTN","CHAD","TRUE ADAM"];
  const TIER_COLORS=["#8a8a8a","#aeaeae","#c9903f","#ff3b42","#ff7a1a","#ffcc33","#f3e6ff"];
  const tierRank=tier=>{const i=TIER_ORDER.indexOf(String(tier||"").toUpperCase());return i<0?3:i};
  const tierColor=rank=>TIER_COLORS[rank];
  // Short FIFA-style attribute codes -- kept in English on purpose (like real
  // FUT cards use the same PAC/SHO/PAS codes in every localization) so the
  // card layout never has to re-measure text for RU vs EN.
  const METRIC_ORDER=["symmetry","proportion","grooming","hair","skin_appearance","presentation"];
  const METRIC_CODES={symmetry:"SYM",proportion:"PRO",grooming:"GRM",hair:"HAIR",skin_appearance:"SKN",presentation:"PRS"};
  const shareUrl=()=>location.origin+location.pathname;
  const shareText=()=>{const d=lastResult;const score=d?d.score:Number($("faceScore")?.textContent||0);const tier=d?d.tier:($("type")?.textContent||scoreTier(score));const elo=$("elo")?.textContent||"1000";return t("share_text",score,tier,elo)};
  function telegramUrl(){const text=shareText();return `https://t.me/share/url?url=${encodeURIComponent(shareUrl())}&text=${encodeURIComponent(text)}`}
  function escapeAttr(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m]))}

  // ---- canvas card rendering -------------------------------------------
  function hexToRgb(hex){const m=/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)||[];return{r:parseInt(m[1]||"ff",16),g:parseInt(m[2]||"ff",16),b:parseInt(m[3]||"ff",16)}}
  function withAlpha(hex,a){const{r,g,b}=hexToRgb(hex);return `rgba(${r},${g},${b},${a})`}
  function roundRectPath(ctx,x,y,w,h,r){
    const rr=Math.min(r,w/2,h/2);
    ctx.beginPath();
    ctx.moveTo(x+rr,y);
    ctx.arcTo(x+w,y,x+w,y+h,rr);
    ctx.arcTo(x+w,y+h,x,y+h,rr);
    ctx.arcTo(x,y+h,x,y,rr);
    ctx.arcTo(x,y,x+w,y,rr);
    ctx.closePath();
  }
  // Manual letter-spacing: canvas ctx.letterSpacing isn't reliable across
  // the older WebViews Telegram's Android client can embed, so headline
  // labels are spaced out character-by-character instead.
  function drawSpacedText(ctx,text,x,y,spacing,align){
    const chars=[...String(text)];
    const widths=chars.map(c=>ctx.measureText(c).width);
    const total=widths.reduce((a,b)=>a+b,0)+spacing*Math.max(0,chars.length-1);
    let startX=x;
    if(align==="right")startX=x-total;else if(align==="center")startX=x-total/2;
    const prevAlign=ctx.textAlign;ctx.textAlign="left";
    let cx=startX;
    chars.forEach((c,i)=>{ctx.fillText(c,cx,y);cx+=widths[i]+spacing});
    ctx.textAlign=prevAlign;
  }
  function loadImage(src){
    return new Promise((resolve,reject)=>{
      const img=new Image();
      img.onload=()=>resolve(img);
      img.onerror=()=>reject(new Error("image load failed"));
      img.src=src;
    });
  }
  function drawCoverImage(ctx,img,x,y,w,h){
    const scale=Math.max(w/img.width,h/img.height);
    const sw=w/scale,sh=h/scale;
    const sx=Math.max(0,(img.width-sw)/2),sy=Math.max(0,(img.height-sh)/2);
    ctx.drawImage(img,sx,sy,sw,sh,x,y,w,h);
  }
  async function loadCardFonts(){
    try{
      await Promise.all([
        document.fonts.load("italic 900 48px Inter"),
        document.fonts.load("900 200px Inter"),
        document.fonts.load("900 56px Inter"),
        document.fonts.load("700 28px Inter"),
      ]);
    }catch(e){/* fall back silently to the generic sans-serif in FONT_STACK */}
  }
  const FONT_STACK="Inter, Arial, sans-serif";

  // Builds the full 1080x1920 (TikTok/Stories-ready) player-card PNG for the
  // given result. `data`: {score, tier, metrics, photo, elo}.
  async function buildCardCanvas(data){
    await loadCardFonts();
    const W=1080,H=1920;
    const canvas=document.createElement("canvas");
    canvas.width=W;canvas.height=H;
    const ctx=canvas.getContext("2d");
    const rank=tierRank(data.tier);
    const tc=tierColor(rank);

    // background: dark ground + tier-tinted glow (mirrors the in-app
    // .share-card CSS treatment) + a soft bottom vignette for legibility.
    ctx.fillStyle="#080808";ctx.fillRect(0,0,W,H);
    const rg=ctx.createRadialGradient(W/2,-150,50,W/2,-150,1500);
    rg.addColorStop(0,withAlpha(tc,0.4));
    rg.addColorStop(0.55,withAlpha(tc,0.08));
    rg.addColorStop(1,withAlpha(tc,0));
    ctx.fillStyle=rg;ctx.fillRect(0,0,W,H);
    const lg=ctx.createLinearGradient(0,H*0.5,0,H);
    lg.addColorStop(0,"rgba(0,0,0,0)");lg.addColorStop(1,"rgba(0,0,0,0.5)");
    ctx.fillStyle=lg;ctx.fillRect(0,H*0.5,W,H*0.5);

    // legendary tier gets an extra outer glow so a TRUE ADAM card reads as
    // visibly rarer even as a static image, not just a different color.
    if(rank>=6){
      ctx.save();ctx.shadowColor=tc;ctx.shadowBlur=80;
      ctx.strokeStyle=withAlpha(tc,0.9);ctx.lineWidth=3;
      roundRectPath(ctx,30,30,W-60,H-60,30);ctx.stroke();ctx.restore();
    }
    // card border frame (double line, like a trading-card edge)
    ctx.strokeStyle=withAlpha(tc,0.85);ctx.lineWidth=4;
    roundRectPath(ctx,28,28,W-56,H-56,28);ctx.stroke();
    ctx.strokeStyle=withAlpha(tc,0.25);ctx.lineWidth=1;
    roundRectPath(ctx,46,46,W-92,H-92,20);ctx.stroke();

    // header: PRIME wordmark (left) + eyebrow (right)
    ctx.textBaseline="alphabetic";
    ctx.font=`italic 900 46px ${FONT_STACK}`;ctx.textAlign="left";
    ctx.fillStyle=tc;ctx.fillText("P",70,118);
    const pWidth=ctx.measureText("P").width;
    ctx.fillStyle="#fff";ctx.fillText("RIME",70+pWidth,118);
    ctx.font=`700 24px ${FONT_STACK}`;ctx.fillStyle="#9c9c9c";
    drawSpacedText(ctx,t("share_card_eyebrow"),1010,108,4,"right");

    // score + tier + stars (top-left, like a FUT card's overall rating)
    ctx.font=`900 200px ${FONT_STACK}`;ctx.fillStyle=tc;ctx.textAlign="left";
    ctx.shadowColor=withAlpha(tc,0.55);ctx.shadowBlur=40;
    ctx.fillText(String(data.score),66,330);
    ctx.shadowBlur=0;
    ctx.font=`900 50px ${FONT_STACK}`;ctx.fillStyle="#fff";
    drawSpacedText(ctx,String(data.tier||"").toUpperCase(),74,392,4,"left");
    ctx.font="34px Arial";ctx.fillStyle=tc;ctx.textAlign="left";
    ctx.fillText("★".repeat(rank+1)+"☆".repeat(6-rank),74,438);
    ctx.font=`700 30px ${FONT_STACK}`;ctx.fillStyle="#999";ctx.textAlign="right";
    ctx.fillText(`ELO ${data.elo}`,1010,180);

    // photo
    const photoX=90,photoY=470,photoW=900,photoH=850,photoR=32;
    ctx.save();
    roundRectPath(ctx,photoX,photoY,photoW,photoH,photoR);ctx.clip();
    if(data.img)drawCoverImage(ctx,data.img,photoX,photoY,photoW,photoH);
    else{ctx.fillStyle="#151515";ctx.fillRect(photoX,photoY,photoW,photoH);}
    ctx.restore();
    ctx.save();
    ctx.shadowColor=withAlpha(tc,0.6);ctx.shadowBlur=26;
    ctx.strokeStyle=tc;ctx.lineWidth=8;
    roundRectPath(ctx,photoX,photoY,photoW,photoH,photoR);ctx.stroke();
    ctx.restore();

    // attribute grid: 6 stats, FIFA-card style (big number + short code + bar)
    const statsY=1370,colW=280,colGap=30,rowH=170,rowGap=20;
    const cols=[90,90+colW+colGap,90+(colW+colGap)*2];
    const rows=[statsY,statsY+rowH+rowGap];
    METRIC_ORDER.forEach((key,i)=>{
      const col=i%3,row=Math.floor(i/3);
      const x=cols[col],y=rows[row];
      const val=Math.max(0,Math.min(100,Number((data.metrics||{})[key])||0));
      ctx.textAlign="left";
      ctx.font=`900 56px ${FONT_STACK}`;ctx.fillStyle=tc;
      ctx.fillText(String(val),x,y+56);
      ctx.font=`700 22px ${FONT_STACK}`;ctx.fillStyle="#aaa";
      drawSpacedText(ctx,METRIC_CODES[key],x,y+88,3,"left");
      const barY=y+108,barW=colW,barH=8;
      ctx.fillStyle="rgba(255,255,255,0.12)";
      roundRectPath(ctx,x,barY,barW,barH,4);ctx.fill();
      ctx.fillStyle=tc;
      roundRectPath(ctx,x,barY,barW*(val/100),barH,4);ctx.fill();
    });

    // footer
    ctx.textAlign="center";
    ctx.font=`700 24px ${FONT_STACK}`;ctx.fillStyle="#888";
    ctx.fillText(t("share_footer"),W/2,1830);
    ctx.font=`italic 900 30px ${FONT_STACK}`;ctx.fillStyle=tc;
    ctx.fillText("PRIME",W/2,1875);

    return canvas;
  }

  // ---- panel + actions ---------------------------------------------------
  let lastResult=null; // {score, tier, metrics, photo, elo} from app.js's analyze handler
  let currentCanvas=null;
  let currentBlobUrl=null;

  function cardBlob(){return new Promise(resolve=>{if(!currentCanvas)return resolve(null);currentCanvas.toBlob(b=>resolve(b),"image/png",0.95)})}

  function render(){
    const result=$("faceResult");
    if(!result||$("primeSharePanel"))return;
    const panel=document.createElement("div");panel.id="primeSharePanel";panel.className="card";
    panel.innerHTML=`<div class="section-title"><span>${escapeAttr(t("share_title"))}</span><small>${escapeAttr(t("share_subtitle"))}</small></div><div id="shareCardWrap" class="share-card-wrap"><div class="status">${escapeAttr(t("share_building"))}</div></div><div class="share-actions"><button id="shareDownload" class="primary">${escapeAttr(t("share_btn_download"))}</button><button id="shareNative" class="primary">${escapeAttr(t("share_btn_native"))}</button></div><div class="share-actions" style="margin-top:8px"><button id="shareTelegram" class="secondary">${escapeAttr(t("share_btn_telegram"))}</button><button id="shareCopy" class="secondary">${escapeAttr(t("share_btn_copy"))}</button></div>`;
    result.appendChild(panel);
    $("shareTelegram").onclick=()=>window.open(telegramUrl(),"_blank");
    $("shareCopy").onclick=async()=>{try{await navigator.clipboard.writeText(shareText()+`\n${shareUrl()}`);if(window.Telegram?.WebApp?.HapticFeedback)window.Telegram.WebApp.HapticFeedback.notificationOccurred("success");toast(t("share_copied"))}catch(e){toast(t("share_copy_failed"))}};
    $("shareDownload").onclick=async()=>{
      const blob=await cardBlob();
      if(!blob)return toast(t("share_card_failed"));
      const url=URL.createObjectURL(blob);
      const a=document.createElement("a");a.href=url;a.download="prime-score.png";
      document.body.appendChild(a);a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),4000);
      if(window.Telegram?.WebApp?.HapticFeedback)window.Telegram.WebApp.HapticFeedback.notificationOccurred("success");
      toast(t("share_downloaded"));
    };
    $("shareNative").onclick=async()=>{
      try{
        const blob=await cardBlob();
        const file=blob?new File([blob],"prime-score.png",{type:"image/png"}):null;
        if(file&&navigator.canShare&&navigator.canShare({files:[file]})){
          await navigator.share({files:[file],title:"PRIME Score",text:shareText()});
        }else if(navigator.share){
          await navigator.share({title:"PRIME Score",text:shareText(),url:shareUrl()});
        }else{
          $("shareDownload").click();
        }
      }catch(e){if(e?.name!=="AbortError")toast(t("share_failed"))}
    };
  }

  async function refreshCard(){
    const wrap=$("shareCardWrap");
    if(!wrap)return;
    if(!lastResult){wrap.innerHTML=`<div class="status">${escapeAttr(t("share_building"))}</div>`;return;}
    wrap.innerHTML=`<div class="status">${escapeAttr(t("share_building"))}</div>`;
    try{
      const img=lastResult.photo?await loadImage(lastResult.photo).catch(()=>null):null;
      const elo=$("elo")?.textContent||lastResult.elo||"1000";
      currentCanvas=await buildCardCanvas({...lastResult,img,elo});
      const blob=await cardBlob();
      if(currentBlobUrl)URL.revokeObjectURL(currentBlobUrl);
      currentBlobUrl=blob?URL.createObjectURL(blob):currentCanvas.toDataURL("image/png");
      wrap.innerHTML=`<img id="shareCardImg" class="share-card-img" alt="PRIME card">`;
      $("shareCardImg").src=currentBlobUrl;
    }catch(e){
      console.error("PRIME card render failed",e);
      wrap.innerHTML=`<div class="status">${escapeAttr(t("share_card_failed"))}</div>`;
    }
  }

  const resultEl=$("faceResult");
  let ob=null;
  function withObserverPaused(fn){
    // render()/refreshCard() (and, on a language change, removing+rebuilding
    // the panel) write INTO this same subtree (appendChild, innerHTML), and
    // the observer below watches that subtree with subtree+characterData --
    // so without disconnecting first, every update the panel makes to itself
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
    if(ob&&resultEl)ob.observe(resultEl,{subtree:true,childList:true,characterData:true});
  }
  if(resultEl){
    ob=new MutationObserver(()=>withObserverPaused(()=>{render()}));
    ob.observe(resultEl,{subtree:true,childList:true,characterData:true});
  }
  // app.js dispatches this right after a successful analysis, carrying the
  // full data (score/tier/metrics/photo) the DOM text alone can't give us.
  document.addEventListener("prime:analysisResult",(e)=>{
    lastResult=e.detail;
    withObserverPaused(()=>{render()});
    refreshCard();
  });
  document.addEventListener("DOMContentLoaded",()=>withObserverPaused(()=>{render()}));
  setTimeout(()=>withObserverPaused(()=>{render()}),800);
  document.addEventListener("prime:langchange",()=>{
    withObserverPaused(()=>{$("primeSharePanel")?.remove();render()});
    refreshCard();
  });
})();
