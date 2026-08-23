function byId(id){return document.getElementById(id);}
const stateKey="prime_mvp_state";
const defaultState={score:72,elo:1000};
function loadState(){try{return {...defaultState,...JSON.parse(localStorage.getItem(stateKey)||"{}")} }catch(e){return {...defaultState}}}
function makeUid(){
  const stored=localStorage.getItem("prime_uid");
  if(stored)return stored;
  const generator=window.crypto&&typeof window.crypto.randomUUID==="function"?window.crypto.randomUUID.bind(window.crypto):null;
  const uid=generator?generator():`prime_${Date.now().toString(36)}_${Math.random().toString(36).slice(2,10)}`;
  localStorage.setItem("prime_uid",uid);
  return uid;
}
let state=loadState();
const uid=makeUid();
let profile=null;
let selectedFile=null,tracks=[],current=-1,audio=new Audio();

function save(){localStorage.setItem(stateKey,JSON.stringify(state))}
function toast(t){const e=document.getElementById("toast");e.textContent=t;e.classList.add("show");setTimeout(()=>e.classList.remove("show"),1700)}
function go(id){document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));document.getElementById(id).classList.add("active");document.querySelectorAll(".nav button").forEach(b=>b.classList.toggle("active",b.dataset.go===id))}
document.querySelectorAll("[data-go]").forEach(b=>b.addEventListener("click",()=>go(b.dataset.go)));

function renderHome(){document.getElementById("primeScore").textContent=state.score;document.getElementById("elo").textContent=state.elo;document.getElementById("rankLabel").textContent=state.score<50?"SUB 5":state.score<65?"MTN":state.score<75?"HTN":state.score<85?"LTN":"CHAD"}
async function syncProfile(){try{const tgUser=window.Telegram?.WebApp?.initDataUnsafe?.user;const name=tgUser?.first_name||localStorage.getItem("prime_name")||"PRIME USER";localStorage.setItem("prime_name",name);const r=await fetch(`/api/profile?id=${encodeURIComponent(uid)}&name=${encodeURIComponent(name)}`);if(!r.ok)return;profile=await r.json();state.elo=profile.elo;state.score=profile.prime_score;save();renderHome()}catch(e){}}
async function saveScoreToServer(){try{const name=localStorage.getItem("prime_name")||"PRIME USER";const r=await fetch("/api/profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:uid,name,prime_score:state.score})});if(r.ok)profile=await r.json()}catch(e){console.warn("profile sync failed",e)}}
async function leaderboard(){try{const r=await fetch("/api/leaderboard");if(!r.ok)throw Error();const rows=await r.json();let txt=rows.slice(0,8).map((x,i)=>`${i+1}. ${x.name} — ${x.elo}`).join("\n");toast(txt||"Пока никто не сыграл")}catch(e){toast("Запусти сервер PRIME")}}
function initTelegramWebApp(){
  const webApp=window.Telegram&&window.Telegram.WebApp;
  if(!webApp)return;
  if(typeof webApp.ready==="function")webApp.ready();
  if(typeof webApp.expand==="function")webApp.expand();
}
initTelegramWebApp();
renderHome();syncProfile();

document.getElementById("goFace").onclick=()=>go("face");document.getElementById("musicTop").onclick=()=>go("music");document.getElementById("menu").onclick=()=>go("home");

const input=document.getElementById("photoInput"),preview=document.getElementById("preview"),analyze=document.getElementById("analyze");
document.getElementById("pickPhoto").onclick=()=>input.click();
input.onchange=e=>{selectedFile=e.target.files[0];if(!selectedFile)return;preview.src=URL.createObjectURL(selectedFile);preview.classList.remove("hidden");analyze.disabled=false;toast("Фото готово")};

async function analyzeImageWithAI(file){
  const resized=await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>{const max=1400;const scale=Math.min(1,max/Math.max(img.width,img.height));const c=document.createElement("canvas");c.width=Math.max(1,Math.round(img.width*scale));c.height=Math.max(1,Math.round(img.height*scale));c.getContext("2d").drawImage(img,0,0,c.width,c.height);c.toBlob(blob=>blob?resolve(blob):reject(new Error("image encode failed")),"image/jpeg",0.86)};img.onerror=()=>reject(new Error("image load failed"));img.src=URL.createObjectURL(file)});
  const dataUrl=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(resized)});
  const base64=dataUrl.split(",")[1];const resp=await fetch("/api/face-ai",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({image:base64,mime:"image/jpeg"})});const result=await resp.json();if(!resp.ok)throw new Error(result.error||"AI analysis failed");return result;
}

