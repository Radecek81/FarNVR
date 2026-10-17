import { api } from './api.js';
import { applyI18n, detectLang, setLang, t } from './i18n.js';
import { LiveView } from './live.js';
import { PlaybackView } from './playback.js';
import { SettingsView } from './settings.js';

class App {
  async init() {
    setLang(detectLang());
    const [me, config] = await Promise.all([api('/api/me'), api('/api/config')]);
    this.user = me;
    this.config = config;
    this.prefs = { layout: 9, order: [], hidden: [], ...(me.prefs || {}) };
    if (this.prefs.lang) setLang(this.prefs.lang);
    document.title = config.site_name;
    document.querySelector('.brand-name').textContent = config.site_name;

    this.views = {
      live: new LiveView(document.getElementById('view-live'), this),
      playback: new PlaybackView(document.getElementById('view-playback'), this),
      settings: new SettingsView(document.getElementById('view-settings'), this),
    };
    document.querySelector('[data-act="logout"]').addEventListener('click', async () => {
      try { await api('/api/logout', { method: 'POST' }); } finally { location.href = '/login.html'; }
    });
    window.addEventListener('hashchange', () => this.route());
    this.route();
    this.pollStatus();
    setInterval(() => this.pollStatus(), 10000);
    setInterval(() => this.updateClock(), 1000);
    this.updateClock();
  }

  route() {
    const name = (location.hash.replace('#', '') || 'live').split('?')[0];
    const view = this.views[name] ? name : 'live';
    if (this.current === view) return;
    if (this.current) this.views[this.current].hide();
    document.querySelectorAll('.view').forEach(v => { v.hidden = v.id !== 'view-' + view; });
    document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.getAttribute('href') === '#' + view));
    this.current = view;
    this.views[view].show();
  }

  openPlayback(cam, ts) {
    this.views.playback.open(cam, ts);
    location.hash = '#playback';
  }

  async pollStatus() {
    try {
      this.status = await api('/api/status');
      this.views.live.updateStatus();
      const bad = Object.values(this.status.cameras).filter(c => c.state !== 'recording').length;
      const badge = document.querySelector('.health');
      badge.hidden = bad === 0 && this.status.storage.mounted;
      badge.textContent = !this.status.storage.mounted ? t('state.storage_missing') : `${bad}× ${t('state.error')}`;
    } catch (e) { /* offline, keep last */ }
  }

  updateClock() {
    document.querySelector('.clock').textContent = new Date().toLocaleTimeString();
  }

  savePrefs() {
    clearTimeout(this._prefTimer);
    this._prefTimer = setTimeout(() => {
      api('/api/me/prefs', { method: 'PUT', json: this.prefs }).catch(() => {});
    }, 500);
  }

  changeLang(lang) {
    this.prefs.lang = lang;
    setLang(lang);
    this.savePrefs();
    applyI18n(document);
    // Re-render dynamic views with the new language
    const cur = this.current;
    this.views[cur].hide();
    this.views.live = new LiveView(document.getElementById('view-live'), this);
    this.views.playback = new PlaybackView(document.getElementById('view-playback'), this);
    this.views[cur].show();
  }
}

new App().init().catch(err => {
  console.error(err);
  document.body.insertAdjacentHTML('beforeend', `<p class="alert">${t('err.network')}</p>`);
});
