import { useCallback, useEffect, useState } from "react";
import HistoryScreen from "./screens/HistoryScreen";
import LoginScreen from "./screens/LoginScreen";
import ResultScreen from "./screens/ResultScreen";
import ScanScreen from "./screens/ScanScreen";
import SettingsScreen from "./screens/SettingsScreen";
import { api, isLoggedIn, logout as clearToken } from "./lib/api";

const TABS = [
  { id: "scan", label: "Scan", icon: "\uD83D\uDCF8" },
  { id: "history", label: "History", icon: "\uD83D\uDCC8" },
  { id: "settings", label: "Settings", icon: "\u2699\uFE0F" },
];

const TITLES = {
  scan: "New scan",
  result: "Reading result",
  history: "History",
  settings: "Settings",
};

export default function App() {
  const [loggedIn, setLoggedIn] = useState(isLoggedIn());
  const [tab, setTab] = useState("scan");
  const [user, setUser] = useState(null);
  const [result, setResult] = useState(null);
  const [preview, setPreview] = useState(null);
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  );

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    let alive = true;
    api
      .me()
      .then((u) => alive && setUser(u))
      .catch(() => {
        if (!alive) return;
        clearToken();
        setLoggedIn(false);
      });
    return () => {
      alive = false;
    };
  }, [loggedIn]);

  const signOut = useCallback(() => {
    clearToken();
    setLoggedIn(false);
    setUser(null);
    setResult(null);
    setPreview(null);
    setTab("scan");
  }, []);

  const handleAuthError = useCallback(() => signOut(), [signOut]);

  if (!loggedIn) {
    return (
      <LoginScreen
        onLogin={() => {
          setLoggedIn(true);
          setTab("scan");
        }}
      />
    );
  }

  const showingResult = tab === "result" && result;

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-main">
          <span className="topbar-mark" aria-hidden="true">
            H₂S
          </span>
          <div>
            <h1 className="topbar-title">{TITLES[tab] || "H₂S Scanner"}</h1>
            <p className="topbar-sub">
              {user?.full_name || user?.username || "officer"} · SIH26118
            </p>
          </div>
        </div>
        {showingResult && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setTab("scan")}
          >
            Back
          </button>
        )}
      </header>

      {!online && (
        <p className="offline-banner" role="alert">
          You are offline — scans cannot be submitted until the connection returns.
        </p>
      )}

      <main className="content">
        {showingResult ? (
          <ResultScreen
            result={result}
            previewUrl={preview}
            onAuthError={handleAuthError}
            onNewScan={() => {
              if (preview) URL.revokeObjectURL(preview);
              setPreview(null);
              setResult(null);
              setTab("scan");
            }}
          />
        ) : tab === "history" ? (
          <HistoryScreen onAuthError={handleAuthError} />
        ) : tab === "settings" ? (
          <SettingsScreen user={user} onLogout={signOut} />
        ) : (
          <ScanScreen
            onError={handleAuthError}
            onResult={(res, previewUrl) => {
              if (preview) URL.revokeObjectURL(preview);
              setResult(res);
              setPreview(previewUrl);
              setTab("result");
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          />
        )}
      </main>

      <nav className="tabbar" aria-label="Main navigation">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`tab ${tab === t.id || (t.id === "scan" && tab === "result") ? "active" : ""}`}
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "page" : undefined}
          >
            <span className="tab-icon" aria-hidden="true">
              {t.icon}
            </span>
            <span className="tab-label">{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
