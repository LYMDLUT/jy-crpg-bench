// One serialized render queue. A newer seek invalidates a decode that has not
// painted yet; pause/resume keeps the cursor and anchors a new playback clock.
class ReplayPlayer {
  constructor(source, {decode, paint, complete, reset, update, error,
                       now=()=>performance.now(), schedule=(fn, delay)=>setTimeout(fn, delay),
                       cancel=timer=>clearTimeout(timer)}) {
    Object.assign(this, {source, decode, paint, complete, reset, update, error, now, schedule, cancel});
    this.position = this.origin = this.duration = this.floor = 0;
    this.speed = 4;
    this.epoch = 0;
    this.queue = Promise.resolve();
    this.controller = new AbortController();
    this.playing = this.wantPlaying = this.ready = this.closed = false;
    this.loading = true;
  }
  current() {
    return Math.min(this.duration, this.playing
      ? this.anchorPosition + (this.now() - this.anchorTime) / 1000 * this.speed : this.position);
  }
  emit() {
    this.update({position:this.position, duration:this.duration, playing:this.wantPlaying,
                 loading:this.loading, ready:this.ready, speed:this.speed});
  }
  enqueue(work) {
    this.queue = this.queue.catch(()=>{}).then(work);
    return this.queue;
  }
  async start() {
    const epoch = this.epoch;
    let prefixTime = 0;
    this.reset({});
    this.wantPlaying = true;
    this.emit();
    for (;;) {
      const event = await this.source.peek();
      if (this.closed || epoch !== this.epoch) return;
      if (!event) throw new Error('No complete frame in this recording');
      this.source.take();
      prefixTime = Math.max(prefixTime, Number(event.t) || 0);
      const decoded = event.d ? await this.decode(event) : null;
      if (this.closed || epoch !== this.epoch) return;
      if (!decoded) { this.paint(null, event); continue; }
      if (!this.complete(decoded)) continue;
      this.paint(decoded, event);
      this.origin = this.floor = prefixTime;
      this.duration = Math.max(0, this.source.duration - this.origin);
      this.position = 0;
      this.ready = true;
      this.loading = false;
      this.emit();
      if (this.wantPlaying) this.play();
      return;
    }
  }
  async renderThrough(target, epoch) {
    while (!this.closed && epoch === this.epoch) {
      const event = await this.source.peek();
      if (this.closed || epoch !== this.epoch || !event) return;
      const when = Math.max(this.floor, Number(event.t) || 0);
      if (when > target) return;
      this.source.take();
      const decoded = event.d ? await this.decode(event) : null;
      if (this.closed || epoch !== this.epoch) return;
      this.paint(decoded, event);
      this.floor = when;
    }
  }
  arm() {
    this.cancel(this.timer);
    if (this.playing && !this.closed) this.timer = this.schedule(()=>this.tick(), 16);
  }
  async tick() {
    if (!this.playing || this.closed || this.loading) return;
    const epoch = this.epoch, target = this.current();
    try {
      await this.enqueue(()=>this.renderThrough(this.origin + target, epoch));
      if (epoch !== this.epoch || this.closed) return;
      if (this.playing) this.position = target;
      if (this.position >= this.duration) this.playing = this.wantPlaying = false;
      this.emit();
      this.arm();
    } catch (error) {
      if (epoch === this.epoch && !this.closed) this.fail(error);
    }
  }
  play() {
    if (this.closed) return;
    this.wantPlaying = true;
    if (this.loading) return;
    if (this.position >= this.duration && this.duration > 0) return this.seek(0);
    this.playing = true;
    this.anchorPosition = this.position;
    this.anchorTime = this.now();
    this.emit();
    this.arm();
  }
  async pause() {
    this.position = this.current();
    this.wantPlaying = this.playing = false;
    this.cancel(this.timer);
    const epoch = this.epoch;
    try {
      if (!this.loading) await this.enqueue(()=>this.renderThrough(this.origin + this.position, epoch));
    } catch (error) {
      if (epoch === this.epoch && !this.closed) this.fail(error);
    }
    if (epoch === this.epoch && !this.closed) this.emit();
  }
  setSpeed(speed) {
    if (![1,2,4,8].includes(speed)) return;
    this.position = this.current();
    this.speed = speed;
    this.anchorPosition = this.position;
    this.anchorTime = this.now();
    this.emit();
  }
  seek(position) {
    // The time origin is unknown until the first complete frame is decoded.
    // A stale control event must not invalidate that initialization.
    if (!this.ready || this.closed) return Promise.resolve();
    this.position = Math.max(0, Math.min(this.duration, Number(position) || 0));
    this.playing = false;
    this.loading = true;
    this.cancel(this.timer);
    const epoch = ++this.epoch, target = this.position;
    this.controller.abort();
    this.controller = new AbortController();
    this.emit();
    return this.enqueue(async () => {
      if (epoch !== this.epoch || this.closed) return;
      const location = await this.source.seek(this.origin + target, this.controller.signal);
      if (epoch !== this.epoch || this.closed) return;
      this.reset(location.held || {});
      this.floor = location.at || 0;
      await this.renderThrough(this.origin + target, epoch);
      if (epoch !== this.epoch || this.closed) return;
      this.loading = false;
      if (this.position >= this.duration) this.wantPlaying = false;
      this.emit();
      if (this.wantPlaying) this.play();
    }).catch(error => {
      if (epoch === this.epoch && !this.closed) this.fail(error);
    });
  }
  fail(error) {
    this.close();
    this.error(error);
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.playing = this.wantPlaying = false;
    this.epoch++;
    this.controller.abort();
    this.cancel(this.timer);
    this.source.close();
  }
}

// Keep actor ownership when restoring held keys from a seek snapshot.
class ReplayKeys {
  constructor(container, {glyphs, arrows, colorOf}) {
    Object.assign(this, {container, glyphs, arrows, colorOf});
    this.held = new Map();
    this.actor = '';
  }
  reset(held = {}) {
    this.held = new Map(Object.entries(held));
    this.actor = '';
    this.render();
  }
  apply(event) {
    if (!event.key) return;
    if (event.who) this.actor = event.who;
    if (event.down) this.held.set(event.key, event.who || this.actor);
    else this.held.delete(event.key);
    this.render();
  }
  render() {
    const groups = new Map();
    for (const [key, actor] of this.held) {
      if (!groups.has(actor)) groups.set(actor, []);
      groups.get(actor).push(key);
    }
    if (this.actor && !groups.has(this.actor)) groups.set(this.actor, []);
    this.container.replaceChildren();
    const document = this.container.ownerDocument;
    for (const [actor, keys] of groups) {
      if (actor) {
        const who = document.createElement('span');
        who.textContent = actor;
        who.style.color = this.colorOf(actor);
        who.style.marginRight = '6px';
        this.container.appendChild(who);
      }
      for (const key of keys) {
        const chip = document.createElement('span');
        chip.className = 'k' + (this.arrows.has(key) ? ' arrow' : '');
        chip.textContent = this.glyphs[key] ?? key;
        this.container.appendChild(chip);
      }
    }
  }
}
if (typeof module !== 'undefined') module.exports = {ReplayPlayer, ReplayKeys};
