// Recording playback: calendar + time range, timeline with gaps and motion,
// speeds 1–8×, frame stepping, jog wheel, snapshot and MP4 export.
import { api, qs } from './api.js';
import { Calendar } from './calendar.js';
import { applyI18n, fmtDateTime, locale, t } from './i18n.js';
import { JogWheel } from './jog.js';
import { hevcSupported } from './media.js';
import { TimelineBar } from './timeline.js';

const SPEEDS = [1, 2, 3, 4, 8];
const JOG_STEPS = [[2, '2 s'], [30, '30 s'], [300, '5 min']];

function pad(n) { return String(n).padStart(2, '0'); }
function timeInput(d) { return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; }
function dayStart(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
function atTime(day, hms) {
  const [h, m, s] = (hms || '00:00:00').split(':').map(Number);
  return new Date(day.getFullYear(), day.getMonth(), day.getDate(), h || 0, m || 0, s || 0);
}
function localInput(ts) {
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${timeInput(d)}`;
}

export class PlaybackView {
  constructor(root, app) {
    this.root = root;
    this.app = app;
    this.speed = 1;
    this.segments = [];
    this.hls = null;
    this.compat = false;
    this.pendingSeek = null;
    this.marks = [null, null];
    this.frameDur = 1 / 15;
    this.jogStep = 0;
    this.day = dayStart(new Date());
    this.build();
  }

  build() {
    this.root.innerHTML = `
      <form class="pb-controls card">
        <label><span data-i18n="pb.camera"></span><select class="pb-cam"></select></label>
        <div class="field cal-wrap"><span data-i18n="pb.date"></span><button type="button" class="btn pb-date"></button></div>
        <label><span data-i18n="pb.from"></span><input type="time" step="1" class="pb-from" required></label>
        <label><span data-i18n="pb.to"></span><input type="time" step="1" class="pb-to" required></label>
        <button type="submit" class="btn primary" data-i18n="pb.show"></button>
        <button type="button" class="btn" data-act="lasthour" data-i18n="pb.last_hour"></button>
        <button type="button" class="btn" data-act="day" data-i18n="pb.day"></button>
      </form>
      <div class="pb-stage">
        <div class="pb-video-wrap">
          <video playsinline preload="auto"></video>
          <div class="pb-clock">--</div>
          <div class="pb-msg" hidden></div>
          <div class="pb-compat" hidden data-i18n="pb.compat"></div>
        </div>
      </div>
      <div class="pb-bars">
        <div class="pb-day-bar"></div>
        <div class="pb-range-bar"></div>
      </div>
      <div class="pb-transport">
        <div class="grp">
          <button type="button" class="btn icon" data-act="back" data-i18n-title="pb.frame_back">⏮</button>
          <button type="button" class="btn icon primary big" data-act="play" data-i18n-title="pb.play">▶</button>
          <button type="button" class="btn icon" data-act="fwd" data-i18n-title="pb.frame_fwd">⏭</button>
        </div>
        <div class="grp speeds" role="group" data-i18n-title="pb.speed">
          ${SPEEDS.map(s => `<button type="button" class="btn" data-speed="${s}">${s}×</button>`).join('')}
        </div>
        <div class="jog-wrap" data-i18n-title="pb.jog"></div>
        <div class="grp">
          <button type="button" class="btn icon" data-act="mute" data-i18n-title="pb.mute">🔇</button>
          <button type="button" class="btn" data-act="in" data-i18n-title="pb.mark_in">[</button>
          <button type="button" class="btn" data-act="out" data-i18n-title="pb.mark_out">]</button>
          <button type="button" class="btn icon" data-act="snap" data-i18n-title="pb.snapshot">📷</button>
          <button type="button" class="btn" data-act="export"><span data-i18n="pb.export"></span></button>
        </div>
      </div>
      <dialog class="export-dlg">
        <form method="dialog" class="stack">
          <h3 data-i18n="pb.export_title"></h3>
          <label><span data-i18n="pb.from"></span><input type="datetime-local" step="1" class="ex-from" required></label>
          <label><span data-i18n="pb.to"></span><input type="datetime-local" step="1" class="ex-to" required></label>
          <label class="row"><input type="checkbox" class="ex-h264"> <span data-i18n="pb.export_h264"></span></label>
          <p class="ex-msg hint"></p>
          <div class="row end">
            <button type="button" class="btn" value="cancel" data-act="ex-cancel" data-i18n="pb.cancel"></button>
            <button type="button" class="btn primary" data-act="ex-go" data-i18n="pb.export_go"></button>
          </div>
        </form>
      </dialog>`;
    applyI18n(this.root);
    const $ = s => this.root.querySelector(s);
    this.video = $('video');
    this.clock = $('.pb-clock');
    this.msg = $('.pb-msg');
    this.camSel = $('.pb-cam');
    this.fromIn = $('.pb-from');
    this.toIn = $('.pb-to');
    this.dateBtn = $('.pb-date');
    this.playBtn = $('[data-act="play"]');
    this.muteBtn = $('[data-act="mute"]');

    for (const c of this.app.config.cameras) {
      const o = document.createElement('option');
      o.value = c.id;
      o.textContent = c.name;
      this.camSel.appendChild(o);
    }
    this.calendar = new Calendar(this.dateBtn, {
      getCamera: () => this.camSel.value,
      onPick: d => { this.day = d; this.updateDateLabel(); this.applyForm(); },
    });

    this.dayBar = new TimelineBar($('.pb-day-bar'), {
      ticks: true, height: 30,
      onSeek: (ts, final) => {
        if (!final) return;
        if (ts >= this.start && ts <= this.end) this.seekWall(ts);
        else {
          const ds = dayStart(this.day).getTime() / 1000;
          const s = Math.max(ds, ts - 1800);
          this.load(this.camSel.value, s, s + 3600, ts);
        }
      },
    });
    this.rangeBar = new TimelineBar($('.pb-range-bar'), {
      ticks: true, height: 46,
      onSeek: (ts, final) => this.scrubWall(ts, final),
    });

    this.jog = new JogWheel($('.jog-wrap'), {
      onStart: () => { this.jogWasPlaying = !this.video.paused; this.stopEmulation(); this.video.pause(); },
      onDelta: sec => this.nudge(sec),
      onEnd: () => { if (this.jogWasPlaying) this.play(); },
    });
    this.jog.center.addEventListener('click', () => this.setJogStep((this.jogStep + 1) % JOG_STEPS.length));
    this.setJogStep(0);

    $('form.pb-controls').addEventListener('submit', ev => { ev.preventDefault(); this.applyForm(); });
    $('[data-act="lasthour"]').addEventListener('click', () => {
      const now = Date.now() / 1000;
      this.day = dayStart(new Date());
      this.load(this.camSel.value, now - 3600, now, now - 3600);
    });
    $('[data-act="day"]').addEventListener('click', () => {
      const s = dayStart(this.day).getTime() / 1000;
      this.load(this.camSel.value, s, s + 86400, s);
    });
    this.camSel.addEventListener('change', () => this.load(this.camSel.value, this.start, this.end, this.currentWall()));
    this.playBtn.addEventListener('click', () => (this.video.paused && !this.emuTimer ? this.play() : this.pause()));
    $('[data-act="back"]').addEventListener('click', () => this.step(-1));
    $('[data-act="fwd"]').addEventListener('click', () => this.step(1));
    this.root.querySelectorAll('[data-speed]').forEach(b =>
      b.addEventListener('click', () => this.setSpeed(Number(b.dataset.speed))));
    this.muteBtn.addEventListener('click', () => {
      this.video.muted = !this.video.muted;
      this.muteBtn.textContent = this.video.muted ? '🔇' : '🔊';
    });
    $('[data-act="in"]').addEventListener('click', () => this.setMark(0));
    $('[data-act="out"]').addEventListener('click', () => this.setMark(1));
    $('[data-act="snap"]').addEventListener('click', () => this.snapshot());
    $('[data-act="export"]').addEventListener('click', () => this.openExport());
    $('[data-act="ex-cancel"]').addEventListener('click', () => $('.export-dlg').close());
    $('[data-act="ex-go"]').addEventListener('click', () => this.doExport());

    const v = this.video;
    v.muted = true;
    v.addEventListener('play', () => this.syncPlayBtn());
    v.addEventListener('pause', () => this.syncPlayBtn());
    v.addEventListener('seeked', () => this.flushSeek());
    v.addEventListener('ratechange', () => this.syncSpeedBtns());
    v.addEventListener('waiting', () => this.root.classList.add('buffering'));
    v.addEventListener('playing', () => this.root.classList.remove('buffering'));
    v.addEventListener('ended', () => this.pause());
    if ('requestVideoFrameCallback' in HTMLVideoElement.prototype) {
      let lastMedia = null;
      const onFrame = (now, meta) => {
        if (lastMedia != null && v.playbackRate === 1) {
          const d = meta.mediaTime - lastMedia;
          if (d > 0.01 && d < 0.5) this.frameDur = this.frameDur * 0.9 + d * 0.1;
        }
        lastMedia = meta.mediaTime;
        v.requestVideoFrameCallback(onFrame);
      };
      v.requestVideoFrameCallback(onFrame);
    }
    document.addEventListener('keydown', ev => this.onKey(ev));
    this.updateDateLabel();
    this.syncSpeedBtns();
  }

  // ---------------------------------------------------------------- range
  updateDateLabel() {
    this.dateBtn.textContent = this.day.toLocaleDateString(locale(), { weekday: 'short', day: 'numeric', month: 'numeric', year: 'numeric' });
    this.calendar.setSelected(this.day);
  }

  applyForm() {
    const s = atTime(this.day, this.fromIn.value || '00:00:00');
    let e = atTime(this.day, this.toIn.value || '23:59:59');
    if (e <= s) e = new Date(e.getTime() + 86400000);
    this.load(this.camSel.value, s.getTime() / 1000, e.getTime() / 1000, s.getTime() / 1000);
  }

  show() {
    this.active = true;
    if (!this.start) {
      const now = Date.now() / 1000;
      this.load(this.camSel.value, now - 3600, now, now - 3600);
    }
    this.tick();
  }

  hide() {
    this.active = false;
    this.pause();
  }

  open(cam, ts) {
    this.camSel.value = cam;
    const now = Date.now() / 1000;
    const end = Math.min(now, ts + 1800);
    this.load(cam, end - 3600, end, ts);
  }

  async load(cam, start, end, playAt) {
    this.camSel.value = cam;
    this.start = Math.floor(start);
    this.end = Math.ceil(end);
    this.day = dayStart(new Date(this.start * 1000));
    this.updateDateLabel();
    this.fromIn.value = timeInput(new Date(this.start * 1000));
    this.toIn.value = timeInput(new Date(this.end * 1000));
    this.rangeBar.setRange(this.start, this.end);
    const ds = this.day.getTime() / 1000;
    this.dayBar.setRange(ds, ds + 86400);
    this.dayBar.setHighlight(this.start, this.end);
    this.marks = [null, null];
    this.rangeBar.setMarks(null, null);
    this.showMsg(t('pb.loading'));
    const token = this.loadToken = Symbol('load');
    this.destroyEngine();
    this.refreshCoverage();
    let idx;
    try {
      idx = await api(`/api/playback/${cam}/index?` + qs({ start: this.start, end: this.end }));
    } catch (e) {
      this.showMsg(t('err.network'));
      return;
    }
    if (token !== this.loadToken) return;
    this.segments = idx.segments;
    if (!this.segments.length) {
      this.showMsg(t('pb.no_recording'));
      this.clock.textContent = '--';
      return;
    }
    this.showMsg(null);
    this.compat = idx.codec === 'hevc' && !hevcSupported() &&
      !(this.video.canPlayType('application/vnd.apple.mpegurl') && !window.Hls?.isSupported());
    this.startEngine(this.mediaFromWall(playAt ?? this.start));
  }

  async refreshCoverage() {
    const cam = this.camSel.value;
    const ds = this.day.getTime() / 1000;
    try {
      const cv = await api('/api/coverage?' + qs({ start: ds, end: ds + 86400, cams: cam }));
      const d = cv.cameras[cam];
      this.dayBar.setData(d.intervals, d.events, cv.now);
      this.rangeBar.setData(d.intervals, d.events, cv.now);
    } catch (e) { /* ignore */ }
  }

  showMsg(text) {
    this.msg.hidden = !text;
    this.msg.textContent = text || '';
  }

  // --------------------------------------------------------------- engine
  playlistUrl() {
    return `/api/playback/${this.camSel.value}/playlist.m3u8?` +
      qs({ start: this.start, end: this.end, tc: this.compat ? 1 : undefined });
  }

  startEngine(startMedia) {
    const v = this.video;
    this.root.querySelector('.pb-compat').hidden = !this.compat;
    const Hls = window.Hls;
    if (Hls && Hls.isSupported()) {
      const hls = new Hls({
        startPosition: startMedia,
        maxBufferLength: 30 * this.speed,
        maxMaxBufferLength: 600,
        backBufferLength: 120,
        enableWorker: true,
      });
      this.hls = hls;
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR && !this.compat) {
          // Usually the browser cannot decode H.265 -> switch to H.264 transcode
          const pos = v.currentTime || startMedia;
          this.compat = true;
          this.destroyEngine();
          this.startEngine(pos);
        } else if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          setTimeout(() => hls.startLoad(), 2000);
        } else {
          hls.recoverMediaError();
        }
      });
      hls.loadSource(this.playlistUrl());
      hls.attachMedia(v);
      hls.once(Hls.Events.MANIFEST_PARSED, () => this.play());
    } else {
      v.src = this.playlistUrl();
      v.addEventListener('loadedmetadata', () => { v.currentTime = startMedia; this.play(); }, { once: true });
    }
  }

  destroyEngine() {
    this.stopEmulation();
    if (this.hls) { this.hls.destroy(); this.hls = null; }
    this.video.removeAttribute('src');
    this.video.load();
    this.pendingSeek = null;
  }

  // -------------------------------------------------------------- mapping
  findSeg(media) {
    const s = this.segments;
    let lo = 0, hi = s.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (s[mid][2] <= media) lo = mid; else hi = mid - 1;
    }
    return s[lo];
  }

  wallFromMedia(media) {
    if (!this.segments.length) return null;
    const seg = this.findSeg(media);
    return seg[0] + Math.min(seg[1], Math.max(0, media - seg[2]));
  }

  mediaFromWall(wall) {
    const s = this.segments;
    if (!s.length) return 0;
    for (const [start, dur, off] of s) {
      if (wall < start) return off;             // inside a gap -> next recording
      if (wall < start + dur) return off + (wall - start);
    }
    const last = s[s.length - 1];
    return last[2] + last[1] - 0.1;
  }

  mediaEnd() {
    const last = this.segments[this.segments.length - 1];
    return last ? last[2] + last[1] : 0;
  }

  currentWall() {
    const m = this.pendingSeek ?? this.video.currentTime;
    return this.wallFromMedia(m) ?? this.start;
  }

  // -------------------------------------------------------------- control
  play() {
    if (this.emulating()) return;
    this.video.playbackRate = this.speed;
    const p = this.video.play();
    if (p) p.catch(() => { this.video.muted = true; this.muteBtn.textContent = '🔇'; this.video.play().catch(() => {}); });
    if (this.speed > 1 && Math.abs(this.video.playbackRate - this.speed) > 0.01) this.startEmulation();
  }

  pause() {
    this.stopEmulation();
    this.video.pause();
    this.syncPlayBtn();
  }

  syncPlayBtn() {
    const playing = !this.video.paused || !!this.emuTimer;
    this.playBtn.textContent = playing ? '⏸' : '▶';
    this.playBtn.title = t(playing ? 'pb.pause' : 'pb.play');
  }

  setSpeed(rate) {
    this.speed = rate;
    if (this.hls) this.hls.config.maxBufferLength = Math.min(600, 30 * rate);
    const wasPlaying = !this.video.paused || this.emulating();
    this.stopEmulation();
    this.video.playbackRate = rate;
    if (wasPlaying) this.play();
    this.syncSpeedBtns();
  }

  syncSpeedBtns() {
    this.root.querySelectorAll('[data-speed]').forEach(b =>
      b.classList.toggle('active', Number(b.dataset.speed) === this.speed));
  }

  // Some mobile browsers cap playbackRate; emulate fast forward by seeking.
  emulating() { return !!this.emuTimer; }
  startEmulation() {
    this.video.pause();
    this.emuTimer = setInterval(() => this.nudge(this.speed * 0.25), 250);
    this.syncPlayBtn();
  }
  stopEmulation() {
    if (this.emuTimer) { clearInterval(this.emuTimer); this.emuTimer = 0; this.syncPlayBtn(); }
  }

  step(frames) {
    this.pause();
    this.nudge(frames * this.frameDur);
  }

  nudge(sec) {
    const base = this.pendingSeek ?? this.video.currentTime;
    this.requestSeek(Math.min(this.mediaEnd() - 0.05, Math.max(0, base + sec)));
  }

  requestSeek(media) {
    this.pendingSeek = media;
    if (!this.video.seeking) this.flushSeek();
  }

  flushSeek() {
    if (this.pendingSeek == null) return;
    const m = this.pendingSeek;
    this.pendingSeek = null;
    if (Math.abs(this.video.currentTime - m) > 0.001) this.video.currentTime = m;
  }

  seekWall(wall) {
    if (wall < this.start || wall > this.end) {
      const len = this.end - this.start;
      this.load(this.camSel.value, wall - len / 2, wall + len / 2, wall);
      return;
    }
    this.requestSeek(this.mediaFromWall(wall));
  }

  scrubWall(wall, final) {
    if (!final) {
      if (!this.scrubbing) { this.scrubbing = true; this.scrubWasPlaying = !this.video.paused; this.video.pause(); }
      this.requestSeek(this.mediaFromWall(wall));
      return;
    }
    this.requestSeek(this.mediaFromWall(wall));
    if (this.scrubbing) {
      this.scrubbing = false;
      if (this.scrubWasPlaying) this.play();
    }
  }

  setJogStep(i) {
    this.jogStep = i;
    const [sec, label] = JOG_STEPS[i];
    this.jog.secondsPerTurn = sec;
    this.jog.setLabel(label, `${t('pb.jog')} (${i === 0 ? t('pb.jog_fine') : t('pb.jog_coarse')})`);
  }

  setMark(i) {
    this.marks[i] = this.currentWall();
    if (this.marks[0] != null && this.marks[1] != null && this.marks[1] < this.marks[0]) this.marks.reverse();
    this.rangeBar.setMarks(this.marks[0], this.marks[1]);
  }

  tick() {
    if (!this.active) return;
    if (this.segments.length) {
      const wall = this.currentWall();
      this.clock.textContent = fmtDateTime(wall);
      this.rangeBar.setPlayhead(wall);
      this.dayBar.setPlayhead(wall);
    }
    requestAnimationFrame(() => this.tick());
  }

  onKey(ev) {
    if (!this.active || ev.target.closest('input, select, textarea, dialog')) return;
    if (ev.key === ' ') { ev.preventDefault(); this.playBtn.click(); }
    else if (ev.key === 'ArrowLeft' && !ev.target.closest('.timeline')) { ev.preventDefault(); this.video.paused ? this.step(-1) : this.nudge(-5); }
    else if (ev.key === 'ArrowRight' && !ev.target.closest('.timeline')) { ev.preventDefault(); this.video.paused ? this.step(1) : this.nudge(5); }
    else if (ev.key >= '1' && ev.key <= '5') this.setSpeed(SPEEDS[Number(ev.key) - 1]);
  }

  // ------------------------------------------------------- snapshot/export
  fileStamp(ts) {
    const d = new Date(ts * 1000);
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  }

  snapshot() {
    const v = this.video;
    if (!v.videoWidth) return;
    const c = document.createElement('canvas');
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext('2d').drawImage(v, 0, 0);
    c.toBlob(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${this.camSel.value}_${this.fileStamp(this.currentWall())}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    }, 'image/png');
  }

  openExport() {
    const dlg = this.root.querySelector('.export-dlg');
    const [a, b] = this.marks;
    const cur = this.currentWall();
    const from = a ?? (b != null ? b - 60 : cur);
    const to = b ?? Math.min(this.end, from + 300);
    dlg.querySelector('.ex-from').value = localInput(from);
    dlg.querySelector('.ex-to').value = localInput(to);
    dlg.querySelector('.ex-msg').textContent = '';
    dlg.showModal();
  }

  async doExport() {
    const dlg = this.root.querySelector('.export-dlg');
    const msg = dlg.querySelector('.ex-msg');
    const from = new Date(dlg.querySelector('.ex-from').value).getTime() / 1000;
    const to = new Date(dlg.querySelector('.ex-to').value).getTime() / 1000;
    if (!(to > from)) { msg.textContent = t('pb.export_failed'); return; }
    const params = { cam: this.camSel.value, start: Math.floor(from), end: Math.ceil(to),
      h264: dlg.querySelector('.ex-h264').checked ? 1 : undefined };
    try {
      const idx = await api(`/api/playback/${params.cam}/index?` + qs({ start: params.start, end: params.end }));
      if (!idx.segments.length) { msg.textContent = t('pb.no_recording'); return; }
    } catch (e) { msg.textContent = t('pb.export_failed') + ': ' + (e.detail || e.message); return; }
    msg.textContent = t('pb.export_wait');
    const a = document.createElement('a');
    a.href = '/api/export?' + qs(params);
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => dlg.close(), 1500);
  }
}
