import { useState } from "react";
import {
  ApiError,
  api,
  getApiBase,
  hasMixedContentIssue,
  setApiBase,
} from "../lib/api";
import { THRESHOLDS, UNIT } from "../lib/dose";

/**
 * SettingsScreen — server address, connectivity check and sign-out.
 * The API base is configurable at runtime so the demo phone can be pointed at
 * whatever LAN address the backend happens to have.
 */
export default function SettingsScreen({ user, onLogout }) {
  const [base, setBase] = useState(getApiBase());
  const [probe, setProbe] = useState(null); // {ok, text}
  const [busy, setBusy] = useState(false);

  async function test() {
    setBusy(true);
    setProbe(null);
    try {
      setApiBase(base);
      const h = await api.health();
      if (h?.status !== "ok") {
        setProbe({ ok: false, text: `Server replied but reported "${h?.status}".` });
        return;
      }
      // /health also reports whether the ML scan path is ready. Show it here so
      // a missing trained model is caught BEFORE a scan is attempted, instead
      // of surfacing as a 503 mid-demo.
      const mlReady = h.ml?.available !== false;
      setProbe({
        ok: mlReady,
        text: mlReady
          ? `Connected · database ${h.database} · AI model ready · API v${h.version}`
          : `Connected, but the AI model is NOT ready — scans will fail. ${
              h.ml?.hint || "Train the model in software/ml_pipeline."
            }`,
      });
    } catch (err) {
      setProbe({
        ok: false,
        text: err instanceof ApiError ? err.message : "Could not reach the server.",
      });
    } finally {
      setBusy(false);
    }
  }

  const mixedContent = hasMixedContentIssue(base);

  return (
    <div className="screen">
      <section className="card">
        <h2 className="card-title">Connection</h2>
        <label className="field">
          <span className="field-label">API base URL</span>
          <input
            className="input"
            value={base}
            onChange={(e) => setBase(e.target.value)}
            placeholder="http://192.168.1.5:8000"
            autoCapitalize="none"
            spellCheck="false"
          />
          <span className="field-hint">
            The FastAPI backend from <code>software/backend</code>. Use the
            machine&apos;s LAN IP, not <code>localhost</code>, when testing on a phone.
          </span>
        </label>
        <button type="button" className="btn btn-outline btn-block" onClick={test} disabled={busy}>
          {busy ? (
            <>
              <span className="spinner" aria-hidden="true" /> Testing…
            </>
          ) : (
            "Save & test connection"
          )}
        </button>
        {mixedContent && (
          <p className="inline-warn" role="alert">
            This page is served over HTTPS but the API address uses{" "}
            <code>http://</code>. The browser will block those requests as mixed
            content. Use an <code>https://</code> backend address.
          </p>
        )}
        {probe && (
          <p className={probe.ok ? "inline-ok" : "inline-error"} role="status">
            {probe.text}
          </p>
        )}
      </section>

      <section className="card">
        <h2 className="card-title">Session</h2>
        <dl className="kv kv-compact">
          <div>
            <dt>Signed in as</dt>
            <dd>{user?.full_name || user?.username || "—"}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>{user?.role || "officer"}</dd>
          </div>
        </dl>
        <button type="button" className="btn btn-ghost btn-block" onClick={onLogout}>
          Sign out
        </button>
      </section>

      <section className="card">
        <h2 className="card-title">DGMS thresholds</h2>
        <dl className="kv kv-compact">
          <div>
            <dt>Warning</dt>
            <dd>
              {THRESHOLDS.warning} {UNIT}
            </dd>
          </div>
          <div>
            <dt>Danger (8-hr TWA)</dt>
            <dd>
              {THRESHOLDS.danger} {UNIT}
            </dd>
          </div>
          <div>
            <dt>Critical</dt>
            <dd>
              {THRESHOLDS.critical} {UNIT}
            </dd>
          </div>
        </dl>
        <p className="field-hint">
          Alert severity is decided by the backend; these values mirror
          <code> routes/readings.py</code> for display only.
        </p>
      </section>
    </div>
  );
}
