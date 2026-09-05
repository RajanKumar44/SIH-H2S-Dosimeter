/**
 * api.js — thin client for the EXISTING FastAPI backend (software/backend).
 *
 * No endpoint is invented here. Everything maps 1:1 onto routes that already
 * ship in the backend:
 *
 *   POST /auth/login                  → JWT (officer/service account)
 *   GET  /auth/me                     → session probe
 *   GET  /workers/                    → worker roster (picker)
 *   POST /readings/scan   (multipart) → ML analysis + stored reading + alert
 *   GET  /readings/worker/{code}      → history for the graph
 *   GET  /health                      → connectivity check
 *
 * The dose is computed server-side by the existing ML pipeline; the app never
 * reimplements colour science.
 */

const DEFAULT_BASE = "http://localhost:8000";

/**
 * Backend used by the packaged Android/iOS build.
 *
 * Why this constant is necessary
 * ------------------------------
 * Inside a Capacitor WebView the app is served from the app bundle, so
 * `window.location.hostname` is **"localhost"** (or the capacitor:// custom
 * scheme host) — NOT the laptop, and not a LAN IP. The generic resolution
 * below therefore fell through to DEFAULT_BASE and the installed APK tried to
 * call `http://localhost:8000`, i.e. **port 8000 on the phone itself**, where
 * nothing is listening. Every request failed instantly and the app reported
 * "Cannot reach the server" even though the same phone could open
 * https://sih-h2s-backend.onrender.com/health in Chrome.
 *
 * A packaged app has no dev server to infer an address from, so the deployed
 * backend has to be compiled in. It stays overridable: VITE_API_BASE at build
 * time and the in-app Settings screen at runtime both still win.
 */
const NATIVE_DEFAULT_BASE = "https://sih-h2s-backend.onrender.com";

const BASE_KEY = "h2s_mobile_api_base";
const TOKEN_KEY = "h2s_mobile_token";
const WORKER_KEY = "h2s_mobile_last_worker";

