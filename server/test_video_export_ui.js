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
  const calls=[],downloads=[],timers=new Map(),delays=new Map(),events={};let sequence=0;
  const sandbox={URL,AbortController,location:{href:base},document:{
    getElementById:id=>elements[id],
    createElement:tag=>({style:{},click(){if(tag==='a')downloads.push(String(this.href));}}),
  },sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k),removeItem:k=>storage.delete(k)},
  setTimeout:(fn,delay)=>{timers.set(++sequence,fn);delays.set(sequence,delay);return sequence;},
  clearTimeout:id=>{timers.delete(id);delays.delete(id);},
  addEventListener:(name,fn)=>events[name]=fn,
  fetch:async(url,options={})=>{const call={url:new URL(url),method:options.method||'GET',options};calls.push(call);return handle(call);}};
  elements.save.after=element=>elements.cancel=element;
  vm.runInNewContext(source,sandbox);
  return {elements,calls,downloads,storage,events,timers,delays,
    tick:async()=>{const first=timers.entries().next().value;assert.ok(first);timers.delete(first[0]);delays.delete(first[0]);await first[1]();await flush();}};
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
test('an expired task allows generating a replacement',async()=>{
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

test('one lost status response preserves the job, cancellation, and automatic recovery without another POST',async()=>{
  let polls=0;
  const f=setup(call=>{
    if(call.method==='POST')return response(row('encoding'),202);
    if(++polls===1)throw new TypeError('Failed to fetch');
    return response(row('ready',{download:'api/video/job1/file'}));
  });
  await f.elements.save.onclick();await f.tick();
  assert.equal(f.elements.save.textContent,'连接中断，正在重试');
  assert.equal(f.elements.save.disabled,true);
  assert.equal(f.elements.cancel.hidden,false);
  assert.equal(f.elements.cancel.disabled,false);
  assert.deepEqual(JSON.parse(f.storage.get(key)),{id:'job1'});
  assert.equal(f.timers.size,1);
  await f.elements.save.onclick();
  assert.equal(f.calls.filter(call=>call.method==='POST').length,1,'A direct retry click cannot submit a duplicate');
  await f.tick();
  assert.equal(f.elements.save.textContent,'⤓ 下载 MP4');
  assert.ok(f.calls.filter(call=>call.method==='GET').every(call=>call.url.href===base+'api/video/job1'));
  assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
});

test('repeated network, 5xx and 429 failures keep the saved id and cap the retry delay before recovery',async()=>{
  const failures=[new TypeError('offline'),500,503,429,new TypeError('offline'),502,503,403];
  let polls=0;
  const f=setup(call=>{
    if(call.method==='POST')return response(row('rendering'),202);
    const failure=failures[polls++];
    if(failure instanceof Error)throw failure;
    return failure ? response({error:'temporary'},failure) : response(row('rendering'));
  });
  await f.elements.save.onclick();
  const waited=[];
  for(let index=0;index<failures.length;index++){
    await f.tick();
    assert.deepEqual(JSON.parse(f.storage.get(key)),{id:'job1'});
    assert.equal(f.elements.save.disabled,true);
    assert.equal(f.elements.cancel.hidden,false);
    assert.equal(f.delays.size,1);
    waited.push([...f.delays.values()][0]);
  }
  assert.deepEqual(waited,[700,1400,2800,5600,11200,15000,15000,15000]);
  await f.tick();
  assert.equal(f.elements.save.textContent,'生成 50%');
  assert.deepEqual([...f.delays.values()],[700],'A successful status resets the backoff');
  assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
  assert.ok(f.calls.filter(call=>call.method==='GET').every(call=>call.url.pathname.endsWith('/job1')));
});

test('cancelling after a polling outage deletes the original task and stops its retries',async()=>{
  const f=setup(call=>{
    if(call.method==='POST')return response(row('encoding'),202);
    if(call.method==='DELETE')return response(row('cancelled'));
    return response({error:'temporary'},503);
  });
  await f.elements.save.onclick();await f.tick();
  await f.elements.cancel.onclick();
  const deletes=f.calls.filter(call=>call.method==='DELETE');
  assert.equal(deletes.length,1);assert.equal(deletes[0].url.href,base+'api/video/job1');
  assert.equal(f.elements.save.textContent,'⤓ MP4');
  assert.equal(f.elements.save.disabled,false);assert.equal(f.elements.cancel.hidden,true);
  assert.equal(f.timers.size,0);assert.equal(f.storage.size,0);
});

test('a failed cancellation keeps the original task available for polling and another cancellation',async()=>{
  let deletes=0;
  const f=setup(call=>{
    if(call.method==='POST')return response(row('encoding'),202);
    if(call.method==='DELETE'){
      if(++deletes===1)throw new TypeError('connection lost');
      return response(row('cancelled'));
    }
    return response(row('encoding'));
  });
  await f.elements.save.onclick();await f.elements.cancel.onclick();
  assert.deepEqual(JSON.parse(f.storage.get(key)),{id:'job1'});
  assert.equal(f.elements.cancel.disabled,false);assert.equal(f.elements.save.disabled,true);
  await f.tick();await f.elements.cancel.onclick();
  assert.ok(f.calls.filter(call=>call.method==='DELETE').every(call=>call.url.href===base+'api/video/job1'));
  assert.equal(f.storage.size,0);assert.equal(f.timers.size,0);
});

for(const status of [404,410])test(`authoritative ${status} removes an expired restored job and permits a replacement`,async()=>{
  const f=setup(call=>call.method==='POST'?response(row('queued'),202):response({error:'task expired'},status),'expired');
  await flush();
  assert.equal(f.elements.save.disabled,false);assert.equal(f.elements.cancel.hidden,true);
  assert.equal(f.storage.size,0);assert.equal(f.timers.size,0);
  await f.elements.save.onclick();
  assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
  assert.deepEqual(JSON.parse(f.storage.get(key)),{id:'job1'});
});

test('fast repeated cancellation cannot revive a task from a late recovery poll',async()=>{
  let polls=0,releaseGet,releaseDelete;
  const f=setup(call=>{
    if(call.method==='POST')return response(row('encoding'),202);
    if(call.method==='DELETE')return new Promise(resolve=>releaseDelete=resolve);
    if(++polls===1)return response({},503);
    return new Promise(resolve=>releaseGet=resolve);
  });
  await f.elements.save.onclick();await f.tick();
  const pendingPoll=f.tick();await flush();
  const pendingCancel=f.elements.cancel.onclick();
  await f.elements.cancel.onclick();await f.elements.save.onclick();
  assert.equal(f.calls.filter(call=>call.method==='DELETE').length,1);
  assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
  releaseDelete(response(row('cancelled')));await pendingCancel;
  releaseGet(response(row('ready',{download:'api/video/job1/file'})));await pendingPoll;
  assert.equal(f.elements.save.textContent,'⤓ MP4');
  assert.equal(f.elements.cancel.hidden,true);assert.equal(f.storage.size,0);assert.equal(f.timers.size,0);
});

test('a hung status request times out, preserves its id, and cannot overwrite a later successful retry',async()=>{
  let release,polls=0;
  const f=setup(call=>{
    if(call.method==='POST')return response(row('encoding'),202);
    if(++polls===1)return new Promise(resolve=>release=resolve);
    return response(row('ready',{download:'api/video/job1/file'}));
  });
  await f.elements.save.onclick();
  const hung=f.tick();await flush();
  assert.deepEqual([...f.delays.values()],[15000]);
  await f.tick();await hung;
  assert.equal(f.calls[1].options.signal.aborted,true);
  assert.equal(f.elements.save.textContent,'连接中断，正在重试');
  assert.deepEqual(JSON.parse(f.storage.get(key)),{id:'job1'});
  await f.tick();
  release(response(row('encoding')));await flush();
  assert.equal(f.elements.save.textContent,'⤓ 下载 MP4');
  assert.equal(f.timers.size,0);
  assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
});

test('pagehide aborts a pending status read without UI changes or deleting the saved job, and pageshow resumes it',async()=>{
  let release,polls=0;
  const f=setup(()=>++polls===1?new Promise(resolve=>release=resolve):response(row('encoding')),'job1');
  const before=f.elements.save.textContent;
  f.events.pagehide({persisted:true});
  assert.equal(f.timers.size,0);assert.equal(f.calls[0].options.signal.aborted,true);
  release(response(row('ready',{download:'api/video/job1/file'})));await flush();
  assert.equal(f.elements.save.textContent,before);
  assert.deepEqual(JSON.parse(f.storage.get(key)),{id:'job1'});
  f.events.pageshow({persisted:true});await flush();
  assert.equal(f.elements.save.textContent,'生成 50%');
  assert.equal(f.calls.length,2);assert.ok(f.calls.every(call=>call.method==='GET'));
});

test('a creation response after pagehide saves its new task id without updating the hidden UI',async()=>{
  let release;
  const f=setup(()=>new Promise(resolve=>release=resolve));
  const creation=f.elements.save.onclick();
  f.events.pagehide({persisted:false});
  const before=f.elements.save.textContent;
  release(response(row('encoding'),202));await creation;
  assert.equal(f.elements.save.textContent,before);
  assert.deepEqual(JSON.parse(f.storage.get(key)),{id:'job1'});
  assert.equal(f.timers.size,0);
});

test('a hung cancellation times out and resumes polling without forgetting the original task',async()=>{
  let release;
  const f=setup(call=>{
    if(call.method==='DELETE')return new Promise(resolve=>release=resolve);
    return response(row('encoding'));
  });
  await f.elements.save.onclick();
  const cancellation=f.elements.cancel.onclick();await flush();
  assert.equal(f.elements.cancel.disabled,true);
  assert.deepEqual([...f.delays.values()],[15000]);
  await f.tick();await cancellation;
  assert.equal(f.elements.cancel.disabled,false);
  assert.deepEqual(JSON.parse(f.storage.get(key)),{id:'job1'});
  await f.tick();
  release(response(row('cancelled')));await flush();
  assert.equal(f.elements.save.textContent,'生成 50%','A timed-out DELETE response must not override its later status query');
  assert.ok(f.calls.filter(call=>call.method!=='POST').every(call=>call.url.href===base+'api/video/job1'));
  assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
});

test('pageshow restores a ready creation result that arrived while the page was hidden',async()=>{
  let release;
  const f=setup(()=>new Promise(resolve=>release=resolve));
  const creation=f.elements.save.onclick();
  f.events.pagehide({persisted:true});
  release(response(row('ready',{download:'api/video/job1/file'})));await creation;
  assert.equal(f.elements.save.textContent,'提交中');
  f.events.pageshow({persisted:true});
  assert.equal(f.elements.save.disabled,false);
  assert.equal(f.elements.save.textContent,'⤓ 下载 MP4');
  await f.elements.save.onclick();
  assert.deepEqual(f.downloads,[base+'api/video/job1/file']);
});

test('pageshow restores an idle button if creation failed while the page was hidden',async()=>{
  let reject;
  const f=setup(()=>new Promise((_,fail)=>reject=fail));
  const creation=f.elements.save.onclick();f.events.pagehide({persisted:true});
  reject(new TypeError('offline'));await creation;
  assert.equal(f.elements.save.textContent,'提交中');
  f.events.pageshow({persisted:true});
  assert.equal(f.elements.save.disabled,false);assert.equal(f.elements.save.textContent,'⤓ MP4');
  assert.equal(f.storage.size,0);assert.equal(f.timers.size,0);
});
