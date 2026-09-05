/**
 * Unit tests for native (Capacitor) API-base resolution in lib/api.js.
 *
 * Run with:  npm test        (node --test, no extra dependencies)
 *
 * Why these exist
 * ---------------
 * The installed Android APK reported "Cannot reach the server" while the SAME
 * phone could open https://sih-h2s-backend.onrender.com/health in Chrome.
 * Two independent defects had to line up for that:
 *
 *   1. Backend CORS did not allow the Capacitor WebView origin
 *      (https://localhost / capacitor://localhost) — fixed in
 *      software/backend/config.py and covered by backend/test_cors.py.
 *
 *   2. THIS file's subject: inside a Capacitor WebView the page is served from
 *      the app bundle, so `window.location.hostname` is "localhost". The
 *      generic resolver treated that as a dev machine and returned
 *      http://localhost:8000 — i.e. port 8000 on the HANDSET, where nothing
 *      listens. The request failed before it ever left the device.
 *
 * The regression risk cuts both ways, so both directions are asserted:
 *   * a native build must NOT fall back to localhost, and
 *   * `npm run dev` (also localhost!) must NOT be redirected to the deployed
 *     production backend.
 */
import assert from "node:assert/strict";
import test from "node:test";

// ── Minimal browser stubs (must exist BEFORE importing lib/api.js) ─────────
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  clear: () => store.clear(),
};
globalThis.window = { location: { hostname: "localhost", protocol: "http:" } };

const { getApiBase, isNativeApp, setApiBase } = await import("../src/lib/api.js");

const RENDER = "https://sih-h2s-backend.onrender.com";

/** Reset the stubbed page to a plain browser on localhost. */
function resetWindow() {
  delete globalThis.window.Capacitor;
  delete globalThis.window.cordova;
  globalThis.window.location = { hostname: "localhost", protocol: "http:" };
}

/** Simulate a Capacitor native WebView. */
function asNative({ hostname = "localhost", protocol = "https:", platform = "android" } = {}) {
  globalThis.window.location = { hostname, protocol };
  globalThis.window.Capacitor = {
    platform,
    isNativePlatform: () => true,
  };
}

test.beforeEach(() => {
  store.clear();
  resetWindow();
});

// ── isNativeApp detection ──────────────────────────────────────────────────

test("isNativePlatform() === true is detected as native", () => {
  asNative();
  assert.equal(isNativeApp(), true);
});

test("Capacitor.platform 'android' is detected as native", () => {
  globalThis.window.Capacitor = { platform: "android" };
  assert.equal(isNativeApp(), true);
});

test("Capacitor.platform 'ios' is detected as native", () => {
  globalThis.window.Capacitor = { platform: "ios" };
  assert.equal(isNativeApp(), true);
});

test("Capacitor.platform 'web' is NOT native (browser-served Capacitor app)", () => {
  globalThis.window.Capacitor = { platform: "web" };
  assert.equal(isNativeApp(), false);
});

test("legacy window.cordova is detected as native", () => {
  globalThis.window.cordova = {};
  assert.equal(isNativeApp(), true);
});

test("capacitor:// page protocol is detected as native", () => {
  globalThis.window.location = { hostname: "localhost", protocol: "capacitor:" };
  assert.equal(isNativeApp(), true);
});

test("ionic:// page protocol is detected as native", () => {
  globalThis.window.location = { hostname: "localhost", protocol: "ionic:" };
  assert.equal(isNativeApp(), true);
});

test("a plain browser on localhost is NOT native", () => {
  assert.equal(isNativeApp(), false);
});

test("a plain browser on a LAN IP is NOT native", () => {
  globalThis.window.location = { hostname: "192.168.1.5", protocol: "http:" };
  assert.equal(isNativeApp(), false);
});

test("isNativeApp() is safe when window is undefined (SSR/node)", () => {
  assert.equal(isNativeApp(undefined), false);
});

test("a throwing isNativePlatform() falls back to other signals, not a crash", () => {
  globalThis.window.Capacitor = {
    isNativePlatform() {
      throw new Error("bridge not ready");
    },
    platform: "android",
  };
  assert.equal(isNativeApp(), true);
});

test("a throwing isNativePlatform() with no other signal returns false", () => {
  globalThis.window.Capacitor = {
    isNativePlatform() {
      throw new Error("bridge not ready");
    },
  };
  assert.equal(isNativeApp(), false);
});

// ── getApiBase in the native build ─────────────────────────────────────────

test("native build targets the deployed backend, NOT localhost", () => {
  asNative();
  const base = getApiBase();
  assert.equal(base, RENDER);
  assert.ok(
    !base.includes("localhost"),
    `native build must never point at the handset itself, got ${base}`,
  );
});

test("native build on the capacitor:// scheme also targets the deployed backend", () => {
  globalThis.window.location = { hostname: "localhost", protocol: "capacitor:" };
  assert.equal(getApiBase(), RENDER);
});

test("native default is https (no mixed-content block in the WebView)", () => {
  asNative();
  assert.ok(getApiBase().startsWith("https://"), getApiBase());
});

// ── Overrides must still win ───────────────────────────────────────────────

test("Settings override beats the native default", () => {
  asNative();
  setApiBase("http://192.168.1.50:8000");
  assert.equal(getApiBase(), "http://192.168.1.50:8000");
});

test("Settings override is normalised (trailing slashes stripped)", () => {
  asNative();
  setApiBase("https://staging.example.com///");
  assert.equal(getApiBase(), "https://staging.example.com");
});

test("clearing the override restores the native default", () => {
  asNative();
  setApiBase("http://192.168.1.50:8000");
  setApiBase("");
  assert.equal(getApiBase(), RENDER);
});

// ── The other direction: dev server must not be hijacked ───────────────────

test("npm run dev on localhost still uses the local backend", () => {
  // Same hostname as the native case — only the Capacitor signal differs.
  assert.equal(getApiBase(), "http://localhost:8000");
});

test("browser on 127.0.0.1 still uses the local backend", () => {
  globalThis.window.location = { hostname: "127.0.0.1", protocol: "http:" };
  assert.equal(getApiBase(), "http://localhost:8000");
});

test("browser on a LAN IP still derives the LAN backend", () => {
  globalThis.window.location = { hostname: "192.168.1.5", protocol: "http:" };
  assert.equal(getApiBase(), "http://192.168.1.5:8000");
});

test("browser on a port-prefixed preview host still maps the port", () => {
  globalThis.window.location = {
    hostname: "5174-abc123.sandbox.novita.ai",
    protocol: "https:",
  };
  assert.equal(getApiBase(), "https://8000-abc123.sandbox.novita.ai");
});
