// Live grid: configurable layout, hide/reorder cameras, 24h recording bar per tile.
import { VideoRTC } from '../vendor/video-rtc.js';
import { api, qs } from './api.js';
import { applyI18n, t } from './i18n.js';
import { hevcSupported } from './media.js';
import { TimelineBar } from './timeline.js';

class NvrLive extends VideoRTC {
  oninit() {
    super.oninit();
    this.video.controls = false;
    this.video.muted = true;
  }
}
if (!customElements.get('nvr-live')) customElements.define('nvr-live', NvrLive);

const LAYOUTS = [1, 4, 9, 16];

export class LiveView {
  constructor(root, app) {
    this.root = root;
    this.app = app;
    this.page = 0;
    this.focus = null;
    this.bars = new Map();
    this.root.innerHTML = `
      <div class="toolbar">
        <div class="seg" role="group" aria-label="layout">
          ${LAYOUTS.map(n => `<button type="button" class="btn" data-layout="${n}">${n === 1 ? '1' : Math.sqrt(n) + '×' + Math.sqrt(n)}</button>`).join('')}
        </div>
        <button type="button" class="btn" data-act="panel"><span data-i18n="live.cameras"></span></button>
        <div class="pager" hidden><button type="button" class="btn icon" data-page="-1">‹</button>
          <span class="pager-label"></span><button type="button" class="btn icon" data-page="1">›</button></div>
        <span class="spacer"></span>
        <div class="legend"><i class="lg rec"></i><span data-i18n="legend.recorded"></span>
          <i class="lg gap"></i><span data-i18n="legend.gap"></span><i class="lg mot"></i><span data-i18n="legend.motion"></span></div>
      </div>
      <aside class="side-panel" hidden>
        <div class="row"><h3 data-i18n="live.panel_title"></h3><span class="spacer"></span>
          <button type="button" class="btn icon ghost" data-act="panel-close" aria-label="✕">✕</button></div>
        <p class="hint" data-i18n="live.panel_hint"></p>
        <ul class="cam-list"></ul>
      </aside>
      <div class="grid"></div>
      <div class="empty" hidden data-i18n="live.no_cameras"></div>`;
    applyI18n(this.root);
    this.grid = this.root.querySelector('.grid');
    this.panel = this.root.querySelector('.side-panel');
    this.root.querySelectorAll('[data-layout]').forEach(b => b.addEventListener('click', () => {
      this.app.prefs.layout = Number(b.dataset.layout);
      this.page = 0;
      this.app.savePrefs();
      this.render();
    }));
    this.root.querySelector('[data-act="panel"]').addEventListener('click', () => {
      this.panel.hidden = !this.panel.hidden;
      this.renderPanel();
    });
    this.panel.querySelector('[data-act="panel-close"]').addEventListener('click', () => { this.panel.hidden = true; });
    document.addEventListener('pointerdown', ev => {
      if (!this.panel.hidden && !this.panel.contains(ev.target) && !ev.target.closest('[data-act="panel"]')) this.panel.hidden = true;
    });
    this.root.querySelectorAll('[data-page]').forEach(b => b.addEventListener('click', () => {
      this.page += Number(b.dataset.page);
      this.render();
    }));
  }

  orderedCameras() {
    const cams = this.app.config.cameras;
    const order = this.app.prefs.order || [];
    const pos = id => { const i = order.indexOf(id); return i < 0 ? 1000 + cams.findIndex(c => c.id === id) : i; };
    return [...cams].sort((a, b) => pos(a.id) - pos(b.id));
  }

  visibleCameras() {
    const hidden = new Set(this.app.prefs.hidden || []);
    return this.orderedCameras().filter(c => !hidden.has(c.id));
  }

