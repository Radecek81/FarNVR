// Translations. Czech is primary, English secondary.
const DICT = {
  cs: {
    'nav.live': 'Živě', 'nav.playback': 'Záznamy', 'nav.settings': 'Nastavení', 'nav.logout': 'Odhlásit',
    'login.title': 'Přihlášení', 'login.username': 'Uživatel', 'login.password': 'Heslo',
    'login.otp': 'Kód z aplikace (2FA)', 'login.submit': 'Přihlásit se',
    'login.invalid': 'Nesprávné jméno nebo heslo.', 'login.otp_required': 'Zadejte kód z ověřovací aplikace.',
    'login.invalid_otp': 'Neplatný ověřovací kód.', 'login.too_many': 'Příliš mnoho pokusů, zkuste to za pár minut.',
    'login.error': 'Přihlášení se nezdařilo.',
    'live.layout': 'Rozložení', 'live.cameras': 'Kamery', 'live.panel_title': 'Zobrazené kamery',
    'live.panel_hint': 'Zaškrtnutím kameru zobrazíte, šipkami změníte pořadí. Skrytí kamery nevypíná nahrávání.',
    'live.no_cameras': 'Žádná kamera není zobrazena. Zapněte je v nabídce Kamery.',
    'live.fullscreen': 'Celá obrazovka', 'live.open_recording': 'Přehrát záznam', 'live.back': 'Zpět na mřížku',
    'live.unmute': 'Zapnout zvuk', 'live.mute': 'Vypnout zvuk', 'live.last24': 'Záznam za 24 h',
    'live.page': 'Strana',
    'state.recording': 'Nahrává', 'state.connecting': 'Připojuji', 'state.starting': 'Spouštím',
    'state.error': 'Chyba', 'state.storage_missing': 'Úložiště nepřipojeno', 'state.stopped': 'Zastaveno',
    'motion': 'Pohyb', 'mode.motion': 'jen při pohybu', 'mode.continuous': 'nepřetržitě',
    'pb.camera': 'Kamera', 'pb.date': 'Datum', 'pb.from': 'Od', 'pb.to': 'Do', 'pb.show': 'Zobrazit',
    'pb.last_hour': 'Poslední hodina', 'pb.today': 'Dnes', 'pb.no_recording': 'V tomto čase není žádný záznam.',
    'pb.play': 'Přehrát', 'pb.pause': 'Pauza', 'pb.frame_back': 'O snímek zpět', 'pb.frame_fwd': 'O snímek vpřed',
    'pb.speed': 'Rychlost', 'pb.jog': 'Kolečko: otáčením posouváte záznam', 'pb.jog_fine': 'jemně', 'pb.jog_coarse': 'hrubě',
    'pb.snapshot': 'Snímek', 'pb.export': 'Export', 'pb.mark_in': 'Začátek výřezu', 'pb.mark_out': 'Konec výřezu',
    'pb.export_title': 'Export záznamu do MP4', 'pb.export_h264': 'Kompatibilní formát H.264 (pomalejší, větší soubor)',
    'pb.export_go': 'Stáhnout MP4', 'pb.export_wait': 'Připravuji soubor…', 'pb.cancel': 'Zrušit',
    'pb.export_failed': 'Export se nezdařil', 'pb.day': 'Celý den', 'pb.compat': 'Režim kompatibility (převod do H.264)',
    'pb.loading': 'Načítám…', 'pb.mute': 'Zvuk',
    'legend.recorded': 'Záznam', 'legend.gap': 'Chybí záznam', 'legend.motion': 'Pohyb',
    'set.language': 'Jazyk', 'set.password': 'Změna hesla', 'set.current': 'Současné heslo', 'set.new': 'Nové heslo (min. 10 znaků)',
    'set.save': 'Uložit', 'set.saved': 'Uloženo.', 'set.pw_error': 'Heslo se nepodařilo změnit.',
    'set.system': 'Stav systému', 'set.storage': 'Úložiště', 'set.used': 'Obsazeno', 'set.daily': 'Denní přírůstek',
    'set.capacity': 'Odhad kapacity', 'set.days': 'dní', 'set.retention': 'Nastavená doba uchování',
    'set.cam': 'Kamera', 'set.state': 'Stav', 'set.last': 'Poslední úsek', 'set.codec': 'Kodek', 'set.onvif': 'Pohyb (ONVIF)',
    'set.oldest': 'Nejstarší záznam', 'set.not_mounted': 'POZOR: úložiště NAS není připojeno!',
    'set.capacity_warn': 'Kapacita nestačí na nastavenou dobu uchování – nejstarší záznamy se budou mazat dříve.',
    'set.user': 'Přihlášený uživatel', 'set.mode': 'Režim',
    'err.network': 'Chyba spojení se serverem.',
    'about.title': 'O aplikaci', 'about.text': 'Svobodný software pod licencí GNU AGPL-3.0.',
  },
  en: {
    'nav.live': 'Live', 'nav.playback': 'Recordings', 'nav.settings': 'Settings', 'nav.logout': 'Log out',
    'login.title': 'Sign in', 'login.username': 'Username', 'login.password': 'Password',
    'login.otp': 'Authenticator code (2FA)', 'login.submit': 'Sign in',
    'login.invalid': 'Wrong username or password.', 'login.otp_required': 'Enter the code from your authenticator app.',
    'login.invalid_otp': 'Invalid authentication code.', 'login.too_many': 'Too many attempts, try again in a few minutes.',
    'login.error': 'Sign in failed.',
    'live.layout': 'Layout', 'live.cameras': 'Cameras', 'live.panel_title': 'Visible cameras',
    'live.panel_hint': 'Tick to show a camera, use arrows to reorder. Hiding a camera does not stop recording.',
    'live.no_cameras': 'No camera is visible. Enable them in the Cameras menu.',
    'live.fullscreen': 'Full screen', 'live.open_recording': 'Play recording', 'live.back': 'Back to grid',
    'live.unmute': 'Unmute', 'live.mute': 'Mute', 'live.last24': 'Recording, last 24 h',
    'live.page': 'Page',
    'state.recording': 'Recording', 'state.connecting': 'Connecting', 'state.starting': 'Starting',
    'state.error': 'Error', 'state.storage_missing': 'Storage not mounted', 'state.stopped': 'Stopped',
    'motion': 'Motion', 'mode.motion': 'motion only', 'mode.continuous': 'continuous',
    'pb.camera': 'Camera', 'pb.date': 'Date', 'pb.from': 'From', 'pb.to': 'To', 'pb.show': 'Show',
    'pb.last_hour': 'Last hour', 'pb.today': 'Today', 'pb.no_recording': 'There is no recording in this time range.',
    'pb.play': 'Play', 'pb.pause': 'Pause', 'pb.frame_back': 'Frame back', 'pb.frame_fwd': 'Frame forward',
    'pb.speed': 'Speed', 'pb.jog': 'Jog wheel: rotate to scrub', 'pb.jog_fine': 'fine', 'pb.jog_coarse': 'coarse',
    'pb.snapshot': 'Snapshot', 'pb.export': 'Export', 'pb.mark_in': 'Clip start', 'pb.mark_out': 'Clip end',
    'pb.export_title': 'Export recording to MP4', 'pb.export_h264': 'Compatible H.264 format (slower, larger file)',
    'pb.export_go': 'Download MP4', 'pb.export_wait': 'Preparing file…', 'pb.cancel': 'Cancel',
    'pb.export_failed': 'Export failed', 'pb.day': 'Whole day', 'pb.compat': 'Compatibility mode (H.264 transcode)',
    'pb.loading': 'Loading…', 'pb.mute': 'Sound',
    'legend.recorded': 'Recorded', 'legend.gap': 'Missing', 'legend.motion': 'Motion',
    'set.language': 'Language', 'set.password': 'Change password', 'set.current': 'Current password', 'set.new': 'New password (min. 10 chars)',
    'set.save': 'Save', 'set.saved': 'Saved.', 'set.pw_error': 'Password could not be changed.',
    'set.system': 'System status', 'set.storage': 'Storage', 'set.used': 'Used', 'set.daily': 'Daily growth',
    'set.capacity': 'Estimated capacity', 'set.days': 'days', 'set.retention': 'Configured retention',
    'set.cam': 'Camera', 'set.state': 'State', 'set.last': 'Last segment', 'set.codec': 'Codec', 'set.onvif': 'Motion (ONVIF)',
    'set.oldest': 'Oldest recording', 'set.not_mounted': 'WARNING: NAS storage is not mounted!',
    'set.capacity_warn': 'Capacity is below the configured retention – oldest recordings will be deleted sooner.',
    'set.user': 'Signed in as', 'set.mode': 'Mode',
    'err.network': 'Connection to the server failed.',
    'about.title': 'About', 'about.text': 'Free software licensed under GNU AGPL-3.0.',
  },
};

