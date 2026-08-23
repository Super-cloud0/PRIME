const fs = require('fs');
const vm = require('vm');

class ClassList {
  constructor(el){ this.el = el; this.items = new Set((el.className || '').split(/\s+/).filter(Boolean)); }
  add(...names){ names.forEach(n => this.items.add(n)); this.el.className = [...this.items].join(' '); }
  remove(...names){ names.forEach(n => this.items.delete(n)); this.el.className = [...this.items].join(' '); }
  contains(name){ return this.items.has(name); }
  toggle(name, force){ const on = force === undefined ? !this.items.has(name) : !!force; on ? this.add(name) : this.remove(name); return on; }
}
class Element {
  constructor(tag, attrs = {}){ this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.style = {}; this.eventHandlers = {}; this.textContent = ''; this.innerHTML = ''; this.disabled = false; this.files = []; Object.entries(attrs).forEach(([k,v]) => this.setAttribute(k,v)); this.classList = new ClassList(this); }
  setAttribute(k,v){ if(k === 'id') this.id = v; else if(k === 'class') this.className = v; else if(k.startsWith('data-')) this.dataset[k.slice(5).replace(/-([a-z])/g, (_,c)=>c.toUpperCase())] = v; else this[k] = v; }
  appendChild(c){ this.children.push(c); return c; }
  addEventListener(type, fn){ this.eventHandlers[type] = this.eventHandlers[type] || []; this.eventHandlers[type].push(fn); }
  click(){ if(typeof this.onclick === 'function') this.onclick({target:this}); (this.eventHandlers.click || []).forEach(fn => fn({target:this})); }
  querySelectorAll(selector){ return document.querySelectorAll(selector, this); }
  querySelector(selector){ return this.querySelectorAll(selector)[0] || null; }
}
function walk(root, out=[]){ out.push(root); root.children.forEach(c => walk(c, out)); return out; }
const document = {
  elements: {}, all: [], body: new Element('body'), head: new Element('head'),
  createElement(tag){ return new Element(tag); },
  getElementById(id){ return this.elements[id] || null; },
  addEventListener(type, fn){ if(type === 'DOMContentLoaded') setImmediate(fn); },
  querySelectorAll(selector, root){
    const nodes = (root ? walk(root, []) : this.all);
    if(selector === '.view') return nodes.filter(e => (e.classList && e.classList.contains('view')));
    if(selector === '.nav button') return nodes.filter(e => e.tagName === 'BUTTON' && e.parent && e.parent.classList && e.parent.classList.contains('nav'));
    if(selector === '[data-go]') return nodes.filter(e => e.dataset && e.dataset.go);
    if(selector === '[data-i]' || selector === '[data-del]') return [];
    return [];
  }
};
function add(tag, attrs, parent=document.body){ const e = new Element(tag, attrs); e.parent = parent; parent.appendChild(e); document.all.push(e); if(e.id) document.elements[e.id] = e; return e; }
['home','face','music','advice'].forEach((id,i) => add('main', {id, class:`view ${i===0?'active':''}`}));
const nav = add('nav', {class:'nav'});
['home','face','music','advice'].forEach(id => add('button', {'data-go':id, class:id==='home'?'active':''}, nav));
['menu','musicTop','goFace','pickPhoto','analyze','addElo','addMusic','play','prev','next','resetAdvice','leaderBtn'].forEach(id => add('button', {id}));
['primeScore','elo','rankLabel','toast','faceStatus','faceResult','faceScore','type','typeText','metrics','scalePos','tips','songs','nowPlaying'].forEach(id => add('div', {id}));
['photoInput','musicInput','seek'].forEach(id => add('input', {id}));
add('img', {id:'preview', class:'hidden'});
const storage = new Map();
const context = { document, window:{}, localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,String(v))}, Audio:function(){}, Image:function(){}, URL:{createObjectURL:()=>'',revokeObjectURL:()=>{}}, FileReader:function(){}, fetch: async (url) => ({ok:true,json:async()=>String(url).startsWith('/api/leaderboard')?[]:{elo:1000,prime_score:72},blob:async()=>({})}), setTimeout, setImmediate, console, Math, Date };
context.window = context;
context.crypto = {}; // Reproduce Telegram/WebView environments without crypto.randomUUID.
vm.createContext(context);
vm.runInContext(fs.readFileSync('app.js','utf8'), context);
function active(){ return document.querySelectorAll('.view').find(v => v.classList.contains('active')).id; }
[['goFace','face'],['musicTop','music'],['menu','home']].forEach(([id, expected]) => { document.getElementById(id).click(); if(active() !== expected) throw new Error(`${id} did not navigate to ${expected}`); });
for (const target of ['face','music','advice']) { document.querySelectorAll('[data-go]').find(b => b.dataset.go === target).click(); if(active() !== target) throw new Error(`Home -> ${target} failed`); document.querySelectorAll('[data-go]').find(b => b.dataset.go === 'home').click(); if(active() !== 'home') throw new Error(`Back from ${target} failed`); }
document.getElementById('leaderBtn').click();
console.log('frontend smoke passed');