analyze.onclick=async()=>{
  if(!selectedFile){toast("Сначала выбери фото");return} analyze.disabled=true;const status=document.getElementById("faceStatus");if(status)status.textContent="AI анализирует фото…";
  try{const r=await analyzeImageWithAI(selectedFile);state.score=Math.round(Number(r.score)||0);save();await saveScoreToServer();renderHome();
    const scoreEl=document.getElementById("faceScore");if(scoreEl)scoreEl.textContent=state.score;const typeEl=document.getElementById("type");if(typeEl)typeEl.textContent=r.type||"HTN";const textEl=document.getElementById("typeText");if(textEl)textEl.textContent=(r.summary||"AI анализ завершён.")+(r.confidence!=null?` • Confidence: ${r.confidence}/100`:"");
    const labels={symmetry:"Симметрия",proportion:"Пропорции",grooming:"Уход",hair:"Волосы",skin_appearance:"Внешний вид кожи",presentation:"Презентация"};const metrics=document.getElementById("metrics");if(metrics)metrics.innerHTML=Object.entries(r.metrics||{}).map(([k,v])=>`<div class="metric"><div class="metric-head"><b>${labels[k]||k}</b><span>${Math.round(v)}/100</span></div><div class="meter"><i style="width:${Math.max(0,Math.min(100,Number(v)||0))}%"></i></div></div>`).join("");
    const scale=document.getElementById("scalePos");if(scale)scale.style.left=`${Math.max(0,Math.min(100,state.score))}%`;const tips=document.getElementById("tips");if(tips)tips.innerHTML=(r.tips||[]).slice(0,5).map(x=>`<li>${escapeHtml(String(x))}</li>`).join("");if(status)status.textContent="AI анализ завершён.";document.getElementById("faceResult")?.classList.remove("hidden");toast(`PRIME Score: ${state.score}`);
  }catch(e){console.error(e);if(status)status.textContent="Ошибка AI: проверь GEMINI_API_KEY и сервер.";toast(e.message||"AI error")}finally{analyze.disabled=false}
};

document.getElementById("addElo").onclick=async()=>{try{const r=await fetch("/api/elo/match",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:uid})});if(!r.ok)throw Error();const x=await r.json();state.elo=x.elo;save();renderHome();toast(`${x.win?"WIN":"LOSS"} vs ${x.opponent} • ELO ${x.delta>0?"+":""}${x.delta}`);if(!x.is_bot)setTimeout(()=>toast("Рейтинг обновлён для всех игроков"),400)}catch(e){toast("Нет связи с сервером")}};