let lang = 'cs';

export function detectLang() {
  try {
    const saved = localStorage.getItem('nvr.lang');
    if (saved && DICT[saved]) return saved;
  } catch (e) { /* storage unavailable */ }
  // Czech is the primary language; English only for clearly English browsers
  return (navigator.language || 'cs').toLowerCase().startsWith('en') ? 'en' : 'cs';
}

export function setLang(l) {
  lang = DICT[l] ? l : 'cs';
  document.documentElement.lang = lang;
  try { localStorage.setItem('nvr.lang', lang); } catch (e) { /* ignore */ }
  applyI18n(document);
}

export function getLang() { return lang; }

export function t(key) {
  return (DICT[lang] && DICT[lang][key]) || DICT.cs[key] || key;
}

export function applyI18n(root) {
  root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  root.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
    el.setAttribute('aria-label', el.title);
  });
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
}

export function locale() { return lang === 'cs' ? 'cs-CZ' : 'en-GB'; }

export function fmtTime(ts, seconds = true) {
  return new Date(ts * 1000).toLocaleTimeString(locale(), {
    hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}),
  });
}

export function fmtDateTime(ts) {
  return new Date(ts * 1000).toLocaleString(locale(), {
    day: 'numeric', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

export function fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B', 'kB', 'MB', 'GB', 'TB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1000)));
  return (n / 1000 ** i).toFixed(i > 2 ? 1 : 0) + ' ' + u[i];
}
