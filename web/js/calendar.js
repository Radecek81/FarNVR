// Month calendar popover; days with recordings are highlighted.
import { api, qs } from './api.js';
import { locale } from './i18n.js';

export class Calendar {
  constructor(anchor, { getCamera, onPick }) {
    this.anchor = anchor;
    this.getCamera = getCamera;
    this.onPick = onPick;
    this.pop = document.createElement('div');
    this.pop.className = 'calendar-pop';
    this.pop.hidden = true;
    anchor.parentElement.appendChild(this.pop);
    anchor.addEventListener('click', () => (this.pop.hidden ? this.open() : this.close()));
    document.addEventListener('pointerdown', ev => {
      if (!this.pop.hidden && !this.pop.contains(ev.target) && ev.target !== anchor) this.close();
    });
  }

  open(date) {
    const d = date || this.selected || new Date();
    this.view = new Date(d.getFullYear(), d.getMonth(), 1);
    this.pop.hidden = false;
    this.render();
  }

  close() { this.pop.hidden = true; }

  setSelected(date) { this.selected = date; }

  async render() {
    const y = this.view.getFullYear(), m = this.view.getMonth();
    const title = this.view.toLocaleDateString(locale(), { month: 'long', year: 'numeric' });
    const first = (new Date(y, m, 1).getDay() + 6) % 7; // Monday first
    const count = new Date(y, m + 1, 0).getDate();
    const wd = Array.from({ length: 7 }, (_, i) =>
      new Date(2024, 0, 1 + i).toLocaleDateString(locale(), { weekday: 'short' }));
    const today = new Date();
    let html = `<div class="cal-head"><button type="button" class="btn icon" data-nav="-1" aria-label="‹">‹</button>
      <strong>${title}</strong><button type="button" class="btn icon" data-nav="1" aria-label="›">›</button></div>
      <div class="cal-grid">${wd.map(w => `<span class="cal-wd">${w}</span>`).join('')}`;
    html += '<span></span>'.repeat(first);
    for (let day = 1; day <= count; day++) {
      const isToday = today.getFullYear() === y && today.getMonth() === m && today.getDate() === day;
      const isSel = this.selected && this.selected.getFullYear() === y && this.selected.getMonth() === m &&
        this.selected.getDate() === day;
      html += `<button type="button" class="cal-day${isToday ? ' today' : ''}${isSel ? ' selected' : ''}" data-day="${day}">${day}</button>`;
    }
    html += '</div>';
    this.pop.innerHTML = html;
    this.pop.querySelectorAll('[data-nav]').forEach(b => b.addEventListener('click', () => {
      this.view = new Date(y, m + Number(b.dataset.nav), 1);
      this.render();
    }));
    this.pop.querySelectorAll('[data-day]').forEach(b => b.addEventListener('click', () => {
      const d = new Date(y, m, Number(b.dataset.day));
      this.selected = d;
      this.close();
      this.onPick(d);
    }));
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const res = await api(`/api/cameras/${this.getCamera()}/days?` + qs({ year: y, month: m + 1, tz }));
      if (this.view.getFullYear() !== y || this.view.getMonth() !== m) return;
      for (const day of res.days) {
        const b = this.pop.querySelector(`[data-day="${day}"]`);
        if (b) b.classList.add('has-rec');
      }
    } catch (e) { /* calendar still usable */ }
  }
}
