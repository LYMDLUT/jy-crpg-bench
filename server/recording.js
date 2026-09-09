// One page at a time; the server pins the recording so reset cannot change it.
class ReplayRecording {
  abort = new AbortController();
  static async open(recording = 'current') {
    const source = new ReplayRecording();
    // Select a file only when opening it. Every later request uses the token
    // for that pinned file, even if the current recording is reset meanwhile.
    await source.load({recording});
    source.keepalive = setInterval(() => source.request({touch:'1'}).catch(() => {}), 60000);
    return source;
  }
  async request(extra, signal) {
    const query = new URLSearchParams({view:'paged', ...(this.token ? {token:this.token} : {}), ...extra});
    const response = await fetch('api/recording?' + query, {
      signal: extra.close ? undefined : signal ? AbortSignal.any([signal, this.abort.signal]) : this.abort.signal,
    });
    const page = await response.json();
    if (!response.ok) throw new Error(page.error || 'Recording unavailable');
    return page;
  }
  async load(extra) {
    this.setPage(await this.request(extra));
  }
  setPage(page) {
    this.page = page;
    this.token = this.page.token;
    this.duration = this.page.duration;
    this.canSeek = this.page.seek_supported ?? this.canSeek ?? false;
    this.index = 0;
  }
  async seek(when, signal) {
    for (;;) {
      const page = await this.request(this.canSeek ? {time:String(when)} : {}, signal);
      if (!page.indexing) {
        this.setPage(page);
        return page.seek || {at:0, held:{}};
      }
      await new Promise((resolve, reject) => {
        const timer = setTimeout(done, 100);
        function done() { signal?.removeEventListener('abort', cancel); resolve(); }
        function cancel() { clearTimeout(timer); reject(signal.reason); }
        if (signal?.aborted) cancel();
        else signal?.addEventListener('abort', cancel, {once:true});
      });
    }
  }
  async peek() {
    if (this.closed) return null;
    if (this.index >= this.page.events.length && !this.page.done) await this.load({start:this.page.next});
    return this.closed ? null : (this.page.events[this.index] || null);
  }
  take() { this.index++; }
  close() {
    if (this.closed) return;
    this.closed = true;
    clearInterval(this.keepalive);
    this.abort.abort();
    this.request({close:'1'}).catch(() => {});
    this.page = {events:[],done:true};
  }
}