  renderPanel() {
    const ul = this.panel.querySelector('.cam-list');
    const hidden = new Set(this.app.prefs.hidden || []);
    const cams = this.orderedCameras();
    ul.innerHTML = '';
    cams.forEach((c, i) => {
      const li = document.createElement('li');
      li.innerHTML = `<label><input type="checkbox" ${hidden.has(c.id) ? '' : 'checked'}> <span></span></label>
        <button type="button" class="btn icon" data-mv="-1" ${i === 0 ? 'disabled' : ''} aria-label="↑">↑</button>
        <button type="button" class="btn icon" data-mv="1" ${i === cams.length - 1 ? 'disabled' : ''} aria-label="↓">↓</button>`;
      li.querySelector('span').textContent = c.name;
      li.querySelector('input').addEventListener('change', ev => {
        const set = new Set(this.app.prefs.hidden || []);
        ev.target.checked ? set.delete(c.id) : set.add(c.id);
        this.app.prefs.hidden = [...set];
        this.app.savePrefs();
        this.render();
      });
      li.querySelectorAll('[data-mv]').forEach(b => b.addEventListener('click', () => this.move(c.id, Number(b.dataset.mv))));
      ul.appendChild(li);
    });
  }

  move(id, delta) {
    const ids = this.orderedCameras().map(c => c.id);
    const i = ids.indexOf(id), j = i + delta;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    this.app.prefs.order = ids;
    this.app.savePrefs();
    this.renderPanel();
    this.render();
  }

  moveTo(id, targetId) {
    const ids = this.orderedCameras().map(c => c.id);
    const from = ids.indexOf(id);
    ids.splice(from, 1);
    ids.splice(ids.indexOf(targetId) + (from <= ids.indexOf(targetId) ? 1 : 0), 0, id);
    this.app.prefs.order = ids;
    this.app.savePrefs();
    this.render();
  }

  show() {
    this.active = true;
    this.render();
    this.refreshCoverage();
    this.covTimer = setInterval(() => this.refreshCoverage(), 60000);
  }

  hide() {
    this.active = false;
    clearInterval(this.covTimer);
    this.grid.innerHTML = '';
    this.bars.clear();
  }

  render() {
    if (!this.active) return;
    const layout = this.app.prefs.layout || 9;
    this.root.querySelectorAll('[data-layout]').forEach(b =>
      b.classList.toggle('active', Number(b.dataset.layout) === layout && !this.focus));
    let cams = this.visibleCameras();
    this.root.querySelector('.empty').hidden = cams.length > 0;
    const pager = this.root.querySelector('.pager');
    let perPage = layout;
    if (this.focus) {
      cams = this.app.config.cameras.filter(c => c.id === this.focus);
      perPage = 1;
      pager.hidden = true;
    } else {
      const pages = Math.max(1, Math.ceil(cams.length / perPage));
      this.page = Math.min(Math.max(0, this.page), pages - 1);
      pager.hidden = pages <= 1;
      pager.querySelector('.pager-label').textContent = `${t('live.page')} ${this.page + 1}/${pages}`;
      cams = cams.slice(this.page * perPage, (this.page + 1) * perPage);
    }
    const cols = this.focus ? 1 : Math.min(Math.ceil(Math.sqrt(perPage)), Math.max(1, cams.length));
    this.grid.style.setProperty('--cols', cols);
    this.grid.style.setProperty('--cols-m', Math.min(cols, 2));
    this.grid.classList.toggle('focus', !!this.focus);

    // Keep existing tiles (and their running streams) when possible
    const wanted = cams.map(c => c.id + (this.focus ? ':main' : ':sub'));
    const existing = new Map([...this.grid.children].map(el => [el.dataset.key, el]));
    for (const [key, el] of existing) if (!wanted.includes(key)) { el.remove(); this.bars.delete(key.split(':')[0]); }
    cams.forEach((cam, i) => {
      const key = wanted[i];
      let tile = existing.get(key);
      if (!tile) tile = this.createTile(cam, !!this.focus);
      if (this.grid.children[i] !== tile) this.grid.insertBefore(tile, this.grid.children[i] || null);
    });
    this.updateStatus();
  }

