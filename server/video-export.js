// Background action-video export. No realtime waiting and no browser frame log.
(() => {
  const button = document.getElementById('save');
  if (!button) return;
  const api = new URL('api/video/', location.href);
  const page = new URL('.', location.href);
  const key = 'qunxia-video-job:' + page.pathname;
  const cancel = document.createElement('button');
  cancel.id = 'video-cancel'; cancel.textContent = '取消'; cancel.hidden = true;
  cancel.style.cssText = 'font:inherit;font-size:10px;padding:3px 6px;background:#17171b;color:#ccc;border:1px solid #2e2e36;border-radius:4px;cursor:pointer';
  button.after(cancel);
  let job = null, requestId = null, timer = null, requesting = false, cancelling = false, closed = false, revision = 0;
  let postRevision = 0;
  let activePoll = null, activeCancel = null, failures = 0;
  const states = new Set(['queued','indexing','rendering','encoding','finalizing','ready','cancelled','error','failed']);
  const terminal = state => ['ready','cancelled','error','failed'].includes(state);
  const storage = value => { try { value ? sessionStorage.setItem(key,JSON.stringify(value)) : sessionStorage.removeItem(key); } catch {} };
  function newRequestId() {
    try { if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID(); } catch {}
    return `video-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }
  function schedule(delay=700) {
    clearTimeout(timer); timer=null;
    if (job && !terminal(job.state) && !closed && !cancelling) timer=setTimeout(poll,delay);
  }
  function stopPoll() {
    if (!activePoll) return;
    clearTimeout(activePoll.timeout);
    activePoll.controller.abort();
    activePoll=null;
  }
  function show(row) {
    job = row;
    failures = 0;
    const busy = !terminal(row.state);
    button.disabled = requesting || busy;
    cancel.hidden = !busy; cancel.disabled = false;
    const percent = row.total > 0 ? ' ' + Math.floor(100 * row.completed / row.total) + '%' : '';
    button.textContent = ({queued:'排队中',indexing:'读取历史',rendering:'生成',encoding:'生成',finalizing:'封装',ready:'⤓ 下载 MP4',cancelled:'⤓ MP4',error:'重试导出',failed:'重试导出'})[row.state] + (busy ? percent : '');
    button.title = row.error || (busy ? `后台处理 ${row.completed || 0} / ${row.total || '?'}，可以继续回放` : '后台生成动作视频，跳过空闲等待');
    storage(busy || row.state === 'ready' ? {id:row.id} : null);
    schedule();
  }
  async function call(url,options={}) {
    const response = await fetch(url,{cache:'no-store',...options});
    if (!response.ok) {
      // HTTP expiry remains authoritative even when the error body is not JSON.
      const body = await response.json().catch(()=>({}));
      const error=Error(body?.error || ([404,410].includes(response.status) ? '后台任务已失效，请重新生成' : `导出请求失败（${response.status}）`));
      error.status=response.status;
      throw error;
    }
    // A truncated successful response cannot stand in for a real job status.
    return response.json();
  }
  function validate(row,id) {
    if (!row || typeof row.id!=='string' || !row.id || (id!==undefined && row.id!==id) || !states.has(row.state))
      throw Error('无法读取后台任务状态');
    return row;
  }
  async function timedCall(pending,url,options={}) {
    const signal=pending.controller.signal;
    let aborted;
    const cancelled=new Promise((_,reject)=>{
      aborted=()=>reject(signal.reason);
      signal.addEventListener('abort',aborted,{once:true});
    });
    pending.timeout=setTimeout(()=>pending.controller.abort(Error('后台任务请求超时')),15000);
    try { return await Promise.race([call(url,{...options,signal}),cancelled]); }
    finally {clearTimeout(pending.timeout);signal.removeEventListener('abort',aborted);}
  }
  function unavailable(error) {
    if ([404,410].includes(error.status)) {
      clearTimeout(timer); timer=null;
      storage(null); job=null; failures=0; cancel.hidden=true;
      button.disabled=false; button.textContent='重试导出'; button.title=error.message;
      return;
    }
    // A lost status response says nothing about the backend job's lifetime.
    // Retain its id and cancellation controls; never create a replacement.
    storage({id:job.id});
    button.disabled=true; button.textContent='连接中断，正在重试'; button.title=error.message;
    cancel.hidden=false; cancel.disabled=false;
    schedule(Math.min(15000,700 * 2 ** Math.min(failures++,5)));
  }
  async function poll() {
    if (!job || terminal(job.state) || closed || cancelling || activePoll) return;
    clearTimeout(timer); timer=null;
    const current = ++revision, id=job.id;
    const pending={controller:new AbortController()};
    activePoll=pending;
    try {
      const row = await timedCall(pending,new URL(id,api));
      if (current !== revision || closed) return;
      show(validate(row,id));
    } catch(error) { if (current === revision && !closed) unavailable(error); }
    finally {if (activePoll===pending) activePoll=null;}
  }
  button.textContent='⤓ MP4';
  button.title='后台生成动作视频，跳过空闲等待';
  button.onclick=async()=>{
    if (requesting || closed || (job && !terminal(job.state))) return;
    if (job?.state==='ready' && job.download) {
      const link=document.createElement('a');link.href=new URL(job.download,page);link.download='';link.click();
      job=null;storage(null);button.textContent='⤓ MP4';return;
    }
    requesting=true;button.disabled=true;button.textContent='提交中';
    if (!requestId) requestId=newRequestId();
    // Persist the token before sending. If the response body is truncated after
    // the backend creates a job, retrying this exact token is safe and returns
    // the original job instead of creating a duplicate.
    storage({requestId});
    const currentPost=++postRevision;
    const pending={controller:new AbortController()};
    try {
      const row=await timedCall(pending,new URL('api/video',page),{method:'POST',headers:{'Content-Type':'application/json','X-Video-Request-Id':requestId},body:JSON.stringify({recording:'current',speed:4,requestId})});
      // A timed-out request can still deliver its body after a retry. Once a
      // newer submit exists, that late response must not replace its state.
      if (currentPost !== postRevision) return;
      validate(row);
      requestId=null;
      requesting=false;
      if (closed) {job=row;storage(!terminal(row.state)||row.state==='ready'?{id:row.id}:null);return;}
      show(row);
    } catch(error) {
      if (currentPost !== postRevision) return;
      requesting=false;
      if ([404,410].includes(error.status)) { requestId=null; storage(null); }
      if(closed)return;
      button.disabled=false;button.textContent='重试导出';button.title=error.message;
    }
  };
  cancel.onclick=async()=>{
    if (!job || closed || cancelling) return;
    const current=++revision,id=job.id;clearTimeout(timer);timer=null;stopPoll();cancelling=true;
    const pending={controller:new AbortController()};activeCancel=pending;
    cancel.disabled=true;
    try { const row=await timedCall(pending,new URL(id,api),{method:'DELETE'});if(current===revision&&!closed){validate(row,id);cancelling=false;show(row);} }
    catch(error) { if(current!==revision||closed)return;cancelling=false;unavailable(error); }
    finally {if(current===revision)cancelling=false;if(activeCancel===pending)activeCancel=null;}
  };
  addEventListener('pagehide',()=>{
    closed=true;++revision;clearTimeout(timer);timer=null;stopPoll();cancelling=false;
    if(activeCancel){clearTimeout(activeCancel.timeout);activeCancel.controller.abort();activeCancel=null;}
  });
  addEventListener('pageshow',event=>{
    if(!event.persisted||!closed)return;
    closed=false;
    if(job){if(job.state)show(job);if(!terminal(job.state))poll();}
    else if(!requesting){button.disabled=false;button.textContent='⤓ MP4';cancel.hidden=true;}
  });
  try {
    const saved=JSON.parse(sessionStorage.getItem(key)||'null');
    if (typeof saved?.requestId==='string' && saved.requestId) requestId=saved.requestId;
    if(saved?.id){job=saved;button.disabled=true;button.textContent='读取任务';poll();}
  } catch {}
})();
