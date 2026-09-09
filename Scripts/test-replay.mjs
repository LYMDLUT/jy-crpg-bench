import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
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
