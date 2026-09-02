import { useState, useEffect } from "react";
import { api } from "../api";

export default function Alerts() {
  const [alerts, setAlerts] = useState([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await api.listAlerts(filter === "unacked");
      setAlerts(data);
    } catch (e) { console.error(e); }
    setLoading(false);
  }

  useEffect(() => { load(); }, [filter]);

  async function handleAck(id) {
    try {
      await api.acknowledgeAlert(id, "admin");
      load();
    } catch (e) { alert("Acknowledge failed: " + e.message); }
  }

  const typeIcon = { warning: "\u26A0\uFE0F", danger: "\uD83D\uDED1", critical: "\uD83D\uDCA5" };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Alerts</h2>
          <p className="subtitle">DGMS threshold breach notifications</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className={`btn ${filter === "all" ? "btn-primary" : "btn-outline"} btn-sm`}
                  onClick={() => setFilter("all")}>All</button>
          <button className={`btn ${filter === "unacked" ? "btn-danger" : "btn-outline"} btn-sm`}
                  onClick={() => setFilter("unacked")}>Unacknowledged</button>
        </div>
      </div>

      {loading ? (
        <div className="loading"><div className="loading-spinner" />Loading alerts...</div>
      ) : alerts.length === 0 ? (
        <div className="empty-state">
          <div className="icon">&#9989;</div>
          <p>No alerts to display</p>
        </div>
      ) : (
        <div className="table-card">
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Worker</th>
                <th>Dose</th>
                <th>Threshold</th>
                <th>Message</th>
                <th>Time</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map(a => (
                <tr key={a.id}>
                  <td><span className={`badge ${a.alert_type}`}>{typeIcon[a.alert_type] || ""} {a.alert_type}</span></td>
                  <td style={{ fontWeight: 600 }}>
                    {a.worker_code || `#${a.worker_id}`}
                    {a.worker_name && (
                      <div style={{ fontWeight: 400, fontSize: 12, color: "var(--text-muted)" }}>
                        {a.worker_name}
                      </div>
                    )}
                  </td>
                  <td style={{ fontWeight: 600 }}>{a.dose_at_alert.toFixed(1)}</td>
                  <td>{a.threshold}</td>
                  <td style={{ maxWidth: 300, fontSize: 12 }}>{a.message}</td>
                  <td style={{ fontSize: 12, color: "var(--text-muted)" }}>
                    {a.created_at ? new Date(a.created_at).toLocaleTimeString() : "—"}
                  </td>
                  <td>
                    {a.is_acknowledged
                      ? <span className="badge safe">Acked</span>
                      : <span className="badge danger">Pending</span>
                    }
                  </td>
                  <td>
                    {!a.is_acknowledged && (
                      <button className="btn btn-primary btn-sm" onClick={() => handleAck(a.id)}>
                        Acknowledge
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
