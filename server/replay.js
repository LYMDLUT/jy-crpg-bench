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
    this.playing = this.wantPlaying = this.loading = this.closed = false;
  }
  current() {
    return Math.min(this.duration, this.playing
      ? this.anchorPosition + (this.now() - this.anchorTime) / 1000 * this.speed : this.position);
  }
  emit() {
    this.update({position:this.position, duration:this.duration, playing:this.wantPlaying,
                 loading:this.loading, speed:this.speed});
  }
  enqueue(work) {
    this.queue = this.queue.catch(()=>{}).then(work);
    return this.queue;
  }
  async start() {
    const epoch = this.epoch;
    let prefixTime = 0;
    this.reset({});
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
      this.emit();
      this.play();
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
if (typeof module !== 'undefined') module.exports = {ReplayPlayer};
