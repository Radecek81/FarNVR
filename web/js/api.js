// Thin fetch wrapper. Every mutating request carries X-NVR (CSRF guard).

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || String(status));
    this.status = status;
    this.detail = detail;
  }
}

export async function api(path, opts = {}) {
  const init = { credentials: 'same-origin', headers: { 'X-NVR': '1' }, ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || 'POST';
    init.body = JSON.stringify(opts.json);
    init.headers['Content-Type'] = 'application/json';
  }
  const r = await fetch(path, init);
  if (r.status === 401 && !path.startsWith('/api/login')) {
    location.href = '/login.html';
    throw new ApiError(401, 'login_required');
  }
  if (!r.ok) {
    let detail = '';
    try { detail = (await r.json()).detail; } catch (e) { /* not json */ }
    throw new ApiError(r.status, detail);
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r.text();
}

export function qs(params) {
  return new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null)).toString();
}
