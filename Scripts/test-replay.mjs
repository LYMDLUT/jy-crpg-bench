import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const {ReplayPlayer, ReplayKeys} = createRequire(import.meta.url)('../server/replay.js');

function fixture(decode = async event => event.d) {
  let now = 0, current, i = 0;
  const colors = [];
  const events = [{t:5,d:'red'}, {t:6,d:'green'}, {t:7,d:'blue'}];
  const source = {
    duration:7,
    async peek() { return events[i] || null; },
    take() { i++; },
    async seek(when) {
      i = Math.max(0, events.findLastIndex(event=>event.t<=when));
      return {at:events[i].t, held:{}};
    },
    close() { this.closed = true; },
  };
  const player = new ReplayPlayer(source, {
    now:()=>now, schedule:()=>0, cancel:()=>{}, decode, complete:()=>true,
    reset:()=>{ current=null; },
    paint:color=>{ if(color) {current=color; colors.push(color);} },
    update:()=>{}, error:error=>{ throw error; },
  });
  return {player,source,colors, color:()=>current, advance:ms=>{now+=ms;}};
}

test('starts with the first picture at zero and pause/resume reanchors the clock', async () => {
  const f = fixture();
  await f.player.start();
  f.player.setSpeed(1);
  assert.equal(f.color(),'red');
  assert.equal(f.player.position,0);
  f.advance(500); await f.player.tick();
  await f.player.pause();
  f.advance(30000); await f.player.tick();
  assert.equal(f.color(),'red');
  assert.equal(f.player.position,.5);
  f.player.play(); f.advance(600); await f.player.tick();
  assert.equal(f.color(),'green');
  assert.ok(Math.abs(f.player.position-1.1)<1e-9);
  f.player.close();
});

test('forward and backward seeks repaint their target and keep an ended recording reusable', async () => {
  const f=fixture(); await f.player.start(); await f.player.pause();
  await f.player.seek(1.5); assert.equal(f.color(),'green');
  await f.player.seek(0); assert.equal(f.color(),'red');
  await f.player.seek(2); assert.equal(f.color(),'blue');
  assert.equal(f.player.wantPlaying,false);
  await f.player.play(); assert.equal(f.color(),'red');
  assert.equal(f.player.position,0);
  assert.equal(f.source.closed,undefined);
  f.player.close(); assert.equal(f.source.closed,true);
});

test('a slow old seek cannot paint after a newer seek', async () => {
  let release, began;
  const started = new Promise(resolve=>{began=resolve;});
  const delayed = new Promise(resolve=>{release=resolve;});
  const f=fixture(async event=>{
    if(event.d==='green') {began(); await delayed;}
    return event.d;
  });
  await f.player.start(); await f.player.pause();
  const old=f.player.seek(1);
  await started;
  const newest=f.player.seek(0);
  release(); await Promise.all([old,newest]);
  assert.equal(f.color(),'red');
  assert.deepEqual(f.colors,['red','red']);
  f.player.close();
});

test('closing during decode releases the source and prevents a late frame', async () => {
  let release, began;
  const started=new Promise(resolve=>{began=resolve;});
  const delayed=new Promise(resolve=>{release=resolve;});
  const f=fixture(async event=>{
    if(event.d==='green') {began(); await delayed;}
    return event.d;
  });
  await f.player.start(); await f.player.pause();
  const pending=f.player.seek(1);
  await started; f.player.close(); release(); await pending;
  assert.equal(f.source.closed,true);
  assert.deepEqual(f.colors,['red']);
});

test('a seek during the first decode cannot discard the recording origin', async () => {
  let release, began;
  const started = new Promise(resolve=>{began=resolve;});
  const delayed = new Promise(resolve=>{release=resolve;});
  const f = fixture(async event=>{
    if (event.d==='red') { began(); await delayed; }
    return event.d;
  });
  const states = [];
  f.player.update = state=>states.push(state);
  const opening = f.player.start();
  await started;
  assert.equal(states.at(-1).ready, false);
  assert.equal(states.at(-1).loading, true);
  await f.player.seek(1.5);
  release(); await opening;
  assert.equal(f.player.origin, 5);
  assert.equal(f.player.duration, 2);
  assert.equal(f.player.position, 0);
  assert.equal(f.color(), 'red');
  assert.equal(states.at(-1).ready, true);
  assert.equal(states.at(-1).loading, false);
  await f.player.pause();
  await f.player.seek(1.5);
  assert.equal(f.color(), 'green');
  f.player.close();
});

