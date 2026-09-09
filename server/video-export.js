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
  let job = null, timer = null, requesting = false, closed = false, revision = 0;
  const terminal = state => ['ready','cancelled','error','failed'].includes(state);
  const storage = value => { try { value ? sessionStorage.setItem(key,JSON.stringify(value)) : sessionStorage.removeItem(key); } catch {} };
  function show(row) {
    job = row;
    const busy = !terminal(row.state);
    button.disabled = requesting || busy;
    cancel.hidden = !busy; cancel.disabled = false;
    const percent = row.total > 0 ? ' ' + Math.floor(100 * row.completed / row.total) + '%' : '';
    button.textContent = ({queued:'排队中',indexing:'读取历史',rendering:'生成',encoding:'生成',finalizing:'封装',ready:'⤓ 下载 MP4',cancelled:'⤓ MP4',error:'重试导出',failed:'重试导出'})[row.state] + (busy ? percent : '');
    button.title = row.error || (busy ? `后台处理 ${row.completed || 0} / ${row.total || '?'}，可以继续回放` : '后台生成动作视频，跳过空闲等待');
    storage(busy || row.state === 'ready' ? {id:row.id} : null);
    clearTimeout(timer);
    if (busy && !closed) timer = setTimeout(poll,700);
  }
  async function call(url,options={}) {
    const response = await fetch(url,{cache:'no-store',...options});
    const body = await response.json().catch(()=>({}));
    if (!response.ok) throw Error(body.error || (response.status===404 ? '后台任务不可用，请重新生成' : `导出请求失败（${response.status}）`));
    return body;
  }
  async function poll() {
    if (!job || closed) return;
    const current = ++revision;
    try { const row = await call(new URL(job.id,api)); if (current === revision && !closed) show(row); }
    catch(error) { if (current !== revision || closed) return; clearTimeout(timer); storage(null); job=null; cancel.hidden=true; button.disabled=false; button.textContent='重试导出'; button.title=error.message; }
  }
  button.textContent='⤓ MP4';
  button.title='后台生成动作视频，跳过空闲等待';
  button.onclick=async()=>{
    if (requesting) return;
    if (job?.state==='ready' && job.download) {
      const link=document.createElement('a');link.href=new URL(job.download,page);link.download='';link.click();
      job=null;storage(null);button.textContent='⤓ MP4';return;
    }
    requesting=true;button.disabled=true;button.textContent='提交中';
    try {
      const row=await call(new URL('api/video',page),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({recording:'current',speed:4})});
      requesting=false;show(row);
    } catch(error) { requesting=false;button.disabled=false;button.textContent='重试导出';button.title=error.message; }
  };
  cancel.onclick=async()=>{
    if (!job) return;
    const current=++revision;clearTimeout(timer);
    cancel.disabled=true;
    try { const row=await call(new URL(job.id,api),{method:'DELETE'});if(current===revision&&!closed)show(row); }
    catch(error) { if(current!==revision||closed)return;cancel.disabled=false;button.title=error.message;timer=setTimeout(poll,700); }
  };
  addEventListener('pagehide',()=>{closed=true;++revision;clearTimeout(timer);});
  try { const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved?.id){job=saved;button.disabled=true;button.textContent='读取任务';poll();} } catch {}
})();
