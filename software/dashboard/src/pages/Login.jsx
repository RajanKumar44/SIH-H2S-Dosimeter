import { useState } from "react";
import { api } from "../api";

export default function Login({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.login(username, password);
      onLogin();
    } catch (err) {
      setError(err.message || "Login failed");
    }
    setLoading(false);
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <h2>H2S Dosimeter</h2>
        <p className="subtitle">Safety Officer Login — SIH26118</p>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Username</label>
            <input
              type="text" value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="admin" autoFocus required
            />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input
              type="password" value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="admin123" required
            />
          </div>
          {error && <p className="error-msg">{error}</p>}
          <button
            type="submit" className="btn btn-primary"
            style={{ width: "100%", justifyContent: "center", marginTop: 8 }}
            disabled={loading}
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
        <p style={{fontSize: "11px", color: "var(--text-muted)", marginTop: 20, textAlign: "center"}}>
          Default: admin / admin123
        </p>
      </div>
    </div>
  );
}
