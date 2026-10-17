// Canvas timeline: recorded intervals, gaps, motion events, playhead and ticks.
import { fmtTime } from './i18n.js';

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const TICK_STEPS = [60, 300, 600, 900, 1800, 3600, 7200, 10800, 21600];

export class TimelineBar {
  constructor(el, opts = {}) {
    this.el = el;
    this.opts = { ticks: true, interactive: true, height: 34, ...opts };
    this.start = 0;
    this.end = 1;
    this.now = Date.now() / 1000;
    this.intervals = [];
    this.events = [];
    this.playhead = null;
    this.marks = [null, null];
    this.highlight = null;
    this.hover = null;
    el.classList.add('timeline');
    this.canvas = document.createElement('canvas');
    el.appendChild(this.canvas);
    this.tip = document.createElement('div');
    this.tip.className = 'timeline-tip';
    el.appendChild(this.tip);
    new ResizeObserver(() => this.draw()).observe(el);
    if (this.opts.interactive) this._bind();
  }

  setRange(start, end) { this.start = start; this.end = end; this.draw(); }
  setData(intervals, events, now) {
    this.intervals = intervals || [];
    this.events = events || [];
    if (now) this.now = now;
    this.draw();
  }
  setPlayhead(ts) { this.playhead = ts; this.draw(); }
  setMarks(a, b) { this.marks = [a, b]; this.draw(); }
  setHighlight(a, b) { this.highlight = a == null ? null : [a, b]; this.draw(); }

  tsAt(clientX) {
    const r = this.canvas.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    return this.start + f * (this.end - this.start);
  }

  _bind() {
    const c = this.canvas;
    this.el.tabIndex = 0;
    this.el.setAttribute('role', 'slider');
    let dragging = false;
    c.addEventListener('pointerdown', ev => {
      dragging = true;
      c.setPointerCapture(ev.pointerId);
      this.opts.onSeek && this.opts.onSeek(this.tsAt(ev.clientX), false);
    });
    c.addEventListener('pointermove', ev => {
      const ts = this.tsAt(ev.clientX);
      this.hover = ts;
      this._showTip(ev.clientX, ts);
      if (dragging && this.opts.onSeek) this.opts.onSeek(ts, false);
    });
    const finish = ev => {
      if (!dragging) return;
      dragging = false;
      this.opts.onSeek && this.opts.onSeek(this.tsAt(ev.clientX), true);
    };
    c.addEventListener('pointerup', finish);
    c.addEventListener('pointercancel', () => { dragging = false; });
    c.addEventListener('pointerleave', () => { this.tip.style.display = 'none'; });
    this.el.addEventListener('keydown', ev => {
      if (!this.opts.onSeek || this.playhead == null) return;
      const step = ev.shiftKey ? 60 : 10;
      if (ev.key === 'ArrowLeft') { this.opts.onSeek(this.playhead - step, true); ev.preventDefault(); }
      if (ev.key === 'ArrowRight') { this.opts.onSeek(this.playhead + step, true); ev.preventDefault(); }
    });
  }

  _showTip(clientX, ts) {
    const r = this.el.getBoundingClientRect();
    this.tip.textContent = fmtTime(ts, (this.end - this.start) < 7200);
    this.tip.style.display = 'block';
    const x = Math.min(r.width - 40, Math.max(40, clientX - r.left));
    this.tip.style.left = x + 'px';
  }

  draw() {
    const c = this.canvas;
    const w = this.el.clientWidth;
    const h = this.opts.height;
    if (!w) return;
    const dpr = window.devicePixelRatio || 1;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
      c.style.width = w + 'px';
      c.style.height = h + 'px';
    }
    const g = c.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const span = this.end - this.start;
    const x = ts => ((ts - this.start) / span) * w;
    const tickH = this.opts.ticks ? 12 : 0;
    const barY = 0;
    const barH = h - tickH;

    // Past without recording = gap; future = neutral
    const nowX = Math.min(w, Math.max(0, x(this.now)));
    g.fillStyle = cssVar('--gap');
    g.fillRect(0, barY, nowX, barH);
    g.fillStyle = cssVar('--future');
    g.fillRect(nowX, barY, w - nowX, barH);

    g.fillStyle = cssVar('--recorded');
    for (const [s, e] of this.intervals) {
      const x0 = x(s), x1 = x(e);
      g.fillRect(x0, barY, Math.max(1, x1 - x0), barH);
    }
    g.fillStyle = cssVar('--motion');
    const mh = Math.max(4, Math.round(barH * 0.3));
    for (const [s, e] of this.events) {
      const x0 = x(s), x1 = x(e);
      g.fillRect(x0, barY, Math.max(2, x1 - x0), mh);
    }
    if (this.highlight) {
      g.fillStyle = cssVar('--highlight');
      const x0 = x(this.highlight[0]), x1 = x(this.highlight[1]);
      g.fillRect(x0, barY, Math.max(2, x1 - x0), barH);
    }
    const [mi, mo] = this.marks;
    if (mi != null || mo != null) {
      g.fillStyle = cssVar('--mark');
      const a = mi != null ? x(mi) : 0, b = mo != null ? x(mo) : w;
      g.globalAlpha = 0.25;
      g.fillRect(a, barY, Math.max(1, b - a), barH);
      g.globalAlpha = 1;
      g.fillRect(a - 1, barY, 2, barH);
      if (mo != null) g.fillRect(b - 1, barY, 2, barH);
    }

    if (this.opts.ticks) {
      const step = TICK_STEPS.find(s => (w / (span / s)) >= 70) || 21600;
      g.fillStyle = cssVar('--muted');
      g.strokeStyle = cssVar('--line');
      g.font = '10px system-ui, sans-serif';
      g.textAlign = 'center';
      const first = Math.ceil(this.start / step) * step;
      const tzOff = new Date(first * 1000).getTimezoneOffset() * 60;
      // align ticks to local wall clock
      let t0 = Math.ceil((this.start - tzOff) / step) * step + tzOff;
      if (t0 < this.start) t0 += step;
      for (let t = t0; t <= this.end; t += step) {
        const tx = Math.round(x(t)) + 0.5;
        g.beginPath();
        g.moveTo(tx, barH);
        g.lineTo(tx, barH + 3);
        g.stroke();
        if (tx > 14 && tx < w - 14) g.fillText(fmtTime(t, step < 60), tx, h - 1);
      }
    }

    if (this.playhead != null && this.playhead >= this.start && this.playhead <= this.end) {
      const px = Math.round(x(this.playhead));
      g.fillStyle = cssVar('--playhead');
      g.fillRect(px - 1, 0, 2, barH);
      g.beginPath();
      g.moveTo(px - 5, 0); g.lineTo(px + 5, 0); g.lineTo(px, 6);
      g.fill();
    }
  }
}
