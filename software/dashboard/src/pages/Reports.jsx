import { useState, useEffect } from "react";
import { api } from "../api";
import {
  Chart as ChartJS,
  CategoryScale, LinearScale, PointElement, LineElement,
  Title, Tooltip, Legend, Filler,
} from "chart.js";
import { Line } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

export default function Reports() {
  const [workerId, setWorkerId] = useState("WRK001");
  const [report, setReport] = useState(null);
  const [workers, setWorkers] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.listWorkers().then(setWorkers).catch(console.error);
  }, []);

  async function loadReport() {
    setLoading(true);
    try {
      const data = await api.getWorkerReport(workerId);
      setReport(data);
    } catch (e) { alert("Error: " + e.message); }
    setLoading(false);
  }

  useEffect(() => { loadReport(); }, [workerId]);

  const chartData = report?.readings?.length ? {
    labels: report.readings.map((r, i) => `#${i + 1}`),
    datasets: [
      {
        label: "Dose (ppm.hr)",
        data: report.readings.map(r => r.dose_ppm_hr),
        borderColor: "#6366f1",
        backgroundColor: "rgba(99,102,241,0.1)",
        tension: 0.3, fill: true, pointRadius: 4,
      },
      {
        label: "DGMS Limit (80)",
        data: report.readings.map(() => 80),
        borderColor: "#ef4444",
        borderDash: [8, 4],
        pointRadius: 0,
        borderWidth: 2,
      },
      {
        label: "Warning (60)",
        data: report.readings.map(() => 60),
        borderColor: "#f59e0b",
        borderDash: [4, 4],
        pointRadius: 0,
        borderWidth: 1,
      },
    ],
  } : null;

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Reports</h2>
          <p className="subtitle">DGMS compliance reports with exposure timeline</p>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
        <div className="form-group" style={{ minWidth: 200 }}>
          <label>Worker</label>
          <select value={workerId} onChange={e => setWorkerId(e.target.value)}>
            {workers.map(w => (
              <option key={w.worker_id} value={w.worker_id}>
                {w.worker_id} — {w.full_name}
              </option>
            ))}
          </select>
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8 }}>
          <button className="btn btn-primary" onClick={loadReport}>Refresh</button>
          <button className="btn btn-outline" onClick={() => api.downloadPdf(workerId)}>
            Download PDF
          </button>
        </div>
      </div>

      {loading ? (
        <div className="loading"><div className="loading-spinner" />Loading report...</div>
      ) : !report ? null : (
        <>
          <div className="stats-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
            <div className="stat-card">
              <div className="stat-label">Total Readings</div>
              <div className="stat-value">{report.total_readings}</div>
            </div>
            <div className={`stat-card ${report.max_dose_ppm_hr >= 80 ? "danger" : report.max_dose_ppm_hr >= 60 ? "warning" : "safe"}`}>
              <div className="stat-label">Max Dose</div>
              <div className="stat-value">{report.max_dose_ppm_hr?.toFixed(1)}</div>
              <div className="stat-sub">ppm.hr</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Avg Dose</div>
              <div className="stat-value">{report.avg_dose_ppm_hr?.toFixed(1)}</div>
              <div className="stat-sub">ppm.hr</div>
            </div>
            <div className={`stat-card ${report.dgms_compliant ? "safe" : "danger"}`}>
              <div className="stat-label">DGMS Status</div>
              <div className="stat-value" style={{ fontSize: 22 }}>
                {report.dgms_compliant ? "Compliant" : "Non-Compliant"}
              </div>
            </div>
          </div>

          {chartData && (
            <div className="chart-card" style={{ marginBottom: 24 }}>
              <h3>Exposure Timeline — {report.full_name}</h3>
              <Line data={chartData} options={{
                responsive: true,
                plugins: {
                  legend: { labels: { color: "#9aa0b4" } },
                  tooltip: { callbacks: { label: c => `${c.dataset.label}: ${c.raw} ppm.hr` } },
                },
                scales: {
                  x: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#6b7185" } },
                  y: {
                    grid: { color: "rgba(255,255,255,0.05)" },
                    ticks: { color: "#6b7185" },
                    title: { display: true, text: "Dose (ppm.hr)", color: "#6b7185" },
                  },
                },
              }} />
            </div>
          )}

          <div className="table-card">
            <div className="table-card-header">
              <h3>Reading Details</h3>
            </div>
            <table>
              <thead>
                <tr><th>#</th><th>Timestamp</th><th>Dose</th><th>DeltaE</th><th>Temp</th><th>Humidity</th></tr>
              </thead>
              <tbody>
                {report.readings.map((r, i) => (
                  <tr key={r.id}>
                    <td>{i + 1}</td>
                    <td style={{ fontSize: 12 }}>{r.timestamp ? new Date(r.timestamp).toLocaleString() : "—"}</td>
                    <td style={{ fontWeight: 600 }}>{r.dose_ppm_hr?.toFixed(1)}</td>
                    <td>{r.delta_E?.toFixed(3) || "—"}</td>
                    <td>{r.temperature_c?.toFixed(1) || "—"}</td>
                    <td>{r.humidity_pct?.toFixed(1) || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}
