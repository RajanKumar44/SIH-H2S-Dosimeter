import { useState } from "react";
import { ApiError, api, getApiBase, setApiBase } from "../lib/api";

/**
 * LoginScreen — officer sign-in against the existing POST /auth/login.
 *
 * Workers are data subjects, not accounts (see CLAUDE.md), so the field app
 * authenticates as the safety officer performing the round.
 */
export default function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [base, setBase] = useState(getApiBase());
  const [showBase, setShowBase] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (!username.trim() || !password) {
      setError("Enter both the username and the password.");
      return;
    }
    setBusy(true);
    try {
      setApiBase(base);
      await api.login(username.trim(), password);
      onLogin();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 401
            ? "Incorrect username or password."
            : err.message
          : "Sign-in failed. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen screen-login">
      <header className="login-brand">
        <div className="login-mark" aria-hidden="true">
          H₂S
        </div>
        <h1>H₂S Field Scanner</h1>
        <p>
          SIH26118 · Passive colorimetric exposure dosimeter
          <br />
          AI-based quantitative reading
        </p>
      </header>

      <form className="card" onSubmit={submit}>
        <h2 className="card-title">Safety officer sign-in</h2>

        <label className="field">
          <span className="field-label">Username</span>
          <input
            className="input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck="false"
            disabled={busy}
          />
        </label>

        <label className="field">
          <span className="field-label">Password</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            disabled={busy}
          />
        </label>

        <button
          type="button"
          className="link-btn"
          onClick={() => setShowBase((v) => !v)}
        >
          {showBase ? "Hide" : "Change"} server address
        </button>

        {showBase && (
          <label className="field">
            <span className="field-label">API base URL</span>
            <input
              className="input"
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder="http://192.168.1.5:8000"
              autoCapitalize="none"
              spellCheck="false"
              disabled={busy}
            />
            <span className="field-hint">
              Point this at the machine running the FastAPI backend. A phone
              cannot reach the laptop&apos;s <code>localhost</code>.
            </span>
          </label>
        )}

        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>
          {busy ? (
            <>
              <span className="spinner" aria-hidden="true" /> Signing in…
            </>
          ) : (
            "Sign in"
          )}
        </button>

        <p className="field-hint centered">Demo credentials: admin / admin123</p>
      </form>
    </div>
  );
}
