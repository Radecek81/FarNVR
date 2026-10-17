import { api } from './api.js';
import { detectLang, setLang, t } from './i18n.js';

setLang(detectLang());
const form = document.querySelector('form');
const alertEl = form.querySelector('.alert');
const otpRow = form.querySelector('.otp');
form.querySelectorAll('[data-lang]').forEach(b => b.addEventListener('click', () => setLang(b.dataset.lang)));

form.addEventListener('submit', async ev => {
  ev.preventDefault();
  alertEl.hidden = true;
  const btn = form.querySelector('button.primary');
  btn.disabled = true;
  try {
    await api('/api/login', { json: {
      username: form.username.value, password: form.password.value, otp: form.otp.value || null } });
    location.href = '/';
  } catch (e) {
    const map = { invalid: 'login.invalid', otp_required: 'login.otp_required', invalid_otp: 'login.invalid_otp',
      too_many_attempts: 'login.too_many' };
    if (e.detail === 'otp_required' || e.detail === 'invalid_otp') {
      otpRow.hidden = false;
      form.otp.focus();
    }
    alertEl.textContent = t(map[e.detail] || 'login.error');
    alertEl.hidden = false;
  } finally {
    btn.disabled = false;
  }
});
