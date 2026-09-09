'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'video-export.js'),'utf8');
const base = 'http://localhost:8084/u/test-user/';
const key = 'qunxia-video-job:/u/test-user/';
const response = (body,status=200) => ({ok:status<400,status,json:async()=>body});
const row = (state,extra={}) => ({id:'job1',state,completed:2,total:4,...extra});
const flush = () => new Promise(resolve=>setImmediate(resolve));
function setup(handle, saved=null) {
  const storage = new Map(saved ? [[key,JSON.stringify({id:saved})]] : []);
  const elements = {save:{disabled:false},play:{disabled:false}};
  const calls=[],downloads=[],timers=new Map(),events={};let sequence=0;
  const sandbox={URL,location:{href:base},document:{
    getElementById:id=>elements[id],
    createElement:tag=>({style:{},click(){if(tag==='a')downloads.push(String(this.href));}}),
  },sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},
  setTimeout:fn=>{timers.set(++sequence,fn);return sequence;},clearTimeout:id=>timers.delete(id),
  addEventListener:(name,fn)=>events[name]=fn,
  fetch:async(url,options={})=>{const call={url:new URL(url),method:options.method||'GET',options};calls.push(call);return handle(call);}};
  elements.save.after=element=>elements.cancel=element;
  vm.runInNewContext(source,sandbox);
  return {elements,calls,downloads,storage,events,timers,
    tick:async()=>{const first=timers.entries().next().value;assert.ok(first);timers.delete(first[0]);await first[1]();await flush();}};
}
test('starts a backend job, preserves Play, reports packaging, then downloads at the user URL',async()=>{
  let state='finalizing';
  const f=setup(call=>call.method==='POST'?response(row('queued'),202):response(row(state,{download:'api/video/job1/file'})));
  await f.elements.save.onclick();assert.equal(f.elements.play.disabled,false);
  assert.equal(f.elements.save.disabled,true);assert.equal(f.elements.cancel.hidden,false);
  assert.equal(f.calls[0].url.href,base+'api/video');
  assert.deepEqual(JSON.parse(f.calls[0].options.body),{recording:'current',speed:4});
  await f.tick();assert.equal(f.elements.save.textContent,'封装 50%');
  state='ready';await f.tick();assert.equal(f.elements.save.disabled,false);
  await f.elements.save.onclick();assert.deepEqual(f.downloads,[base+'api/video/job1/file']);
  assert.equal(f.storage.size,0);assert.equal(f.elements.save.textContent,'⤓ MP4');
});
test('cancel wins against an older status response and allows another export',async()=>{
  let release;
  const f=setup(call=>call.method==='POST'?response(row('encoding'),202):call.method==='DELETE'?response(row('cancelled')):new Promise(resolve=>release=resolve));
  await f.elements.save.onclick();const old=f.tick();await flush();
  await f.elements.cancel.onclick();release(response(row('encoding')));await old;
  assert.equal(f.elements.save.textContent,'⤓ MP4');assert.equal(f.elements.save.disabled,false);
  assert.equal(f.elements.cancel.hidden,true);assert.equal(f.timers.size,0);assert.equal(f.storage.size,0);
});
test('reload resumes a saved task and unload leaves the backend running',async()=>{
  const f=setup(()=>response(row('encoding')),'job1');
  assert.equal(f.elements.save.disabled,true);await flush();
  assert.equal(f.calls[0].url.href,base+'api/video/job1');
  assert.equal(f.elements.save.textContent,'生成 50%');
  f.events.pagehide();assert.equal(f.timers.size,0);assert.equal(f.calls.length,1);
  assert.ok(f.storage.has(key));
});
test('an expired task or request error remains retryable',async()=>{
  const f=setup(()=>response({error:'task expired'},404),'old');await flush();
  assert.equal(f.elements.save.disabled,false);assert.equal(f.elements.save.title,'task expired');
  assert.equal(f.elements.save.textContent,'重试导出');assert.equal(f.storage.size,0);
});
test('a cache hit is immediately downloadable and never disables Play',async()=>{
  const f=setup(()=>response(row('ready',{cached:true,download:'api/video/job1/file'})));
  await f.elements.save.onclick();assert.equal(f.elements.save.textContent,'⤓ 下载 MP4');
  assert.equal(f.elements.play.disabled,false);assert.equal(f.elements.cancel.hidden,true);
  assert.equal(f.timers.size,0);
});