test('pausing during the first decode stays paused once its picture arrives', async () => {
  let release, began;
  const started = new Promise(resolve=>{began=resolve;});
  const delayed = new Promise(resolve=>{release=resolve;});
  const f = fixture(async event=>{ began(); await delayed; return event.d; });
  const opening = f.player.start();
  await started; await f.player.pause();
  release(); await opening;
  assert.equal(f.color(), 'red');
  assert.equal(f.player.position, 0);
  assert.equal(f.player.playing, false);
  assert.equal(f.player.wantPlaying, false);
  f.player.close();
});

test('seek snapshots and later key events retain actor names and styled key chips', () => {
  const container = {
    children: [],
    ownerDocument: {createElement:()=>({style:{}})},
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
  };
  const keys = new ReplayKeys(container, {
    glyphs:{up:'↗',enter:'⏎'}, arrows:new Set(['up']),
    colorOf:actor=>actor==='agent-a' ? '#abcdef' : '#123456',
  });
  const labels = ()=>container.children.map(child=>child.textContent);
  keys.reset({up:'agent-a', enter:'agent-b'});
  assert.deepEqual(labels(), ['agent-a','↗','agent-b','⏎']);
  assert.equal(container.children[0].style.color, '#abcdef');
  assert.equal(container.children[1].className, 'k arrow');
  assert.equal(container.children[2].style.color, '#123456');
  assert.equal(container.children[3].className, 'k');
  keys.apply({key:'up',down:false,who:'agent-a'});
  assert.deepEqual(labels(), ['agent-b','⏎','agent-a']);
  keys.apply({key:'space',down:true,who:'<operator>'});
  assert.deepEqual(labels(), ['agent-b','⏎','<operator>','space']);
  keys.reset({});
  assert.deepEqual(labels(), []);
});

test('default browser timers are not invoked with the player as their receiver', async () => {
  const originalSet=globalThis.setTimeout, originalClear=globalThis.clearTimeout;
  function browserTimer() {
    assert.ok(this===undefined || this===globalThis, 'Window timer called with an invalid receiver');
    return 1;
  }
  globalThis.setTimeout=browserTimer; globalThis.clearTimeout=browserTimer;
  try {
    const f=fixture();
    const player=new ReplayPlayer(f.source, {decode:async e=>e.d,paint:()=>{},
      complete:()=>true,reset:()=>{},update:()=>{},error:e=>{throw e;}});
    await player.start(); await player.pause(); player.close();
  } finally {
    globalThis.setTimeout=originalSet; globalThis.clearTimeout=originalClear;
  }
});

function deferred() {
  let resolve;
  const promise = new Promise(done=>{ resolve=done; });
  return {promise, resolve};
}

function replayDOM() {
  const elements = new Map();
  const document = {
    activeElement: null,
    listeners: {},
    addEventListener(type, listener) { (this.listeners[type] ??= []).push(listener); },
    createElement: tag=>new Element(tag),
    createTextNode: text=>Object.assign(new Element('#text'), {textContent:text}),
    createDocumentFragment: ()=>new Element('#fragment'),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element(id==='vcv' ? 'canvas' : 'div'));
      return elements.get(id);
    },
  };
  class Element {
    constructor(tag) {
      this.tagName=tag.toUpperCase(); this.children=[]; this.style={};
      this.ownerDocument=document; this.attributes={}; this.listeners={};
      this.width=320; this.height=200; this.open=false; this._text='';
      const classes=new Set();
      this.classList={add:name=>classes.add(name), remove:name=>classes.delete(name),
        contains:name=>classes.has(name)};
    }
    get textContent() { return this._text + this.children.map(child=>child.textContent).join(''); }
    set textContent(text) { this._text=String(text); this.children=[]; }
    set innerHTML(_value) { throw new Error('Recording metadata must use text nodes, not HTML'); }
    appendChild(child) { this.children.push(child); child.parentNode=this; return child; }
    append(...children) {
      for (const child of children) this.appendChild(typeof child==='string' ? document.createTextNode(child) : child);
    }
    replaceChildren(...children) { this.children=[]; this._text=''; this.append(...children); }
    setAttribute(name, value) { this.attributes[name]=String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    getAttribute(name) { return this.attributes[name] ?? null; }
    addEventListener(type, listener) { (this.listeners[type] ??= []).push(listener); }
    async dispatch(type) {
      const event={type, target:this};
      for (const listener of this.listeners[type] || []) await listener(event);
      await this['on'+type]?.(event);
    }
    focus() { document.activeElement=this; this.focusCalls=(this.focusCalls || 0)+1; }
    getContext() { return {fillRect(){}}; }
  }
  return {document, elements};
}

