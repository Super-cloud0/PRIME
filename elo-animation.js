(() => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const esc = s => String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  const style = document.createElement('style');
  style.textContent = `
    .prime-elo-overlay{position:fixed;inset:0;z-index:99999;background:radial-gradient(circle at center,#181818 0,#050505 70%);display:flex;align-items:center;justify-content:center;padding:16px;opacity:0;animation:primeEloIn .25s ease forwards}
    .prime-elo-arena{width:min(760px,100%);text-align:center;color:#fff}.prime-elo-kicker{font-size:11px;letter-spacing:4px;color:#888;margin-bottom:18px}
    .prime-elo-fighters{display:grid;grid-template-columns:1fr 74px 1fr;gap:12px;align-items:center}.prime-elo-card{background:#101010;border:1px solid #2b2b2b;border-radius:22px;padding:12px;box-shadow:0 15px 55px #0008;transition:transform .55s cubic-bezier(.2,.8,.2,1),box-shadow .45s}
    .prime-elo-card img{display:block;width:100%;aspect-ratio:1;object-fit:cover;border-radius:15px;background:#191919}.prime-elo-name{font-weight:900;margin-top:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.prime-elo-rating{font-size:12px;color:#777;margin-top:4px}
    .prime-elo-vs{font-size:30px;font-weight:1000}.prime-elo-count{font-size:60px;font-weight:1000;min-height:70px;line-height:1}.prime-elo-status{font-size:12px;letter-spacing:2px;color:#777;margin-top:5px}.prime-elo-result{font-size:28px;font-weight:1000;margin-top:22px;min-height:36px}.prime-elo-delta{font-size:18px;margin-top:7px}.prime-elo-reason{font-size:13px;color:#999;line-height:1.45;max-width:560px;margin:10px auto}.prime-elo-close{border:1px solid #444;background:#151515;color:#fff;border-radius:14px;padding:12px 25px;font-weight:800;margin-top:12px}
    .prime-elo-fighters.fight .prime-elo-card:first-child{transform:translateX(25px) scale(1.03)}.prime-elo-fighters.fight .prime-elo-card:last-child{transform:translateX(-25px) scale(1.03)}.prime-elo-fighters.win-a .prime-elo-card:first-child{box-shadow:0 0 0 2px #fff,0 0 55px #fff3}.prime-elo-fighters.win-b .prime-elo-card:last-child{box-shadow:0 0 0 2px #fff,0 0 55px #fff3}
    .prime-elo-count.pulse{animation:primeEloPulse .42s ease 3}@keyframes primeEloIn{to{opacity:1}}@keyframes primeEloPulse{50%{transform:scale(1.15);opacity:.65}}
    @media(max-width:560px){.prime-elo-fighters{grid-template-columns:1fr 42px 1fr}.prime-elo-vs{font-size:22px}.prime-elo-count{font-size:48px}.prime-elo-name{font-size:13px}}
  `;
  document.head.appendChild(style);

  function overlay(){
    const o=document.createElement('div');o.className='prime-elo-overlay';
    o.innerHTML=`<div class="prime-elo-arena"><div class="prime-elo-kicker">PRIME ELO ARENA</div><div class="prime-elo-fighters" id="primeEloFighters"><div class="prime-elo-card"><img id="primeEloMe" alt="YOU"><div class="prime-elo-name" id="primeEloMeName">YOU</div><div class="prime-elo-rating" id="primeEloMeRating">ELO —</div></div><div><div class="prime-elo-vs">VS</div><div class="prime-elo-count" id="primeEloCount">3</div><div class="prime-elo-status">MATCH</div></div><div class="prime-elo-card"><img id="primeEloOpp" alt="OPPONENT"><div class="prime-elo-name" id="primeEloOppName">OPPONENT</div><div class="prime-elo-rating" id="primeEloOppRating">ELO —</div></div></div><div class="prime-elo-result" id="primeEloResult">FINDING OPPONENT…</div><div class="prime-elo-delta" id="primeEloDelta"></div><div class="prime-elo-reason" id="primeEloReason"></div><button class="prime-elo-close" id="primeEloClose">CLOSE</button></div>`;
    document.body.appendChild(o);return o;
  }
  async function run(){
    const old=document.getElementById('primeEloOverlay');if(old)old.remove();
    const o=overlay();o.id='primeEloOverlay';const q=id=>o.querySelector('#'+id);const close=()=>o.remove();q('primeEloClose').onclick=close;
    const selected=document.getElementById('photoInput')?.files?.[0];
    if(selected)q('primeEloMe').src=URL.createObjectURL(selected);
    const score=document.getElementById('primeScore')?.textContent||'—';q('primeEloMeRating').textContent=`ELO ${document.getElementById('elo')?.textContent||1000} · SCORE ${score}`;
    try{
      await sleep(500);q('primeEloResult').textContent='FINDING OPPONENT…';
      await sleep(500);q('primeEloCount').textContent='3';await sleep(500);q('primeEloCount').textContent='2';await sleep(500);q('primeEloCount').textContent='1';await sleep(400);q('primeEloCount').textContent='⚡';q('primeEloCount').classList.add('pulse');
      const uid=localStorage.getItem('prime_uid');
      const r=await fetch('/api/elo/match',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:uid})});
      const x=await r.json();if(!r.ok)throw new Error(x.error||'ELO match failed');
      q('primeEloOppName').textContent=x.opponent||'OPPONENT';q('primeEloOppRating').textContent=`ELO ${x.opponent_elo??'—'}`;
      q('primeEloOpp').src='data:image/svg+xml;charset=UTF-8,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600"><rect width="100%" height="100%" fill="#191919"/><text x="50%" y="52%" dominant-baseline="middle" text-anchor="middle" fill="#777" font-size="65">PRIME</text></svg>`);
      q('primeEloFighters').classList.add('fight');q('primeEloResult').textContent='AI / ELO RESULT';await sleep(700);
      const win=!!x.win;q('primeEloFighters').classList.add(win?'win-a':'win-b');q('primeEloResult').textContent=win?'YOU WIN':'YOU LOSE';q('primeEloDelta').textContent=`${x.delta>0?'+':''}${x.delta} ELO  →  ${x.elo}`;q('primeEloReason').textContent='Рейтинг обновлён по результату матча.';
      document.getElementById('elo').textContent=x.elo;document.getElementById('primeScore')?.textContent;
    }catch(e){q('primeEloResult').textContent=e.message||'ELO ERROR';q('primeEloReason').textContent='Попробуй ещё раз после появления второго участника.';}
  }
  document.addEventListener('DOMContentLoaded',()=>{const b=document.getElementById('addElo');if(b)b.onclick=run;});
})();
