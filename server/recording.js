// One page at a time; the server pins the recording so reset cannot change it.
class ReplayRecording {
  static async open() {
    const source = new ReplayRecording();
    await source.load({});
    source.keepalive = setInterval(() => source.request({touch:'1'}).catch(() => {}), 60000);
    return source;
  }
  async request(extra) {
    const query = new URLSearchParams({view:'paged', ...(this.token ? {token:this.token} : {}), ...extra});
    const response = await fetch('api/recording?' + query);
    const page = await response.json();
    if (!response.ok) throw new Error(page.error || 'Recording unavailable');
    return page;
  }
  async load(extra) {
    this.page = await this.request(extra);
    this.token = this.page.token;
    this.duration = this.page.duration;
    this.index = 0;
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
    this.request({close:'1'}).catch(() => {});
    this.page = {events:[],done:true};
  }
}