/** Network/HTTP failure with a user-presentable message. */
export class ApiError extends Error {
  constructor(message, { status = 0, kind = "http" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind; // "http" | "network" | "auth" | "validation" | "unavailable"
  }
}

function envBase() {
  const v = import.meta.env?.VITE_API_BASE;
  return typeof v === "string" && v.trim() ? v.trim() : "";
}

const BACKEND_PORT = "8000";

/** A bare IPv4 literal, e.g. 192.168.1.5 — a LAN address, not a tunnel host. */
function isIpHost(hostname) {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(hostname);
}

/**
 * Derive the backend URL for port-prefixed HTTPS preview hosts.
 *
 * The phone camera needs a secure context, so on a real device the app is
 * usually reached through a tunnel whose hostname encodes the port, e.g.
 *
 *   https://5174-abc123.sandbox.novita.ai   (app)
 *   https://8000-abc123.sandbox.novita.ai   (backend)
 *
 * Appending ":8000" to such a host — what the old code did for every non-local
 * hostname — produced an unreachable URL, and calling an http:// backend from
 * an https:// page is blocked as mixed content anyway. Rewriting the port
 * prefix keeps the whole flow on HTTPS and makes the camera demo work without
 * anyone editing Settings.
 *
 * @returns {string} full origin, or "" if the host is not port-prefixed.
 */
export function derivePreviewApiBase(hostname, protocol = "https:") {
  const m = /^(\d{2,5})-(.+)$/.exec(hostname || "");
  if (!m) return "";
  return `${protocol}//${BACKEND_PORT}-${m[2]}`;
}

/**
 * True when the page is running inside a Capacitor/Cordova native WebView
 * rather than a normal browser tab.
 *
 * Detection order matters — the reliable signals first:
 *   1. `window.Capacitor.isNativePlatform()` — injected by the Capacitor
 *      runtime; authoritative when present.
 *   2. `window.Capacitor.platform` / `window.cordova` — older runtimes.
 *   3. A capacitor:// or ionic:// page protocol — the custom-scheme case,
 *      which is unmistakable.
 *
 * A bare "localhost" hostname is deliberately NOT treated as native on its
 * own: `npm run dev` also serves on localhost, and mis-detecting the dev
 * server would silently redirect a developer's requests to the production
 * Render backend.
 */
export function isNativeApp(win = typeof window !== "undefined" ? window : undefined) {
  if (!win) return false;

  const cap = win.Capacitor;
  if (cap) {
    if (typeof cap.isNativePlatform === "function") {
      try {
        if (cap.isNativePlatform()) return true;
      } catch {
        /* fall through to the other signals */
      }
    }
    if (typeof cap.platform === "string" && cap.platform !== "web") return true;
  }
  if (win.cordova) return true;

  const proto = win.location?.protocol || "";
  return proto === "capacitor:" || proto === "ionic:";
}

export function getApiBase() {
  const stored = localStorage.getItem(BASE_KEY);
  if (stored && stored.trim()) return stored.replace(/\/+$/, "");
  const fromEnv = envBase();
  if (fromEnv) return fromEnv.replace(/\/+$/, "");

  // Packaged native build: there is no dev server to infer an address from and
  // "localhost" means the handset, so use the deployed backend.
  if (isNativeApp()) return NATIVE_DEFAULT_BASE;

  const { hostname, protocol } = window.location;
  if (!hostname || hostname === "localhost" || hostname === "127.0.0.1") {
    return DEFAULT_BASE;
  }

  // HTTPS preview/tunnel host that encodes the port (Codespaces, sandbox URLs).
  const preview = derivePreviewApiBase(hostname, protocol);
  if (preview) return preview;

  // Phones cannot reach the laptop's "localhost". When the app is served from a
  // LAN IP, default the API to the same host on the backend port.
  if (isIpHost(hostname)) return `${protocol}//${hostname}:${BACKEND_PORT}`;

  // Some other named host — a guessed port would very likely be wrong, so
  // point at the same origin and let Settings override it.
  return `${protocol}//${hostname}`;
}

/**
 * True when an https:// page is configured to call an http:// API — the browser
 * blocks those requests as mixed content before they leave the device, which
 * looks exactly like "the server is down". Surfaced in Settings.
 */
export function hasMixedContentIssue(base = getApiBase()) {
  if (typeof window === "undefined") return false;
  return window.location.protocol === "https:" && base.startsWith("http://");
}

export function setApiBase(base) {
  const clean = (base || "").trim().replace(/\/+$/, "");
  if (clean) localStorage.setItem(BASE_KEY, clean);
  else localStorage.removeItem(BASE_KEY);
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || null;
}

function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function isLoggedIn() {
  return !!getToken();
}

export function getLastWorker() {
  return localStorage.getItem(WORKER_KEY) || "";
}

export function setLastWorker(code) {
  if (code) localStorage.setItem(WORKER_KEY, code);
}

export function logout() {
  setToken(null);
}

/** Pull the human-readable message out of a FastAPI error body. */
function detailOf(payload, status) {
  const d = payload?.detail;
  if (typeof d === "string" && d) return d;
  if (Array.isArray(d) && d.length) {
    // Pydantic validation errors
    const first = d[0];
    if (first?.msg) return `${first.msg}${first.loc ? ` (${first.loc.join(".")})` : ""}`;
  }
  if (typeof payload === "string" && payload.trim()) return payload.trim();
  return `Request failed (HTTP ${status}).`;
}

async function parseBody(res) {
  const ct = res.headers.get("content-type") || "";
  try {
    return ct.includes("json") ? await res.json() : await res.text();
  } catch {
    return null;
  }
}

function throwForStatus(res, payload) {
  const msg = detailOf(payload, res.status);
  if (res.status === 401) {
    setToken(null);
    throw new ApiError("Session expired — please sign in again.", {
      status: 401,
      kind: "auth",
    });
  }
  if (res.status === 403) {
    throw new ApiError("You do not have permission for this action.", {
      status: 403,
      kind: "auth",
    });
  }
  if (res.status === 503) {
    throw new ApiError(msg, { status: 503, kind: "unavailable" });
  }
  if (res.status === 400 || res.status === 415 || res.status === 422) {
    throw new ApiError(msg, { status: res.status, kind: "validation" });
  }
  throw new ApiError(msg, { status: res.status });
}

const DEFAULT_TIMEOUT = 20000;

async function fetchWithTimeout(url, opts = {}, timeout = DEFAULT_TIMEOUT) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    return await fetch(url, { ...opts, signal: ctl.signal });
  } catch (e) {
    if (e?.name === "AbortError") {
      throw new ApiError(
        `The server did not respond within ${Math.round(timeout / 1000)}s. ` +
          `Check the connection and try again.`,
        { kind: "network" },
      );
    }
    throw new ApiError(
      "Cannot reach the server. Check your network and the API address in Settings.",
      { kind: "network" },
    );
  } finally {
    clearTimeout(timer);
  }
}

async function request(method, path, { body, form, timeout } = {}) {
  const headers = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const opts = { method, headers };
  if (form) {
    opts.body = form; // browser sets the multipart boundary
  } else if (body instanceof URLSearchParams) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    opts.body = body.toString();
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }

  const res = await fetchWithTimeout(`${getApiBase()}${path}`, opts, timeout);
  const payload = await parseBody(res);
  if (!res.ok) throwForStatus(res, payload);
  return payload;
}

export const api = {
  health: () => request("GET", "/health", { timeout: 8000 }),

  login: async (username, password) => {
    const data = await request("POST", "/auth/login", {
      body: new URLSearchParams({ username, password }),
      timeout: 15000,
    });
    if (!data?.access_token) {
      throw new ApiError("Login response did not include a token.", { status: 500 });
    }
    setToken(data.access_token);
    return data;
  },

  me: () => request("GET", "/auth/me"),

  listWorkers: () => request("GET", "/workers/"),

  /**
   * POST /readings/scan — the one and only inference path.
   * `file` is a Blob/File of the captured frame.
   */
  scan: ({ file, workerId, badgeId, temperatureC, humidityPct, notes }) => {
    const form = new FormData();
    form.append("worker_id", workerId);
    form.append("image", file, file.name || "strip.jpg");
    if (badgeId) form.append("badge_id", badgeId);
    if (temperatureC !== undefined && temperatureC !== null && temperatureC !== "")
      form.append("temperature_c", String(temperatureC));
    if (humidityPct !== undefined && humidityPct !== null && humidityPct !== "")
      form.append("humidity_pct", String(humidityPct));
    if (notes) form.append("notes", notes);
    // Image analysis + model inference on a phone-sized JPEG: allow longer.
    return request("POST", "/readings/scan", { form, timeout: 60000 });
  },

  workerReadings: (code, limit = 30) =>
    request("GET", `/readings/worker/${encodeURIComponent(code)}?limit=${limit}`),
};
