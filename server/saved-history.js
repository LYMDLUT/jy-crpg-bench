// Complete disk-backed screenshot history. The realtime log's 40-image cache
// is separate; each page owns only eight images and releases its snapshot.
(() => {
  const PAGE = 8;
  const get = id => document.getElementById(id);
  const endpoint = path => new URL(path, location.href);
  let start = 0, total = 0, origin = null, busy = false, urls = [], controller = null;
  const box = get('historyrows'), info = get('historyinfo');
  function selectHistory(selected) {
    get('historypane').hidden = !selected;
    get('logrows').hidden = selected;
    get('historytab').setAttribute('aria-selected', String(selected));
    get('livetab').setAttribute('aria-selected', String(!selected));
    if (typeof updateImageJump === 'function') updateImageJump();
  }
  get('historytab').onclick = () => selectHistory(true);
  get('livetab').onclick = () => selectHistory(false);
  function buttons() {
    get('historyfirst').disabled = get('historyprev').disabled = busy || start <= 0;
    get('historynext').disabled = busy || start + PAGE >= total;
    get('historylatest').disabled = busy;
  }
  function releaseImages() { urls.forEach(url => URL.revokeObjectURL(url)); urls = []; }
  async function request(path, signal) {
    const response = await fetch(endpoint(path), {cache:'no-store', signal});
    if (!response.ok) throw Error(response.status === 404 ? '历史截图暂不可用，请重试。' : '读取历史失败，请重试。');
    return {response, data:await response.json()};
  }
  async function load(requested = null) {
    if (busy) return;
    busy = true; buttons();
    controller = new AbortController();
    const signal = controller.signal;
    let token = null;
    info.textContent = ' · 读取中';
    try {
      let result = await request('api/replay?recording=current', signal);
      token = result.data.token;
      if (!token) throw Error('历史读取未能开始，请重试。');
      while (result.response.status === 202 || result.data.indexing) {
        const progress = result.data.total ? Math.min(100, Math.floor(100 * result.data.scanned / result.data.total)) : null;
        info.textContent = ' · 正在读取磁盘历史' + (progress !== null ? ` ${progress}%` : '');
        await new Promise(resolve => setTimeout(resolve, 600));
        result = await request(`api/replay/${encodeURIComponent(token)}`, signal);
      }
      const meta = result.data;
      if (!Number.isSafeInteger(meta.steps) || meta.steps < 0) throw Error('历史记录数量无法识别。');
      if (origin !== null && origin !== meta.started) requested = null;
      origin = meta.started; total = meta.steps;
      start = Math.max(0, Math.min(requested ?? Math.max(0, total - PAGE), Math.max(0, total - 1)));
      const path = `api/replay/${encodeURIComponent(token)}/steps?start=${start}&count=${PAGE}`;
      const {data:page} = await request(path, signal);
      if (!Array.isArray(page.steps)) throw Error('历史截图列表无法读取。');
      releaseImages(); box.textContent = '';
      info.textContent = ' · ' + total.toLocaleString();
      get('historyrange').textContent = total ? `${start+1}–${start+page.steps.length} / ${total} 张` : '0 张';
      const imageRows = [];
      for (let offset = page.steps.length - 1; offset >= 0; offset--) {
        const step = page.steps[offset], index = start + offset;
        const row = document.createElement('article'); row.className = 'saved-row'; row.dataset.step = index;
        const details = document.createElement('div'); details.className = 'saved-meta';
        const who = document.createElement('span'); who.className = 'saved-who'; who.textContent = step.who || 'agent'; who.title = who.textContent; who.style.color = colorOf(who.textContent);
        const when = document.createElement('span'); when.textContent = `#${index+1} · ${fmt(step.t)}`;
        details.append(who, when);
        const action = document.createElement('div'); action.className = 'saved-action';
        const verb = document.createElement('span'); verb.className = 'verb';
        verb.textContent = ({GET:'截图',KEY:'按键',KEYS:'按键',WAIT:'等待'})[step.act] || step.act;
        action.append(verb);
        if (step.act === 'KEY' || step.act === 'KEYS') action.append(keySpans(step.on || ''));
        else if (step.act !== 'GET') action.append(document.createTextNode(step.on || ''));
        row.append(details, action); box.append(row); imageRows.push({row, index});
      }
      if (!page.steps.length) { const text = document.createElement('div'); text.className = 'history-empty'; text.textContent = '暂无已保存的历史截图'; box.append(text); }
      for (let i = 0; i < imageRows.length; i += 2) {
        await Promise.all(imageRows.slice(i,i+2).map(async ({row,index}) => {
          try {
            const response = await fetch(endpoint(`api/replay/${encodeURIComponent(token)}/frame?step=${index}`), {cache:'no-store',signal});
            if (!response.ok) throw Error();
            const url = URL.createObjectURL(await response.blob()); urls.push(url);
            const link = document.createElement('a'); link.className = 'saved-shot'; link.href = url; link.target = '_blank'; link.rel = 'noopener'; link.title = '打开完整画面 · 从磁盘录像按步骤还原';
            const image = new Image(); image.src = url; image.alt = `历史截图 ${index+1}`; image.dataset.step = index;
            link.append(image); row.append(link); await image.decode();
          } catch(error) {
            if (signal.aborted) throw error;
            const text = document.createElement('div'); text.className = 'history-empty'; text.textContent = '截图暂时无法加载，请重试'; row.append(text);
          }
        }));
      }
      box.scrollTop = 0;
    } catch(error) {
      if (!signal.aborted) { info.textContent=''; box.textContent=''; const text=document.createElement('div'); text.className='history-empty'; text.textContent=error.message; box.append(text); }
    } finally {
      if (token) await fetch(endpoint(`api/replay/${encodeURIComponent(token)}`), {method:'DELETE',keepalive:true}).catch(()=>{});
      busy = false; buttons();
    }
  }
  get('historyfirst').onclick = () => load(0);
  get('historyprev').onclick = () => load(Math.max(0,start-PAGE));
  get('historynext').onclick = () => load(start+PAGE);
  get('historylatest').onclick = () => load();
  addEventListener('pagehide', event => { if (!event.persisted) { controller?.abort(); releaseImages(); } });
  selectHistory(true); load();
})();
