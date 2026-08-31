import { useState, useEffect } from "react";
import { api } from "../api";

export default function Workers() {
  const [workers, setWorkers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    worker_id: "", full_name: "", department: "", site: "", shift: "A", designation: "", phone: "",
  });
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try { setWorkers(await api.listWorkers()); }
    catch (e) { console.error(e); }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function handleCreate(e) {
    e.preventDefault();
    setError("");
    try {
      await api.createWorker(form);
      setShowForm(false);
      setForm({ worker_id: "", full_name: "", department: "", site: "", shift: "A", designation: "", phone: "" });
      load();
    } catch (err) { setError(err.message); }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Workers</h2>
          <p className="subtitle">Manage monitored workers</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? "Cancel" : "+ Add Worker"}
        </button>
      </div>

      {showForm && (
        <div className="table-card" style={{ marginBottom: 20 }}>
          <div className="table-card-header"><h3>Register New Worker</h3></div>
          <form onSubmit={handleCreate} style={{ padding: 20, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div className="form-group">
              <label>Worker ID</label>
              <input value={form.worker_id} onChange={e => setForm({...form, worker_id: e.target.value})}
                     placeholder="WRK009" required />
            </div>
            <div className="form-group">
              <label>Full Name</label>
              <input value={form.full_name} onChange={e => setForm({...form, full_name: e.target.value})}
                     placeholder="Full Name" required />
            </div>
            <div className="form-group">
              <label>Department</label>
              <input value={form.department} onChange={e => setForm({...form, department: e.target.value})}
                     placeholder="Drilling" />
            </div>
            <div className="form-group">
              <label>Site</label>
              <input value={form.site} onChange={e => setForm({...form, site: e.target.value})}
                     placeholder="Refinery Unit-1" />
            </div>
            <div className="form-group">
              <label>Shift</label>
              <select value={form.shift} onChange={e => setForm({...form, shift: e.target.value})}>
                <option>A</option><option>B</option><option>C</option><option>General</option>
              </select>
            </div>
            <div className="form-group">
              <label>Designation</label>
              <input value={form.designation} onChange={e => setForm({...form, designation: e.target.value})}
                     placeholder="Operator" />
            </div>
            {error && <p className="error-msg" style={{ gridColumn: "1/-1" }}>{error}</p>}
            <div style={{ gridColumn: "1/-1" }}>
              <button type="submit" className="btn btn-primary">Create Worker</button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div className="loading"><div className="loading-spinner" />Loading workers...</div>
      ) : (
        <div className="table-card">
          <div className="table-card-header">
            <h3>All Workers</h3>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{workers.length} workers</span>
          </div>
          <table>
            <thead>
              <tr>
                <th>ID</th><th>Name</th><th>Department</th><th>Site</th>
                <th>Shift</th><th>Designation</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {workers.map(w => (
                <tr key={w.id}>
                  <td style={{ fontWeight: 600, color: "var(--text-primary)" }}>{w.worker_id}</td>
                  <td>{w.full_name}</td>
                  <td>{w.department || "—"}</td>
                  <td>{w.site || "—"}</td>
                  <td>{w.shift || "—"}</td>
                  <td>{w.designation || "—"}</td>
                  <td><span className={`badge ${w.is_active ? "safe" : "danger"}`}>
                    {w.is_active ? "Active" : "Inactive"}
                  </span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
