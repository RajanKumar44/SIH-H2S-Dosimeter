import { useState, useEffect } from "react";
import { api } from "./api";
import Dashboard from "./pages/Dashboard";
import Workers from "./pages/Workers";
import SubmitReading from "./pages/SubmitReading";
import Alerts from "./pages/Alerts";
import Reports from "./pages/Reports";
import Login from "./pages/Login";

function getPage() {
  const hash = window.location.hash.replace("#/", "") || "dashboard";
  return hash;
}

function Sidebar({ page, onNavigate, onLogout, user }) {
  const items = [
    { id: "dashboard", label: "Dashboard", icon: "\uD83D\uDCCA" },
    { id: "workers",   label: "Workers",   icon: "\uD83D\uDC77" },
    { id: "submit",    label: "Submit Reading", icon: "\uD83E\uDDEA" },
    { id: "alerts",    label: "Alerts",    icon: "\uD83D\uDD14" },
    { id: "reports",   label: "Reports",   icon: "\uD83D\uDCC4" },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <h1>H2S Dosimeter</h1>
        <p>SIH26118 Admin Panel</p>
      </div>
      <nav className="sidebar-nav">
        {items.map(item => (
          <button
            key={item.id}
            className={`nav-item ${page === item.id ? "active" : ""}`}
            onClick={() => onNavigate(item.id)}
          >
            <span className="icon">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div style={{ marginBottom: 8 }}>
          Signed in as <strong>{user?.full_name || user?.username || "admin"}</strong>
        </div>
        <button className="btn btn-outline btn-sm" onClick={onLogout} style={{ width: "100%", justifyContent: "center" }}>
          Sign Out
        </button>
      </div>
    </aside>
  );
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(api.isLoggedIn());
  const [page, setPage] = useState(getPage());
  const [user, setUser] = useState(null);

  useEffect(() => {
    function onHash() { setPage(getPage()); }
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (loggedIn) {
      api.me().then(setUser).catch(() => {
        setLoggedIn(false);
        api.logout();
      });
    }
  }, [loggedIn]);

  function navigate(id) {
    window.location.hash = `#/${id}`;
    setPage(id);
  }

  function handleLogout() {
    api.logout();
    setLoggedIn(false);
    setUser(null);
    navigate("login");
  }

  if (!loggedIn || page === "login") {
    return <Login onLogin={() => { setLoggedIn(true); navigate("dashboard"); }} />;
  }

  const pages = {
    dashboard: <Dashboard />,
    workers: <Workers />,
    submit: <SubmitReading user={user} />,
    alerts: <Alerts />,
    reports: <Reports />,
  };

  return (
    <div className="app-layout">
      <Sidebar page={page} onNavigate={navigate} onLogout={handleLogout} user={user} />
      <main className="main-content">
        {pages[page] || <Dashboard />}
      </main>
    </div>
  );
}
