import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const {ReplayPlayer, ActionReplayPlayer, ReplayKeys} = createRequire(import.meta.url)('../server/replay.js');

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
    getContext() { const canvas=this; return {fillRect(){},drawImage(image){canvas.image=image;}}; }
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
  const context=vm.createContext({document:dom.document, addEventListener(){}, AbortController,
    ReplayKeys, GLYPH:{}, ARROW:new Set(), colorOf:()=>'',
    StepReplaySource:{open(name) {
      const pending=deferred(); opens.push({name,...pending}); return pending.promise;
    }},
    ActionReplayPlayer:class {
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

function actionFixture({count=3, frame=async index=>({index})} = {}) {
  let now=0, timer, current;
  const pictures=[], states=[], prefetched=[];
  const source={steps:count, duration:113*3600,
    step:async index=>({t:index*3600,who:index%2 ? 'agent-b' : 'agent-a',act:'KEY',on:'up'}),
    frame,
    prefetch(index,signal) { prefetched.push({index,signal}); },
    close() {this.closed=true;},
  };
  const player=new ActionReplayPlayer(source, {
    now:()=>now,
    schedule:(callback,delay)=>{ timer={callback,delay}; return timer; },
    cancel:handle=>{ if(handle===timer) timer=null; },
    paint:(image,step)=>{ current=image.index; pictures.push({index:image.index,step}); },
    update:state=>states.push(state), error:error=>{throw error;},
  });
  return {source,player,pictures,states,prefetched,advance:ms=>{now+=ms;},
    current:()=>current, timer:()=>timer};
}

test('action playback starts immediately and maps 10820 actions to 27 minutes at 4x, independent of wall time', async () => {
  const f=actionFixture({count:10820});
  await f.player.start();
  assert.equal(f.current(),0);
  assert.equal(f.player.duration/4,1623);
  assert.equal(f.timer().delay,150);
  assert.equal(f.states.at(-1).step.t,0);
  f.advance(150); await f.player.tick();
  assert.equal(f.current(),1);
  assert.equal(f.states.at(-1).step.t,3600);
  assert.equal(f.states.at(-1).step.who,'agent-b');
  f.player.pause();
  for (const index of [127,128,9000,1,0,10819]) {
    await f.player.seek(index*.6);
    assert.equal(f.current(),index);
    assert.equal(f.player.wantPlaying,false);
  }
  await f.player.seek(f.player.duration);
  assert.equal(f.current(),10819);
  assert.equal(f.player.wantPlaying,false);
  await f.player.play();
  assert.equal(f.current(),0);
  f.player.close();
});

test('action pause and speed changes preserve the displayed action and its remaining hold time', async () => {
  const f=actionFixture(); await f.player.start();
  f.advance(50); f.player.pause();
  assert.ok(Math.abs(f.player.position-.2)<1e-9);
  f.advance(90000); await f.player.tick();
  assert.equal(f.current(),0);
  f.player.setSpeed(2); f.player.play();
  assert.ok(Math.abs(f.timer().delay-200)<1e-9);
  f.advance(200); await f.player.tick();
  assert.equal(f.current(),1);
  assert.ok(Math.abs(f.timer().delay-300)<1e-9);
  f.player.close(); assert.equal(f.source.closed,true);
});

test('slow action frames do not skip actions and pausing during a pending frame remains paused', async () => {
  const wait=deferred(), began=deferred();
  const f=actionFixture({frame:async index=>{
    if(index===1) {began.resolve(); await wait.promise;}
    return {index};
  }});
  await f.player.start();
  f.advance(150); const pending=f.player.tick(); await began.promise;
  f.advance(900000); f.player.pause();
  assert.equal(f.current(),0);
  wait.resolve(); await pending;
  assert.equal(f.current(),0,'A paused viewer must keep its last visible picture');
  assert.equal(f.player.playing,false);
  assert.equal(f.player.wantPlaying,false);
  assert.equal(f.player.position,.6);
  f.player.play(); assert.equal(f.timer().delay,0);
  await f.player.tick(); assert.equal(f.current(),1);
  assert.equal(f.timer().delay,150);
  f.player.close();
});

test('a new action seek paints without waiting for a slow obsolete seek, which is aborted and cannot overwrite it', async () => {
  const wait=deferred(), began=deferred(); let oldSignal;
  const f=actionFixture({frame:async (index,signal)=>{
    if(index===1) {oldSignal=signal; began.resolve(); await wait.promise;}
    return {index};
  }});
  await f.player.start(); f.player.pause();
  const stale=f.player.seek(.6); await began.promise;
  await f.player.seek(1.2);
  assert.equal(oldSignal.aborted,true);
  assert.equal(f.current(),2,'The latest request must not queue behind a stale decode');
  wait.resolve(); await stale;
  assert.deepEqual(f.pictures.map(p=>p.index),[0,2]);
  f.player.close();
});

test('closing or pausing during the first action frame never causes a late autoplay', async () => {
  for (const close of [false,true]) {
    const wait=deferred(), began=deferred();
    const f=actionFixture({frame:async index=>{began.resolve(); await wait.promise; return {index};}});
    const opening=f.player.start(); await began.promise;
    if(close) f.player.close(); else f.player.pause();
    await f.player.seek(1.2);
    wait.resolve(); await opening;
    assert.equal(f.player.wantPlaying,false);
    assert.equal(f.player.playing,false);
    assert.equal(f.current(),close ? undefined : 0);
    f.player.close();
  }
});

test('action playback holds the last frame before stopping and restarts from the first frame', async () => {
  const f=actionFixture({count:1}); await f.player.start();
  assert.equal(f.player.wantPlaying,true);
  assert.equal(f.timer().delay,150);
  f.advance(150); await f.player.tick();
  assert.equal(f.player.position,.6);
  assert.equal(f.player.wantPlaying,false);
  assert.equal(f.source.closed,undefined);
  await f.player.play(); assert.equal(f.current(),0);
  assert.equal(f.player.position,0);
  assert.equal(f.player.wantPlaying,true);
  f.player.close();
});

test('action key display preserves actor switches, repeated keys, arrows, and failed actions', () => {
  const dom=replayDOM(), container=dom.document.getElementById('keys');
  const keys=new ReplayKeys(container,{glyphs:{up:'↗',enter:'⏎'},arrows:new Set(['up']),colorOf:who=>who});
  keys.showStep({who:'agent-a',act:'KEYS',on:'up up enter'});
  assert.deepEqual(container.children.map(x=>x.textContent),['agent-a','↗','↗','⏎']);
  assert.equal(container.children[1].className,'k arrow');
  keys.showStep({who:'agent-b',act:'WAIT',on:'100',ok:false});
  assert.deepEqual(container.children.map(x=>x.textContent),['agent-b','等待',' · 未执行 / 失败']);
  keys.showStep({who:'<img>',act:'GET'});
  assert.equal(container.children[0].textContent,'<img>');
  assert.equal(container.children[0].children.length,0);
});

function stepSourceVM(fetch, extra={}) {
  const requests=[], intervals=[], pictures=[], disposed=[];
  const context=vm.createContext({module:{exports:{}}, URL, URLSearchParams, AbortController, AbortSignal,
    setTimeout:(callback)=>setTimeout(callback,0),clearTimeout,
    setInterval:callback=>{intervals.push(callback); return intervals.length;},clearInterval(){},
    createImageBitmap:async blob=>{
      const image={index:blob.index,close(){disposed.push(this.index);}};
      pictures.push(image); return image;
    },
    fetch:async (url,options={})=>{
      requests.push({url,options});
      return fetch(new URL(url,'http://local/u/test/'),options);
    }, ...extra});
  vm.runInContext(readFileSync(new URL('../server/recording.js',import.meta.url),'utf8'),context);
  return {Source:context.module.exports.StepReplaySource,requests,intervals,pictures,disposed};
}
const jsonReply = (body,status=200)=>({ok:status<400,status,json:async()=>body});
function stepResponse(url) {
  const number=Number(url.searchParams.get('step'));
  if(url.pathname.endsWith('/frame')) return {ok:true,status:200,blob:async()=>({index:number})};
  if(url.pathname.endsWith('/steps')) {
    const start=Number(url.searchParams.get('start'));
    return jsonReply({start,total:10820,steps:Array.from({length:128},(_,offset)=>({t:(start+offset)*3600,act:'KEY',on:'up'}))});
  }
  return jsonReply({token:'pinned-archive',steps:10820,duration:113*3600});
}

test('action source polls one pinned archive, pages 128 steps, caches four pictures, and deletes its token', async () => {
  let opening=true;
  const f=stepSourceVM(url=>{
    if(opening) {opening=false; return jsonReply({token:'pinned-archive',indexing:true,scanned:1,total:2},202);}
    return stepResponse(url);
  });
  const progress=[];
  const source=await f.Source.open('archive &?.jsonl',{progress:meta=>progress.push(meta)});
  assert.equal(progress.length,1);
  assert.equal(source.steps,10820);
  assert.equal(new URL(f.requests[0].url,'http://local/').searchParams.get('recording'),'archive &?.jsonl');
  for(const number of [0,127,128,256,128]) await source.step(number);
  const pages=f.requests.filter(r=>r.url.includes('/steps')).map(r=>new URL(r.url,'http://local/'));
  assert.deepEqual(pages.map(url=>url.searchParams.get('start')),['0','128','256']);
  assert.ok(pages.every(url=>url.searchParams.get('count')==='128'));
  assert.equal(source.pages.size,2);
  for(let number=0;number<6;number++) await source.frame(number);
  assert.equal(source.frames.size,4);
  assert.deepEqual(f.disposed,[0,1]);
  const count=f.requests.length; await source.frame(5);
  assert.equal(f.requests.length,count);
  await f.intervals[0](); source.close();
  assert.equal(f.requests.at(-1).options.method,'DELETE');
  assert.equal(f.requests.at(-1).options.signal,undefined);
  assert.equal(f.disposed.length,6);
  assert.equal(source.frames.size,0);
  assert.ok(f.requests.slice(1).every(r=>r.url.startsWith('api/replay/pinned-archive')));
});

test('action source prefetches only the next two pictures and closes a cancelled late decode', async () => {
  const wait=deferred(), began=deferred(), closed=[];
  const f=stepSourceVM(stepResponse,{createImageBitmap:async blob=>{
    if(blob.index===1) {began.resolve(); await wait.promise;}
    return {index:blob.index,close(){closed.push(blob.index);}};
  }});
  const source=await f.Source.open();
  const abort=new AbortController();
  source.prefetch(0,abort.signal); await began.promise;
  assert.deepEqual(f.requests.filter(r=>r.url.includes('/frame')).map(r=>new URL(r.url,'http://local/').searchParams.get('step')),['1','2']);
  abort.abort(); wait.resolve();
  await new Promise(resolve=>setTimeout(resolve,0));
  assert.ok(closed.includes(1));
  assert.equal(source.frames.has(1),false);
  source.close();
});

test('closing while the action token is opening still releases the late token and does not poll it', async () => {
  const wait=deferred();
  const f=stepSourceVM((url,options)=>options.method==='DELETE' ? jsonReply({ok:true}) : wait.promise);
  const abort=new AbortController(), pending=f.Source.open('current',{signal:abort.signal});
  abort.abort(); wait.resolve(jsonReply({token:'late',indexing:true},202));
  await assert.rejects(pending);
  assert.equal(f.requests.length,2);
  assert.equal(f.requests[1].url,'api/replay/late');
  assert.equal(f.requests[1].options.method,'DELETE');
});

test('missing action history gives a retryable error without falling back to a long replay', async () => {
  const f=stepSourceVM(()=>jsonReply({},404));
  await assert.rejects(f.Source.open(),/动作历史.*请重试/);
  assert.equal(f.requests.length,1);
});

test('action source fallback decoding revokes object URLs even when decoding fails', async () => {
  const revoked=[], made=[];
  const f=stepSourceVM(stepResponse,{createImageBitmap:undefined,
    URL:{createObjectURL:()=>{made.push('blob:frame'); return 'blob:frame';},revokeObjectURL:url=>revoked.push(url)},
    Image:class {async decode(){throw Error('bad image');}},
  });
  await assert.rejects(f.Source.decode({}),/bad image/);
  assert.deepEqual(revoked,made);
});

test('all current and archived playback uses actions with no continuous recording option or fallback', async () => {
  const html=readFileSync(new URL('../server/index.html',import.meta.url),'utf8');
  assert.doesNotMatch(html,/vcrmode|完整录制|ReplayRecording\.open|new ReplayPlayer/);
  const begin=html.indexOf('const vcr = document.getElementById("vcr")');
  const end=html.indexOf('// ---- export the recording',begin);
  const dom=replayDOM(), opened=[], closed=[];
  class Player {async start(){} close(){}}
  const context=vm.createContext({document:dom.document,addEventListener(){},AbortController,
    ReplayKeys,GLYPH:{},ARROW:new Set(),colorOf:()=>'',ActionReplayPlayer:Player,
    ReplayPlayer:class {constructor(){throw Error('Continuous replay is forbidden');}},
    StepReplaySource:{open:async name=>{opened.push(name);return {close:()=>closed.push(name)};}},
    ReplayRecording:{open:()=>{throw Error('Raw recording API fallback is forbidden');}},
  });
  vm.runInContext(html.slice(begin,end)+'\n'+namedHTMLFunction(html,'openPlayback'),context);
  await context.openPlayback();
  context.vcrClose();
  await context.openPlayback('archive.jsonl');
  assert.deepEqual(opened,['current','archive.jsonl']);
  assert.ok(closed.includes('current'));
  assert.equal(dom.document.activeElement,dom.document.getElementById('vcrclose'));
  context.vcrClose();
});

test('unsupported action playback shows a retryable error and retries the same archive without a raw API fallback', async () => {
  const html=readFileSync(new URL('../server/index.html',import.meta.url),'utf8');
  const begin=html.indexOf('const vcr = document.getElementById("vcr")');
  const end=html.indexOf('// ---- export the recording',begin);
  const dom=replayDOM(), opened=[];
  const context=vm.createContext({document:dom.document,addEventListener(){},AbortController,
    ReplayKeys,GLYPH:{},ARROW:new Set(),colorOf:()=>'',
    ActionReplayPlayer:class {async start(){} close(){}},
    StepReplaySource:{open:async name=>{
      opened.push(name);
      if(opened.length===1) throw Error('动作历史暂不可用，请重试。');
      return {close(){}};
    }},
    ReplayRecording:{open:()=>{throw Error('Automatic fallback is forbidden');}},
  });
  vm.runInContext(html.slice(begin,end)+'\n'+namedHTMLFunction(html,'openPlayback'),context);
  await context.openPlayback('archive.jsonl');
  assert.match(dom.document.getElementById('vcrstatus').textContent,/动作历史.*请重试/);
  assert.doesNotMatch(dom.document.getElementById('vcrstatus').textContent,/完整录制/);
  assert.equal(dom.document.getElementById('vcrseek').disabled,true);
  assert.equal(dom.document.getElementById('vcrretry').hidden,false);
  assert.equal(dom.document.getElementById('vcrtime').textContent,'读取失败');
  await dom.document.getElementById('vcrretry').dispatch('click');
  assert.deepEqual(opened,['archive.jsonl','archive.jsonl']);
  assert.equal(dom.document.getElementById('vcrretry').hidden,true);
  context.vcrClose();
});

test('original time keeps milliseconds and long hours through action seeks independently of compressed progress', async () => {
  const html=readFileSync(new URL('../server/index.html',import.meta.url),'utf8');
  const begin=html.indexOf('const vcr = document.getElementById("vcr")');
  const end=html.indexOf('// ---- export the recording',begin);
  const dom=replayDOM();
  const times={0:1.234,1:86399.9996,128:407160.789,10819:864001.005};
  const source={steps:10820,step:async index=>({t:index===0 ? 1.25 : times[index],
    ...(index===0 ? {recorded_t:90061.234} : {}),who:'agent-a',act:'KEY',on:'up'}),
    frame:async index=>({index,width:320,height:200}),prefetch(){},close(){}};
  const context=vm.createContext({document:dom.document,addEventListener(){},AbortController,
    ReplayKeys,GLYPH:{},ARROW:new Set(),colorOf:()=>'',
    ActionReplayPlayer:class extends ActionReplayPlayer {
      constructor(source,callbacks){super(source,{...callbacks,schedule:()=>0,cancel:()=>{},now:()=>0});}
    },
    StepReplaySource:{open:async ()=>source},
  });
  const format=html.match(/function fmt\(s\) \{[\s\S]*?\n\}/)[0];
  vm.runInContext(html.slice(begin,end)+'\n'+format+'\n'+namedHTMLFunction(html,'openPlayback'),context);
  await context.openPlayback();
  const get=id=>dom.document.getElementById(id);
  assert.equal(get('vcrtime').textContent,'播放 0:00');
  assert.equal(get('vcrduration').textContent,'27:03');
  assert.equal(get('vcrrecorded').textContent,'动作 1 / 10820 · 原始时间 25:01:01.234');
  await get('vcrpause').dispatch('click');
  for(const [index,expected] of [[128,'113:06:00.789'],[1,'24:00:00.000'],[0,'25:01:01.234'],[10819,'240:00:01.005']]) {
    get('vcrseek').value=String(index*.6);
    await get('vcrseek').dispatch('input');
    assert.equal(get('vcv').image.index,index);
    assert.equal(get('vcrrecorded').textContent,`动作 ${index+1} / 10820 · 原始时间 ${expected}`);
    assert.ok(get('vcrseek').getAttribute('aria-valuetext').endsWith('原始时间 '+expected));
    assert.equal(get('vcrpause').textContent,'resume');
  }
  get('vcrspeed').value='2'; await get('vcrspeed').dispatch('change');
  assert.equal(get('vcrduration').textContent,'54:06');
  assert.match(get('vcrrecorded').textContent,/原始时间 240:00:01\.005$/);
  context.vcrClose();
});