  createTile(cam, main) {
    const tile = document.createElement('div');
    tile.className = 'tile';
    tile.dataset.key = cam.id + (main ? ':main' : ':sub');
    tile.dataset.cam = cam.id;
    tile.innerHTML = `
      <div class="tile-video"></div>
      <div class="tile-top" draggable="${main ? 'false' : 'true'}">
        <span class="dot" aria-hidden="true"></span><span class="name"></span>
        <span class="badge motion" hidden data-i18n="motion"></span>
        <span class="spacer"></span>
        ${main && cam.audio ? '<button type="button" class="btn icon ghost" data-act="audio" data-i18n-title="live.unmute">🔇</button>' : ''}
        <button type="button" class="btn icon ghost" data-act="rec" data-i18n-title="live.open_recording">⏪</button>
        <button type="button" class="btn icon ghost" data-act="focus" data-i18n-title="${main ? 'live.back' : 'live.fullscreen'}">${main ? '✕' : '⤢'}</button>
      </div>
      <div class="tile-bar" data-i18n-title="live.last24"></div>`;
    tile.querySelector('.name').textContent = cam.name;
    applyI18n(tile);
    const player = document.createElement('nvr-live');
    player.mode = this.app.config.webrtc ? 'webrtc,mse,hls,mjpeg' : 'mse,hls,mjpeg';
    player.media = main ? 'video,audio' : 'video';
    tile.querySelector('.tile-video').appendChild(player);
    // Browsers without H.265 support get the H.264 sub stream in the detail view too
    const st = this.app.status && this.app.status.cameras[cam.id];
    const mainOk = !(st && st.codec === 'hevc') || hevcSupported();
    player.src = '/live/api/ws?' + qs({ src: main && mainOk ? cam.id : cam.id + '_sub' });

    const bar = new TimelineBar(tile.querySelector('.tile-bar'), {
      ticks: false, height: 10,
      onSeek: (ts, final) => { if (final) this.app.openPlayback(cam.id, ts); },
    });
    this.bars.set(cam.id, bar);
    if (this.lastCoverage && this.lastCoverage.cameras[cam.id]) {
      const cv = this.lastCoverage;
      bar.setRange(cv.start, cv.end);
      bar.setData(cv.cameras[cam.id].intervals, cv.cameras[cam.id].events, cv.now);
    }

    tile.querySelector('[data-act="focus"]').addEventListener('click', () => {
      this.focus = main ? null : cam.id;
      this.render();
    });
    tile.querySelector('.tile-video').addEventListener('dblclick', () => {
      this.focus = main ? null : cam.id;
      this.render();
    });
    tile.querySelector('[data-act="rec"]').addEventListener('click', () =>
      this.app.openPlayback(cam.id, Date.now() / 1000 - 300));
    const audioBtn = tile.querySelector('[data-act="audio"]');
    if (audioBtn) audioBtn.addEventListener('click', () => {
      const v = player.video;
      v.muted = !v.muted;
      if (!v.muted) v.play().catch(() => {});
      audioBtn.textContent = v.muted ? '🔇' : '🔊';
      audioBtn.title = t(v.muted ? 'live.unmute' : 'live.mute');
    });
    const top = tile.querySelector('.tile-top');
    top.addEventListener('dragstart', ev => { ev.dataTransfer.setData('text/plain', cam.id); tile.classList.add('dragging'); });
    top.addEventListener('dragend', () => tile.classList.remove('dragging'));
    tile.addEventListener('dragover', ev => ev.preventDefault());
    tile.addEventListener('drop', ev => {
      ev.preventDefault();
      const id = ev.dataTransfer.getData('text/plain');
      if (id && id !== cam.id) this.moveTo(id, cam.id);
    });
    return tile;
  }

  async refreshCoverage() {
    if (!this.active) return;
    const end = Date.now() / 1000;
    const start = end - 86400;
    try {
      const cv = await api('/api/coverage?' + qs({ start: Math.floor(start), end: Math.ceil(end) }));
      this.lastCoverage = cv;
      for (const [id, bar] of this.bars) {
        const d = cv.cameras[id];
        if (!d) continue;
        bar.setRange(cv.start, cv.end);
        bar.setData(d.intervals, d.events, cv.now);
      }
    } catch (e) { /* retry next tick */ }
  }

  updateStatus() {
    const st = this.app.status;
    if (!st) return;
    for (const tile of this.grid.children) {
      const s = st.cameras[tile.dataset.cam];
      if (!s) continue;
      const dot = tile.querySelector('.dot');
      dot.className = 'dot ' + s.state;
      dot.title = t('state.' + s.state) + (s.last_error ? ' – ' + s.last_error : '');
      tile.querySelector('.badge.motion').hidden = !s.motion;
    }
  }
}
