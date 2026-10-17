// Virtual jog wheel. Rotating it (mouse drag, touch, or mouse wheel) emits
// a time delta in seconds. Pointer Events give one code path for mouse,
// pen and touch.

const SVG_NS = 'http://www.w3.org/2000/svg';

export class JogWheel {
  /**
   * @param {HTMLElement} el container
   * @param {{onStart?:Function,onDelta:(sec:number)=>void,onEnd?:Function,secondsPerTurn?:number}} opts
   */
  constructor(el, opts) {
    this.el = el;
    this.opts = opts;
    this.secondsPerTurn = opts.secondsPerTurn || 2;
    this.angle = 0;
    this._build();
    this._bind();
  }

  _build() {
    this.el.classList.add('jog');
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 100 100');
    svg.innerHTML = `
      <circle cx="50" cy="50" r="48" class="jog-outer"/>
      <g class="jog-rot">
        ${Array.from({ length: 36 }, (_, i) => {
          const a = (i * 10) * Math.PI / 180;
          const r1 = i % 3 === 0 ? 37 : 40, r2 = 45;
          return `<line x1="${50 + r1 * Math.sin(a)}" y1="${50 - r1 * Math.cos(a)}" x2="${50 + r2 * Math.sin(a)}" y2="${50 - r2 * Math.cos(a)}"/>`;
        }).join('')}
        <circle cx="50" cy="16" r="5" class="jog-grip"/>
      </g>
      <circle cx="50" cy="50" r="22" class="jog-inner"/>`;
    this.el.appendChild(svg);
    this.rot = svg.querySelector('.jog-rot');
    this.svg = svg;
    this.center = document.createElement('button');
    this.center.type = 'button';
    this.center.className = 'jog-center';
    this.el.appendChild(this.center);
  }

  setLabel(text, title) {
    this.center.textContent = text;
    this.center.title = title || '';
  }

  _angleOf(ev) {
    const r = this.svg.getBoundingClientRect();
    return Math.atan2(ev.clientX - (r.left + r.width / 2), -(ev.clientY - (r.top + r.height / 2)));
  }

  _rotate(deltaRad) {
    this.angle += deltaRad;
    this.rot.setAttribute('transform', `rotate(${(this.angle * 180 / Math.PI) % 360} 50 50)`);
    this.opts.onDelta((deltaRad / (2 * Math.PI)) * this.secondsPerTurn);
  }

  _bind() {
    let last = null;
    let active = false;
    this.svg.addEventListener('pointerdown', ev => {
      ev.preventDefault();
      active = true;
      last = this._angleOf(ev);
      this.svg.setPointerCapture(ev.pointerId);
      this.el.classList.add('active');
      this.opts.onStart && this.opts.onStart();
    });
    this.svg.addEventListener('pointermove', ev => {
      if (!active) return;
      const a = this._angleOf(ev);
      let d = a - last;
      if (d > Math.PI) d -= 2 * Math.PI;
      if (d < -Math.PI) d += 2 * Math.PI;
      last = a;
      if (Math.abs(d) > 0.0005) this._rotate(d);
    });
    const end = () => {
      if (!active) return;
      active = false;
      this.el.classList.remove('active');
      this.opts.onEnd && this.opts.onEnd();
    };
    this.svg.addEventListener('pointerup', end);
    this.svg.addEventListener('pointercancel', end);
    // Mouse wheel / touchpad: one notch = 10 degrees
    let wheelTimer = 0;
    this.svg.addEventListener('wheel', ev => {
      ev.preventDefault();
      if (!wheelTimer) this.opts.onStart && this.opts.onStart();
      clearTimeout(wheelTimer);
      const notch = Math.sign(ev.deltaY || ev.deltaX) * (Math.PI / 18);
      this._rotate(notch);
      wheelTimer = setTimeout(() => { wheelTimer = 0; this.opts.onEnd && this.opts.onEnd(); }, 400);
    }, { passive: false });
  }
}
