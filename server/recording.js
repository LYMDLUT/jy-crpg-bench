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
if (typeof module !== 'undefined') module.exports = {ReplayRecording};
