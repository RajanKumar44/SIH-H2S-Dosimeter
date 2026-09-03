import { useCallback, useEffect, useState } from "react";
import HistoryChart from "../components/HistoryChart";
import { ApiError, api, getLastWorker, setLastWorker } from "../lib/api";
import { UNIT, classifyDose, formatDose, statusMeta } from "../lib/dose";

const DASH = "\u2014";

/**
 * HistoryScreen — per-worker trend + reading list from
 * `GET /readings/worker/{code}` (an endpoint that already exists).
 */
export default function HistoryScreen({ onAuthError }) {
  const [workers, setWorkers] = useState([]);
  const [workerId, setWorkerId] = useState(getLastWorker());
  const [rows, setRows] = useState([]);
  const [state, setState] = useState("loading"); // loading|ready|error
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const list = await api.listWorkers();
        if (!alive) return;
        const active = (list || []).filter((w) => w.is_active !== false);
        setWorkers(active);
        setWorkerId((cur) => cur || active[0]?.worker_id || "");
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiError && err.kind === "auth") return onAuthError?.(err);
        setError(err instanceof ApiError ? err.message : "Could not load workers.");
        setState("error");
      }
    })();
    return () => {
      alive = false;
    };
  }, [onAuthError]);

  const load = useCallback(
    async (code) => {
      if (!code) return;
      setState("loading");
      setError("");
      try {
        const data = await api.workerReadings(code, 30);
        setRows(data || []);
        setState("ready");
      } catch (err) {
        if (err instanceof ApiError && err.kind === "auth") return onAuthError?.(err);
        setError(err instanceof ApiError ? err.message : "Could not load readings.");
        setState("error");
      }
    },
    [onAuthError],
  );

  useEffect(() => {
    if (workerId) {
      setLastWorker(workerId);
      load(workerId);
    }
  }, [workerId, load]);

  const latest = rows.length
    ? rows.reduce((a, b) =>
        new Date(a.scan_timestamp || 0) > new Date(b.scan_timestamp || 0) ? a : b,
      )
    : null;
  const latestMeta = latest ? statusMeta(classifyDose(latest.dose_ppm_hr)) : null;

  return (
    <div className="screen">
      <section className="card">
        <h2 className="card-title">Exposure history</h2>
        <label className="field">
          <span className="field-label">Worker</span>
          <select
            className="input"
            value={workerId}
            onChange={(e) => setWorkerId(e.target.value)}
          >
            {workers.length === 0 && <option value="">No workers</option>}
            {workers.map((w) => (
              <option key={w.worker_id} value={w.worker_id}>
                {w.worker_id} — {w.full_name}
              </option>
            ))}
          </select>
        </label>

        {latest && (
          <p className="field-hint">
            Latest: <strong>{formatDose(latest.dose_ppm_hr)} {UNIT}</strong>{" "}
            <span className={`badge badge-${latestMeta.tone}`}>{latestMeta.label}</span>
          </p>
        )}
      </section>

      <section className="card">
        {state === "loading" && (
          <div className="skeleton-row">
            <span className="spinner" aria-hidden="true" /> Loading readings…
          </div>
        )}
        {state === "error" && (
          <>
            <p className="inline-error" role="alert">
              {error}
            </p>
            <button
              type="button"
              className="btn btn-outline btn-block"
              onClick={() => load(workerId)}
            >
              Retry
            </button>
          </>
        )}
        {state === "ready" && <HistoryChart readings={rows} />}
      </section>

      {state === "ready" && rows.length > 0 && (
        <section className="card">
          <h2 className="card-title">Recent readings</h2>
          <ul className="reading-list">
            {rows
              .slice()
              .sort(
                (a, b) =>
                  new Date(b.scan_timestamp || 0) - new Date(a.scan_timestamp || 0),
              )
              .map((r) => {
                const m = statusMeta(classifyDose(r.dose_ppm_hr));
                return (
                  <li key={r.id} className="reading-item">
                    <span className="dot" style={{ background: m.color }} aria-hidden="true" />
                    <span className="reading-dose">
                      {formatDose(r.dose_ppm_hr)} <em>{UNIT}</em>
                    </span>
                    <span className="reading-when">
                      {r.scan_timestamp
                        ? new Date(r.scan_timestamp).toLocaleString(undefined, {
                            day: "2-digit",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : DASH}
                    </span>
                    <span className={`badge badge-${m.tone} badge-sm`}>{m.label}</span>
                  </li>
                );
              })}
          </ul>
        </section>
      )}
    </div>
  );
}
