/*
 * Shared session + API layer for both UI pages.
 *
 * The previous UI kept its auth token in two unrelated places - onboarding
 * wrote one to localStorage, and the dashboard made you paste it into a text
 * box by hand. Both pages now read the same keys here, so signing in on
 * onboarding is enough to land on the dashboard already authenticated.
 */

const LS = {
  token: 'rs_access_token',
  refresh: 'rs_refresh_token',
  email: 'rs_email',
  companyId: 'rs_company_id',
};

/*
 * Fixed to this one deployment: one Railway-hosted backend talking to one
 * Supabase project. The anon key is Supabase's public, client-safe key (unlike
 * the service-role secret, which only ever lives in Railway's env vars) -
 * baking it in here is the same trust level as shipping it in any other
 * client-side bundle.
 */
const API_BASE = 'https://reddit-scanner-api-production.up.railway.app';
const SUPABASE_URL = 'https://hlnrsashchwzzvbqqmch.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_77ybrddbVRazAuE_lHm89A_CX-AdPCb';

// ---- storage ----

function lsGet(key, fallback = '') {
  return localStorage.getItem(key) || fallback;
}

function lsSet(key, value) {
  if (value) localStorage.setItem(key, value);
  else localStorage.removeItem(key);
}

const session = {
  apiBase: () => API_BASE,
  supabaseUrl: () => SUPABASE_URL,
  supabaseAnonKey: () => SUPABASE_ANON_KEY,
  token: () => lsGet(LS.token),
  email: () => lsGet(LS.email),
  companyId: () => lsGet(LS.companyId),
  isSignedIn: () => !!lsGet(LS.token),

  signIn({ token, refreshToken, email }) {
    lsSet(LS.token, token);
    lsSet(LS.refresh, refreshToken);
    lsSet(LS.email, email);
  },

  setCompanyId(id) {
    lsSet(LS.companyId, id);
  },

  signOut() {
    [LS.token, LS.refresh, LS.email, LS.companyId].forEach((k) => localStorage.removeItem(k));
  },
};

// ---- errors ----

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function detailToMessage(detail, status) {
  if (!detail) return `HTTP ${status}`;
  if (typeof detail === 'string') return detail;
  // FastAPI validation errors arrive as a list of {loc, msg, type}
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && d.msg) || JSON.stringify(d)).join('; ');
  }
  return JSON.stringify(detail);
}

// ---- backend API ----

async function sendRequest(path, opts) {
  const headers = Object.assign(
    { Authorization: `Bearer ${session.token()}` },
    opts.body ? { 'Content-Type': 'application/json' } : {},
    opts.headers || {},
  );

  let res;
  try {
    res = await fetch(`${session.apiBase()}${path}`, { ...opts, headers });
  } catch (e) {
    throw new ApiError('Could not reach the backend — is uvicorn running?', 0);
  }

  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { /* non-JSON error body */ }
  }
  return { res, data };
}

async function api(path, opts = {}) {
  if (!session.token()) throw new ApiError('Not signed in', 401);

  let { res, data } = await sendRequest(path, opts);

  // Supabase access tokens expire after an hour. Rather than dumping the user
  // back to a login screen mid-session, spend the refresh token once and retry.
  if (res.status === 401 && (await tryRefresh())) {
    ({ res, data } = await sendRequest(path, opts));
  }

  if (!res.ok) {
    throw new ApiError(detailToMessage(data && data.detail, res.status), res.status);
  }
  return data;
}

let refreshInFlight = null;

function tryRefresh() {
  // Collapse concurrent 401s (the dashboard fires matches + leads in parallel)
  // into a single refresh round-trip.
  if (refreshInFlight) return refreshInFlight;

  const refreshToken = lsGet(LS.refresh);
  const url = session.supabaseUrl();
  const anonKey = session.supabaseAnonKey();
  if (!refreshToken || !url || !anonKey) return Promise.resolve(false);

  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${url}/auth/v1/token?grant_type=refresh_token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', apikey: anonKey },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.access_token) return false;

      session.signIn({
        token: data.access_token,
        refreshToken: data.refresh_token,
        email: (data.user && data.user.email) || session.email(),
      });
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

// ---- Supabase Auth (direct, no SDK) ----

async function supabaseAuth(endpoint, email, password) {
  const url = session.supabaseUrl();
  const anonKey = session.supabaseAnonKey();
  if (!url || !anonKey) {
    throw new ApiError('Add your Supabase project URL and anon key in Connection settings first.', 0);
  }

  let res;
  try {
    res = await fetch(`${url}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', apikey: anonKey },
      body: JSON.stringify({ email, password }),
    });
  } catch (e) {
    throw new ApiError('Could not reach Supabase — check the project URL.', 0);
  }

  const data = await res.json().catch(() => null);
  if (!res.ok || !data) {
    const msg = (data && (data.error_description || data.msg || data.message)) || `HTTP ${res.status}`;
    throw new ApiError(msg, res.status);
  }
  return data;
}

/* Where Supabase sends people after they click the confirmation email.
 * Without an explicit redirect_to, Supabase falls back to the project's Site URL
 * - which defaults to http://localhost:3000 and stranded every real signup there.
 * Derived from the current origin so local dev and the deployed site each send
 * people back to themselves. Supabase only honours this if the URL is listed
 * under Authentication -> URL Configuration -> Redirect URLs. */
function emailRedirectTo() {
  return `${window.location.origin}/onboarding.html`;
}

/** Read the email claim out of a Supabase access token, for display only.
 *  Used when a session arrives via the confirmation-email redirect, where the
 *  fragment carries tokens but no email. Not a security check - the backend
 *  independently validates every token it's given. */
function emailFromToken(token) {
  try {
    const payload = token.split('.')[1];
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json).email || '';
  } catch {
    return '';
  }
}

const auth = {
  signUp: (email, password) => supabaseAuth(
    `/auth/v1/signup?redirect_to=${encodeURIComponent(emailRedirectTo())}`, email, password),
  logIn: (email, password) => supabaseAuth('/auth/v1/token?grant_type=password', email, password),
};

// ---- view helpers ----

/** Escape untrusted text before it goes anywhere near innerHTML.
 *  Reddit post titles and AI reasoning are arbitrary user-authored strings. */
function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function timeAgo(iso) {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function splitList(value) {
  return value.split(',').map((s) => s.trim()).filter(Boolean);
}

/** Renders into a [role=status] slot. `kind` is 'error' | 'ok' | 'info'. */
function setStatus(el, text, kind = 'info') {
  if (!el) return;
  el.className = text ? `status status-${kind}` : 'status';
  el.textContent = text || '';
}

function el(id) {
  return document.getElementById(id);
}
