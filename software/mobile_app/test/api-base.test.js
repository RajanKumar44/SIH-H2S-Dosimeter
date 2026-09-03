/**
 * Unit tests for the API-base resolution logic in lib/api.js.
 *
 * Run with:  npm test        (node --test, no extra dependencies)
 *
 * These exist because resolving the backend address is the single most
 * demo-fragile piece of the mobile app, and it has exactly the failure mode
 * that looks like "the server is down":
 *
 *   * The phone camera needs a secure context, so on a real device the app is
 *     reached through an HTTPS tunnel whose hostname encodes the port
 *     (e.g. https://5174-abc.sandbox.novita.ai). The old code appended ":8000"
 *     to ANY non-local hostname, producing an unreachable URL.
 *   * Calling an http:// backend from an https:// page is blocked by the
 *     browser as mixed content before the request is ever sent.
 *
 * lib/api.js imports `import.meta.env` (Vite-only) at module scope inside
 * envBase(), but the two functions under test are pure and don't touch it, so
 * the module imports fine under plain node as long as a minimal `window` and
 * `localStorage` exist. Both are stubbed below.
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

const { derivePreviewApiBase, getApiBase, hasMixedContentIssue } = await import(
  "../src/lib/api.js"
);

/** Point the stubbed page at a given origin. */
function at(hostname, protocol = "https:") {
  globalThis.window.location = { hostname, protocol };
}

test.beforeEach(() => store.clear());

// ── derivePreviewApiBase ───────────────────────────────────────────────────

test("port-prefixed preview host maps the app port to the backend port", () => {
  assert.equal(
    derivePreviewApiBase("5174-abc123.sandbox.novita.ai", "https:"),
    "https://8000-abc123.sandbox.novita.ai",
  );
});

test("preview mapping preserves the rest of the hostname verbatim", () => {
  assert.equal(
    derivePreviewApiBase("3000-xyz-9f.app.github.dev", "https:"),
    "https://8000-xyz-9f.app.github.dev",
  );
});

test("preview mapping keeps the page's protocol (never downgrades to http)", () => {
  const out = derivePreviewApiBase("5174-abc.e2b.dev", "https:");
  assert.ok(out.startsWith("https://"), out);
});

test("a host that already targets the backend port maps to itself", () => {
  assert.equal(
    derivePreviewApiBase("8000-abc.e2b.dev", "https:"),
    "https://8000-abc.e2b.dev",
  );
});

test("non port-prefixed hosts are not treated as previews", () => {
  for (const h of ["example.com", "192.168.1.5", "localhost", "", "abc-5174.dev"]) {
    assert.equal(derivePreviewApiBase(h, "https:"), "", h);
  }
});

// ── getApiBase ─────────────────────────────────────────────────────────────

test("localhost falls back to the local backend on :8000", () => {
  at("localhost", "http:");
  assert.equal(getApiBase(), "http://localhost:8000");
  at("127.0.0.1", "http:");
  assert.equal(getApiBase(), "http://localhost:8000");
});

test("a LAN IP keeps the :8000 suffix (phone on the same Wi-Fi)", () => {
  at("192.168.1.5", "http:");
  assert.equal(getApiBase(), "http://192.168.1.5:8000");
});

test("an HTTPS preview host resolves to the HTTPS backend, NOT host:8000", () => {
  at("5174-abc123.sandbox.novita.ai", "https:");
  const base = getApiBase();
  assert.equal(base, "https://8000-abc123.sandbox.novita.ai");
  // The regression this guards: ":8000" appended to a tunnel host.
  assert.ok(!base.endsWith(":8000"), base);
});

test("a stored Settings override wins over every derivation", () => {
  at("5174-abc.sandbox.novita.ai", "https:");
  localStorage.setItem("h2s_mobile_api_base", "https://api.example.org/");
  // Trailing slashes are stripped so paths concatenate cleanly.
  assert.equal(getApiBase(), "https://api.example.org");
});

// ── hasMixedContentIssue ───────────────────────────────────────────────────

test("http API from an https page is flagged as mixed content", () => {
  at("5174-abc.sandbox.novita.ai", "https:");
  assert.equal(hasMixedContentIssue("http://192.168.1.5:8000"), true);
});

test("https API from an https page is fine", () => {
  at("5174-abc.sandbox.novita.ai", "https:");
  assert.equal(hasMixedContentIssue("https://8000-abc.sandbox.novita.ai"), false);
});

test("http API from an http page is fine (no mixed content on plain http)", () => {
  at("192.168.1.5", "http:");
  assert.equal(hasMixedContentIssue("http://192.168.1.5:8000"), false);
});

test("the default base on an HTTPS preview host is not itself mixed content", () => {
  at("5174-abc.sandbox.novita.ai", "https:");
  assert.equal(hasMixedContentIssue(getApiBase()), false);
});
