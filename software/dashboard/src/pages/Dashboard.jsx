import { useState, useEffect } from "react";
import { api } from "../api";
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, BarElement, ArcElement,
  PointElement, LineElement, Title, Tooltip, Legend, Filler,
} from "chart.js";
import { Bar, Doughnut, Line } from "react-chartjs-2";

ChartJS.register(
  CategoryScale, LinearScale, BarElement, ArcElement,
  PointElement, LineElement, Title, Tooltip, Legend, Filler
);

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [alertCounts, setAlertCounts] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [summary, counts] = await Promise.all([
          api.dashboardSummary(),
          api.alertCounts(),
        ]);
        setData(summary);
        setAlertCounts(counts);
      } catch (e) {
        console.error("Dashboard load error:", e);
      }
      setLoading(false);
    }
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div className="loading"><div className="loading-spinner" />Loading dashboard...</div>;
  if (!data) return <div className="empty-state"><p>Failed to load dashboard data. Is the backend running?</p></div>;

  const safeCount = data.workers.filter(w => w.status === "safe").length;
  const warnCount = data.workers_in_warning;
  const dangerCount = data.workers_in_danger;

  const statusChart = {
    labels: ["Safe", "Warning", "Danger"],
    datasets: [{
      data: [safeCount, warnCount, dangerCount],
      backgroundColor: ["#22c55e", "#f59e0b", "#ef4444"],
      borderWidth: 0,
      hoverOffset: 8,
    }],
  };

  const workerDoses = data.workers
    .filter(w => w.latest_dose_ppm_hr != null)
    .sort((a, b) => b.latest_dose_ppm_hr - a.latest_dose_ppm_hr)
    .slice(0, 10);

  const doseChart = {
    labels: workerDoses.map(w => w.worker_id),
    datasets: [{
      label: "Latest Dose (ppm.hr)",
      data: workerDoses.map(w => w.latest_dose_ppm_hr),
      backgroundColor: workerDoses.map(w =>
        w.latest_dose_ppm_hr >= 80 ? "#ef4444" :
        w.latest_dose_ppm_hr >= 60 ? "#f59e0b" : "#6366f1"
      ),
      borderRadius: 6,
      borderSkipped: false,
    }],
  };

  const totalAlerts = alertCounts
    ? Object.values(alertCounts).reduce((s, v) => s + v.total, 0) : 0;
  const unackedAlerts = alertCounts
    ? Object.values(alertCounts).reduce((s, v) => s + v.unacked, 0) : 0;

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Dashboard</h2>
          <p className="subtitle">Real-time H2S exposure monitoring</p>
        </div>
        <span style={{fontSize: "12px", color: "var(--text-muted)"}}>
          Auto-refreshes every 30s
        </span>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Total Workers</div>
          <div className="stat-value">{data.total_workers}</div>
          <div className="stat-sub">{data.active_workers} active</div>
        </div>
        <div className="stat-card safe">
          <div className="stat-label">Safe</div>
          <div className="stat-value" style={{color: "var(--safe)"}}>{safeCount}</div>
          <div className="stat-sub">Below 60 ppm.hr</div>
        </div>
        <div className={`stat-card warning ${warnCount > 0 ? "pulse-danger" : ""}`}>
          <div className="stat-label">Warning</div>
          <div className="stat-value" style={{color: "var(--warning)"}}>{warnCount}</div>
          <div className="stat-sub">60-80 ppm.hr</div>
        </div>
        <div className={`stat-card danger ${dangerCount > 0 ? "pulse-danger" : ""}`}>
          <div className="stat-label">Danger</div>
          <div className="stat-value" style={{color: "var(--danger)"}}>{dangerCount}</div>
          <div className="stat-sub">Above 80 ppm.hr</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Readings Today</div>
          <div className="stat-value">{data.total_readings_today}</div>
          <div className="stat-sub">Scans submitted</div>
        </div>
        <div className={`stat-card ${unackedAlerts > 0 ? "danger" : ""}`}>
          <div className="stat-label">Active Alerts</div>
          <div className="stat-value" style={{color: unackedAlerts > 0 ? "var(--danger)" : "var(--text-primary)"}}>
            {unackedAlerts}
          </div>
          <div className="stat-sub">{totalAlerts} total</div>
        </div>
      </div>

      <div className="charts-grid">
        <div className="chart-card">
          <h3>Worker Status Distribution</h3>
          <div style={{ maxWidth: 260, margin: "0 auto" }}>
            <Doughnut data={statusChart} options={{
              cutout: "65%",
              plugins: { legend: { position: "bottom", labels: { color: "#9aa0b4", padding: 16 } } },
            }} />
          </div>
        </div>
        <div className="chart-card">
          <h3>Top Exposure Doses</h3>
          <Bar data={doseChart} options={{
            indexAxis: "y",
            plugins: {
              legend: { display: false },
              tooltip: { callbacks: { label: (c) => `${c.raw} ppm.hr` } },
            },
            scales: {
              x: {
                grid: { color: "rgba(255,255,255,0.05)" },
                ticks: { color: "#6b7185" },
                title: { display: true, text: "Dose (ppm.hr)", color: "#6b7185" },
              },
              y: { grid: { display: false }, ticks: { color: "#9aa0b4" } },
            },
          }} />
        </div>
      </div>

      <div className="table-card">
        <div className="table-card-header">
          <h3>All Workers</h3>
          <span style={{fontSize: "12px", color: "var(--text-muted)"}}>{data.workers.length} workers</span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Worker ID</th>
              <th>Name</th>
              <th>Site</th>
              <th>Shift</th>
              <th>Latest Dose</th>
              <th>Readings</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.workers.map(w => (
              <tr key={w.worker_id}>
                <td style={{fontWeight: 600, color: "var(--text-primary)"}}>{w.worker_id}</td>
                <td>{w.full_name}</td>
                <td>{w.site || "—"}</td>
                <td>{w.shift || "—"}</td>
                <td style={{fontWeight: 600}}>
                  {w.latest_dose_ppm_hr != null ? `${w.latest_dose_ppm_hr.toFixed(1)} ppm.hr` : "—"}
                </td>
                <td>{w.total_readings}</td>
                <td>
                  <span className={`badge ${w.status}`}>
                    {w.status === "safe" ? "Safe" : w.status === "warning" ? "Warning" : "Danger"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