// ---------------- Per-user music ----------------
// Playlist is stored on the PRIME server and keyed by uid, not only in browser storage.
async function allTracks(){const r=await fetch(`/api/music?user_id=${encodeURIComponent(uid)}`);if(!r.ok)throw new Error("Не удалось загрузить музыку");return await r.json()}
function readAsBase64(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(",")[1]);r.onerror=reject;r.readAsDataURL(file)})}
async function addTrack(file){if(file.size>15*1024*1024)throw new Error(`${file.name}: максимум 15 МБ`);const data=await readAsBase64(file);const r=await fetch("/api/music",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({user_id:uid,name:file.name,mime:file.type||"audio/mpeg",data})});const result=await r.json();if(!r.ok)throw new Error(result.error||"Ошибка загрузки");return result}
async function delTrack(id){const r=await fetch(`/api/music/${id}`,{method:"DELETE",headers:{"Content-Type":"application/json"},body:JSON.stringify({user_id:uid})});if(!r.ok){const x=await r.json().catch(()=>({}));throw new Error(x.error||"Ошибка удаления")}}
async function renderSongs(){try{tracks=await allTracks();const box=document.getElementById("songs");box.innerHTML=tracks.length?tracks.map((t,i)=>`<div class="song"><span>▶</span><b data-i="${i}">${escapeHtml(t.name)}</b><button data-del="${t.id}">×</button></div>`).join(""):`<div class="song">Пока нет треков. Добавь свой первый трек.</div>`;box.querySelectorAll("[data-i]").forEach(b=>b.onclick=()=>playTrack(+b.dataset.i));box.querySelectorAll("[data-del]").forEach(b=>b.onclick=async()=>{try{await delTrack(+b.dataset.del);if(current===+b.dataset.del){audio.pause();audio.removeAttribute("src");current=-1}await renderSongs();toast("Трек удалён")}catch(e){toast(e.message)}})}catch(e){toast("Не удалось загрузить музыку")}}
async function playTrack(i){if(!tracks[i])return;current=tracks[i].id;try{audio.pause();const resp=await fetch(`/api/music/${tracks[i].id}?user_id=${encodeURIComponent(uid)}`);if(!resp.ok)throw new Error("Трек недоступен");const blob=await resp.blob();if(audio._objectUrl)URL.revokeObjectURL(audio._objectUrl);audio._objectUrl=URL.createObjectURL(blob);audio.src=audio._objectUrl;document.getElementById("nowPlaying").textContent=tracks[i].name;await audio.play();document.getElementById("play").textContent="Ⅱ"}catch(e){toast(e.message||"Не удалось воспроизвести трек")}}
document.getElementById("addMusic").onclick=()=>document.getElementById("musicInput").click();
document.getElementById("musicInput").onchange=async e=>{const files=[...e.target.files].filter(f=>f.type.startsWith("audio/"));if(!files.length)return;document.getElementById("addMusic").disabled=true;try{for(const f of files){toast(`Загружаю: ${f.name}`);await addTrack(f)}await renderSongs();toast("Треки сохранены в аккаунте")}catch(err){toast(err.message||"Ошибка загрузки")}finally{document.getElementById("addMusic").disabled=false;e.target.value=""}};
document.getElementById("play").onclick=async()=>{if(!audio.src){if(tracks[0])await playTrack(0);return}if(audio.paused){audio.play();document.getElementById("play").textContent="Ⅱ"}else{audio.pause();document.getElementById("play").textContent="▶"}};
document.getElementById("prev").onclick=()=>{if(!tracks.length)return;const i=Math.max(0,tracks.findIndex(t=>t.id===current));playTrack((i-1+tracks.length)%tracks.length)};
document.getElementById("next").onclick=()=>{if(!tracks.length)return;const i=Math.max(0,tracks.findIndex(t=>t.id===current));playTrack((i+1)%tracks.length)};
document.getElementById("seek").oninput=e=>{if(audio.duration)audio.currentTime=audio.duration*e.target.value/100};audio.ontimeupdate=()=>{if(audio.duration)document.getElementById("seek").value=audio.currentTime/audio.duration*100};audio.onended=()=>{if(tracks.length){const i=tracks.findIndex(t=>t.id===current);playTrack((i+1)%tracks.length)}};
function escapeHtml(s){return s.replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m]))}
renderSongs();
document.getElementById("resetAdvice").onclick=()=>toast("Принято");
document.getElementById("leaderBtn")?.addEventListener("click",leaderboard);