function namedHTMLFunction(html, name) {
  const start=html.indexOf('async function '+name+'(');
  assert.notEqual(start, -1, 'Missing real HTML function '+name);
  const end=html.indexOf('\n}', start);
  assert.notEqual(end, -1, 'Missing function terminator for '+name);
  return html.slice(start, end+2);
}

test('opening a replay twice pins one reader, focuses close, and can reopen during a pending open', async () => {
  const html=readFileSync(new URL('../server/index.html', import.meta.url), 'utf8');
  const begin=html.indexOf('const vcr = document.getElementById("vcr")');
  const end=html.indexOf('// ---- export the recording', begin);
  assert.ok(begin>=0 && end>begin, 'Real playback initialization must be present');
  const dom=replayDOM(), opens=[], players=[];
  const context=vm.createContext({document:dom.document, addEventListener(){},
    ReplayKeys, GLYPH:{}, ARROW:new Set(), colorOf:()=>'',
    ReplayRecording:{open(name) {
      const pending=deferred(); opens.push({name,...pending}); return pending.promise;
    }},
    ReplayPlayer:class {
      constructor(source) { this.source=source; players.push(this); }
      async start() {}
      close() { this.source.close(); }
    },
  });
  const playBinding=html.match(/^playBtn\.onclick = .*;$/m);
  assert.ok(playBinding, 'The Play button must bind the named playback entry point');
  vm.runInContext(html.slice(begin,end)+'\n'+namedHTMLFunction(html,'openPlayback')+'\n'+playBinding[0], context);
  const first=dom.document.getElementById('play').onclick({type:'click'});
  assert.equal(opens.length,1);
  assert.equal(opens[0].name,'current');
  assert.equal(dom.document.activeElement,dom.document.getElementById('vcrclose'));
  await context.openPlayback('archive-ignored.jsonl');
  assert.equal(opens.length,1,'Opening while the first request is pending must not pin a second reader');
  context.vcrClose();
  const reopened=context.openPlayback('archive-selected.jsonl');
  assert.equal(opens.length,2);
  assert.equal(opens[1].name,'archive-selected.jsonl');
  const obsolete={closeCalls:0,close(){this.closeCalls++;}};
  opens[0].resolve(obsolete); await first;
  assert.equal(obsolete.closeCalls,1);
  assert.equal(players.length,0,'A reader arriving after close must never start painting');
  const active={closeCalls:0,close(){this.closeCalls++;}};
  opens[1].resolve(active); await reopened;
  assert.equal(players.length,1);
  assert.equal(players[0].source,active);
  assert.equal(dom.document.getElementById('vcr').classList.contains('on'),true);
  context.vcrClose();
  assert.ok(active.closeCalls>=1);
});

test('archive selection is sent once and page, seek, keepalive, and close keep the pinned token', async () => {
  const code=readFileSync(new URL('../server/recording.js', import.meta.url), 'utf8');
  const requests=[], timers=[];
  const context=vm.createContext({module:{exports:{}}, URLSearchParams, AbortController, AbortSignal,
    setInterval:callback=>{timers.push(callback); return timers.length;}, clearInterval(){},
    setTimeout, clearTimeout,
    fetch:async (url, options)=>{
      requests.push({url,options});
      const query=new URL(url,'http://localhost/u/test/').searchParams;
      const page={token:'pinned-archive',duration:12,seek_supported:true,next:200,
        events:query.has('start') ? [{t:3,d:'next-page'}] : [{t:1,d:'first-page'}],
        done:query.has('start'), ...(query.has('time') ? {seek:{at:6,held:{}}} : {})};
      return {ok:true,json:async()=>page};
    },
  });
  vm.runInContext(code,context);
  const {ReplayRecording}=context.module.exports;
  assert.equal(typeof ReplayRecording,'function');
  const name='20260909-183000-abcdef012345.jsonl';
  const source=await ReplayRecording.open(name);
  assert.equal((await source.peek()).d,'first-page');
  source.take();
  assert.equal((await source.peek()).d,'next-page');
  await source.seek(6);
  await timers[0]();
  source.close();
  await Promise.resolve();
  const queries=requests.map(({url})=>new URL(url,'http://localhost/u/test/').searchParams);
  assert.equal(queries[0].get('recording'),name);
  assert.equal(queries[0].has('token'),false);
  for (const query of queries.slice(1)) {
    assert.equal(query.has('recording'),false,'Subsequent requests must address the pinned reader, not reselect a file');
    assert.equal(query.get('token'),'pinned-archive');
  }
  assert.ok(queries.some(query=>query.get('start')==='200'));
  assert.ok(queries.some(query=>query.get('time')==='6'));
  assert.ok(queries.some(query=>query.get('touch')==='1'));
  assert.ok(queries.some(query=>query.get('close')==='1'));
  assert.equal(requests.at(-1).options.signal,undefined,'Closing a reader must not use its aborted playback signal');
});

