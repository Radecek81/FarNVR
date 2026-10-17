// Settings: language, password change, system and storage status.
import { api } from './api.js';
import { applyI18n, fmtBytes, fmtDateTime, getLang, t } from './i18n.js';

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export class SettingsView {
  constructor(root, app) {
    this.root = root;
    this.app = app;
  }

  show() {
    this.render();
    this.timer = setInterval(() => this.renderStatus(), 10000);
  }

  hide() { clearInterval(this.timer); }

  render() {
    this.root.innerHTML = `
      <div class="settings">
        <section class="card">
          <h3 data-i18n="set.language"></h3>
          <div class="seg">
            <button type="button" class="btn" data-lang="cs">Čeština</button>
            <button type="button" class="btn" data-lang="en">English</button>
          </div>
          <p class="hint"><span data-i18n="set.user"></span>: <strong class="who"></strong></p>
        </section>
        <section class="card">
          <h3 data-i18n="set.password"></h3>
          <form class="stack pw-form">
            <input type="text" name="username" autocomplete="username" hidden>
            <label><span data-i18n="set.current"></span><input type="password" class="pw-cur" autocomplete="current-password" required></label>
            <label><span data-i18n="set.new"></span><input type="password" class="pw-new" autocomplete="new-password" minlength="10" required></label>
            <div class="row"><button class="btn primary" data-i18n="set.save"></button><span class="pw-msg hint"></span></div>
          </form>
        </section>
        <section class="card">
          <h3 data-i18n="about.title"></h3>
          <p><strong>FarNVR</strong> © Uberit s.r.o.</p>
          <p class="hint"><span data-i18n="about.text"></span>
            <a href="https://github.com/Radecek81/FarNVR" rel="noopener">github.com/Radecek81/FarNVR</a></p>
        </section>
        <section class="card wide">
          <h3 data-i18n="set.system"></h3>
          <div class="status"></div>
        </section>
      </div>`;
    applyI18n(this.root);
    this.root.querySelector('.who').textContent = this.app.user.username;
    this.root.querySelectorAll('[data-lang]').forEach(b => {
      b.classList.toggle('active', b.dataset.lang === getLang());
      b.addEventListener('click', () => { this.app.changeLang(b.dataset.lang); this.render(); });
    });
    this.root.querySelector('.pw-form').addEventListener('submit', async ev => {
      ev.preventDefault();
      const msg = this.root.querySelector('.pw-msg');
      try {
        await api('/api/me/password', { json: {
          current: this.root.querySelector('.pw-cur').value, new: this.root.querySelector('.pw-new').value } });
        msg.textContent = t('set.saved');
        ev.target.reset();
      } catch (e) { msg.textContent = t('set.pw_error'); }
    });
    this.renderStatus();
  }

  async renderStatus() {
    const el = this.root.querySelector('.status');
    if (!el) return;
    let st;
    try { st = await api('/api/status'); } catch (e) { el.textContent = t('err.network'); return; }
    const s = st.storage;
    const warnCap = s.capacity_days != null && s.capacity_days < s.retention_days;
    const rows = this.app.config.cameras.map(c => {
      const r = st.cameras[c.id] || {};
      const sc = s.cameras[c.id] || {};
      const onv = r.onvif ? t('state.' + (r.onvif.state === 'subscribed' ? 'recording' : r.onvif.state)) : '–';
      return `<tr>
        <td>${esc(c.name)}</td>
        <td><span class="dot ${esc(r.state)}"></span> ${esc(t('state.' + r.state))}
          ${r.last_error ? `<div class="hint err">${esc(r.last_error)}</div>` : ''}</td>
        <td>${esc(t('mode.' + c.mode))}</td>
        <td>${r.last_segment_at ? esc(fmtDateTime(r.last_segment_at)) : '–'}</td>
        <td>${esc((r.codec || '–').toUpperCase())}</td>
        <td>${esc(onv)}${r.onvif && r.onvif.last_error ? `<div class="hint err">${esc(r.onvif.last_error)}</div>` : ''}</td>
        <td>${fmtBytes(sc.bytes_24h || 0)}</td>
        <td>${sc.oldest ? esc(fmtDateTime(sc.oldest)) : '–'}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `
      ${s.mounted ? '' : `<p class="alert">${esc(t('set.not_mounted'))}</p>`}
      <div class="kpis">
        <div><span>${esc(t('set.used'))}</span><strong>${fmtBytes(s.used)} / ${fmtBytes(s.total)}</strong><em>${s.usage_percent} %</em></div>
        <div><span>${esc(t('set.daily'))}</span><strong>${fmtBytes(s.daily_bytes)}</strong></div>
        <div><span>${esc(t('set.capacity'))}</span><strong>${s.capacity_days != null ? s.capacity_days + ' ' + esc(t('set.days')) : '–'}</strong></div>
        <div><span>${esc(t('set.retention'))}</span><strong>${s.retention_days} ${esc(t('set.days'))}</strong></div>
      </div>
      ${warnCap ? `<p class="alert warn">${esc(t('set.capacity_warn'))}</p>` : ''}
      <div class="table-wrap"><table>
        <thead><tr><th>${esc(t('set.cam'))}</th><th>${esc(t('set.state'))}</th><th>${esc(t('set.mode'))}</th><th>${esc(t('set.last'))}</th>
          <th>${esc(t('set.codec'))}</th><th>${esc(t('set.onvif'))}</th><th>${esc(t('set.daily'))}</th><th>${esc(t('set.oldest'))}</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`;
  }
}