// Read action metadata in small pages and reconstruct only the pictures being
// watched. Recorded wall time is metadata, never the action playback clock.
class StepReplaySource {
  constructor() {
    this.abort = new AbortController();
    this.pages = new Map();
    this.frames = new Map();
    this.pending = new Map();
  }
  static async open(recording = 'current', {signal, progress = ()=>{}} = {}) {
    const source = new StepReplaySource();
    const close = () => source.close();
    source.detach = () => signal?.removeEventListener('abort', close);
    signal?.addEventListener('abort', close, {once:true});
    try {
      if (signal?.aborted) throw signal.reason;
      // The response owns a pinned token. Do not abandon it on close before
      // learning that token; release it even if a newer viewer has opened.
      let response = await fetch('api/replay?' + new URLSearchParams({recording}), {cache:'no-store'});
      let meta = await source.json(response);
      source.token = meta.token;
      if (!source.token) throw Error('动作回放未能开始，可选择“完整录制”。');
      if (source.closed) { source.release(); throw source.abort.signal.reason; }
      while (response.status === 202 || meta.indexing) {
        progress(meta);
        await source.wait(400);
        response = await source.request('');
        meta = await source.json(response);
      }
      if (!Number.isSafeInteger(meta.steps) || meta.steps < 1)
        throw Error('该录像没有可回放的动作，可选择“完整录制”。');
      source.steps = meta.steps;
      source.duration = Number(meta.duration) || 0;
      source.beat = .6;
      source.keepalive = setInterval(() => source.request('').catch(()=>{}), 60000);
      return source;
    } catch (error) { source.close(); throw error; }
  }
  async json(response) {
    if (!response.ok) throw Error(response.status === 404
      ? '该录像暂不支持动作回放，请选择“完整录制”。'
      : '动作回放读取失败，请重试或选择“完整录制”。');
    return response.json();
  }
  request(path, signal) {
    return fetch('api/replay/' + encodeURIComponent(this.token) + path, {
      cache:'no-store', signal:signal ? AbortSignal.any([signal, this.abort.signal]) : this.abort.signal,
    });
  }
  wait(delay) {
    const signal = this.abort.signal;
    return new Promise((resolve, reject) => {
      const done = () => { signal.removeEventListener('abort', aborted); resolve(); };
      const timer = setTimeout(done, delay);
      const aborted = () => { clearTimeout(timer); reject(signal.reason); };
      if (signal.aborted) aborted();
      else signal.addEventListener('abort', aborted, {once:true});
    });
  }
  check(signal) {
    if (this.closed || this.abort.signal.aborted) throw this.abort.signal.reason;
    if (signal?.aborted) throw signal.reason;
  }
  async step(number, signal) {
    this.check(signal);
    const start = Math.floor(number / 128) * 128;
    let page = this.pages.get(start);
    if (!page) {
      page = await this.json(await this.request(`/steps?start=${start}&count=128`, signal));
      this.check(signal);
      if (page.start !== start || !Array.isArray(page.steps)) throw Error('动作列表无法读取。');
    }
    this.pages.delete(start); this.pages.set(start, page);
    while (this.pages.size > 2) this.pages.delete(this.pages.keys().next().value);
    const step = page.steps[number - start];
    if (!step) throw Error('该动作不存在。');
    return step;
  }
  async frame(number, signal) {
    this.check(signal);
    if (this.frames.has(number)) {
      const image = this.frames.get(number);
      this.frames.delete(number); this.frames.set(number, image);
      return image;
    }
    const previous = this.pending.get(number);
    if (previous && !previous.signal.aborted) return previous.promise;
    const combined = signal ? AbortSignal.any([signal, this.abort.signal]) : this.abort.signal;
    const pending = {signal:combined};
    pending.promise = (async () => {
      let image;
      try {
        const response = await this.request(`/frame?step=${number}`, combined);
        if (!response.ok || response.status === 202) throw Error('动作画面暂时无法读取，请重试。');
        const blob = await response.blob();
        this.check(combined);
        image = await StepReplaySource.decode(blob);
        this.check(combined);
        this.frames.set(number, image);
        while (this.frames.size > 4) {
          const oldest = this.frames.keys().next().value;
          this.frames.get(oldest).close?.(); this.frames.delete(oldest);
        }
        return image;
      } catch (error) { image?.close?.(); throw error; }
      finally { if (this.pending.get(number) === pending) this.pending.delete(number); }
    })();
    this.pending.set(number, pending);
    return pending.promise;
  }
  static async decode(blob) {
    if (typeof createImageBitmap === 'function') return createImageBitmap(blob);
    const url = URL.createObjectURL(blob);
    try { const image = new Image(); image.src = url; await image.decode(); return image; }
    finally { URL.revokeObjectURL(url); }
  }
  prefetch(number, signal) {
    // At most two future pictures, not the next metadata page's 128 pictures.
    for (let next = number + 1; next < Math.min(this.steps, number + 3); next++)
      this.frame(next, signal).catch(()=>{});
  }
  release() {
    if (!this.token || this.released) return;
    this.released = true;
    fetch('api/replay/' + encodeURIComponent(this.token), {method:'DELETE',keepalive:true}).catch(()=>{});
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.detach?.();
    clearInterval(this.keepalive);
    this.abort.abort();
    for (const image of this.frames.values()) image.close?.();
    this.frames.clear(); this.pages.clear(); this.pending.clear();
    this.release();
  }
}
if (typeof module !== 'undefined') module.exports = {ReplayRecording, StepReplaySource};