test('the recordings menu loads lazily and offers safe downloads and playback for current and archived files', async () => {
  const html=readFileSync(new URL('../server/index.html', import.meta.url),'utf8');
  assert.match(html, /<details id="recordingfiles">[\s\S]*?<div id="recordinglinks">/);
  const begin=html.indexOf('// ---- recording files ');
  const end=html.indexOf('// ---- live connection ',begin);
  assert.ok(begin>=0 && end>begin, 'Real recording menu initialization must be present');
  const dom=replayDOM(), requests=[], opened=[];
  const files=[
    {id:'current',name:'recording.jsonl',bytes:1048576},
    {id:'20260909-183000-abcdef012345.jsonl',name:'20260909-183000-abcdef012345.jsonl',bytes:2097152},
    {id:'special /?&#.jsonl',name:'<img src=x onerror=alert(1)>.jsonl',bytes:0},
  ];
  const context=vm.createContext({document:dom.document, addEventListener(){},
    openPlayback:id=>opened.push(id),
    fetch:async (url,options)=>{ requests.push({url,options}); return {ok:true,json:async()=>({files})}; },
  });
  vm.runInContext(html.slice(begin,end),context);
  const details=dom.document.getElementById('recordingfiles');
  const links=dom.document.getElementById('recordinglinks');
  assert.equal(requests.length,0);
  await details.dispatch('toggle');
  assert.equal(requests.length,0,'A closed menu must not fetch the list');
  details.open=true;
  await details.dispatch('toggle');
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,'api/recordings');
  assert.equal(requests[0].options.cache,'no-store');
  assert.equal(links.children.length,files.length);
  for (const [index,file] of files.entries()) {
    const row=links.children[index];
    assert.equal(row.tagName,'DIV');
    const label=row.children.find(child=>child.tagName==='SPAN');
    const download=row.children.find(child=>child.tagName==='A');
    const play=row.children.find(child=>child.tagName==='BUTTON');
    assert.ok(label && download && play);
    assert.equal(download.href,'api/recordings/'+encodeURIComponent(file.id));
    assert.equal(download.download,file.name);
    if (file.id==='current') assert.match(label.textContent,/当前录像/);
    else assert.ok(label.textContent.includes(file.name.replace(/\.jsonl$/,'')));
    assert.equal(label.children.length,0,'Recording names must stay inert text');
    details.open=true;
    await play.dispatch('click');
    assert.equal(details.open,false);
    assert.equal(opened.at(-1),file.id);
  }
  assert.deepEqual(opened,files.map(file=>file.id));
});

test('reopening the recordings menu ignores an older list response and reports unsupported servers', async () => {
  const html=readFileSync(new URL('../server/index.html', import.meta.url),'utf8');
  const begin=html.indexOf('// ---- recording files ');
  const end=html.indexOf('// ---- live connection ',begin);
  const dom=replayDOM(), pending=[];
  const context=vm.createContext({document:dom.document, addEventListener(){}, openPlayback(){},
    fetch:()=>{ const request=deferred(); pending.push(request); return request.promise; },
  });
  vm.runInContext(html.slice(begin,end),context);
  const details=dom.document.getElementById('recordingfiles');
  const links=dom.document.getElementById('recordinglinks');
  details.open=true;
  const old=details.dispatch('toggle');
  details.open=false;
  await details.dispatch('toggle');
  details.open=true;
  const fresh=details.dispatch('toggle');
  const response=name=>({ok:true,json:async()=>({files:[{id:name,name,bytes:1}]})});
  pending[1].resolve(response('fresh.jsonl'));
  await fresh;
  assert.match(links.textContent,/fresh/);
  pending[0].resolve(response('obsolete.jsonl'));
  await old;
  assert.match(links.textContent,/fresh/);
  assert.doesNotMatch(links.textContent,/obsolete/);
  details.open=false;
  await details.dispatch('toggle');
  details.open=true;
  const missing=details.dispatch('toggle');
  pending[2].resolve({ok:false,status:404});
  await missing;
  assert.match(links.textContent,/暂不支持录像列表/);
});
