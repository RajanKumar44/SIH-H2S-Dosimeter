import { useCallback, useEffect, useRef, useState } from "react";
import CameraCapture from "../components/CameraCapture";
import { ApiError, api, getLastWorker, setLastWorker } from "../lib/api";

/**
 * ScanScreen — worker selection → capture → POST /readings/scan.
 *
 * Everything after the upload happens in the existing backend: the ML pipeline
 * computes the dose and `evaluate_thresholds` decides the exposure status. This
 * screen only gathers inputs, manages loading/error state and hands the
 * response to the result screen.
 */
export default function ScanScreen({ onResult, onError }) {
  const [workers, setWorkers] = useState([]);
  const [workersError, setWorkersError] = useState("");
  const [loadingWorkers, setLoadingWorkers] = useState(true);
  const [workerId, setWorkerId] = useState(getLastWorker());

  const [image, setImage] = useState(null);
  const [showEnv, setShowEnv] = useState(false);
  const [temperatureC, setTemperatureC] = useState("");
  const [humidityPct, setHumidityPct] = useState("");
  const [notes, setNotes] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const imageRef = useRef(null);

  // Revoke the previous preview URL whenever the image changes/unmounts.
  useEffect(() => {
    imageRef.current = image;
    return () => {
      if (imageRef.current && imageRef.current !== image) {
        URL.revokeObjectURL(imageRef.current.previewUrl);
      }
    };
  }, [image]);

  // Roster refresh trigger. The roster lives in the backend and can change
  // while the app is open (an admin adds a worker, or the backend was still
  // waking up on the first try). Bumping this re-runs the fetch below, which
  // is what the Retry button and the resume-from-background handler do.
  const [rosterNonce, setRosterNonce] = useState(0);
  const reloadWorkers = useCallback(() => {
    // Reset the panel from the event that caused the reload, not from inside
    // the effect, so no extra render pass is triggered.
    setLoadingWorkers(true);
    setWorkersError("");
    setRosterNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const rows = await api.listWorkers();
        if (!alive) return;
        const active = (rows || []).filter((w) => w.is_active !== false);
        setWorkers(active);
        // Keep the remembered worker ONLY if it is still in the active roster.
        // A stale localStorage code (worker deactivated/renamed, or a reset
        // demo database) otherwise stays selected and every scan 404s with
        // "Active worker '...' not found."
        setWorkerId((cur) =>
          active.some((w) => w.worker_id === cur)
            ? cur
            : active[0]?.worker_id || "",
        );
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiError && err.kind === "auth") {
          onError?.(err);
          return;
        }
        setWorkersError(
          err instanceof ApiError
            ? err.message
            : "Could not load the worker roster.",
        );
      } finally {
        if (alive) setLoadingWorkers(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [onError, rosterNonce]);

  // The roster is fetched once on mount, so a worker added afterwards was
  // invisible until the app was killed and reopened. Re-fetch when the app
  // comes back to the foreground (Android backgrounds the webview freely) and
  // when connectivity returns after a failed first load.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") reloadWorkers();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", reloadWorkers);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", reloadWorkers);
    };
  }, [reloadWorkers]);

  function clearImage() {
    if (image) URL.revokeObjectURL(image.previewUrl);
    setImage(null);
    setError("");
  }

  async function submit() {
    setError("");
    if (!workerId) {
      setError("Select the worker whose wristband this is.");
      return;
    }
    if (!image) {
      setError("Capture a photo of the strip first.");
      return;
    }
    setSubmitting(true);
    try {
      const result = await api.scan({
        file: image.file,
        workerId,
        temperatureC,
        humidityPct,
        notes,
      });
      setLastWorker(workerId);
      onResult(result, image.previewUrl);
      setImage(null); // ownership of previewUrl passes to the result screen
      setNotes("");
    } catch (err) {
      if (err instanceof ApiError && err.kind === "auth") {
        onError?.(err);
        return;
      }
      setError(
        err instanceof ApiError
          ? err.message
          : "The scan could not be submitted. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const selected = workers.find((w) => w.worker_id === workerId);

  return (
    <div className="screen">
      <section className="card">
        <h2 className="card-title">1 · Worker</h2>

        {loadingWorkers ? (
          <div className="skeleton-row">
            <span className="spinner" aria-hidden="true" /> Loading roster…
          </div>
        ) : workersError ? (
          <>
            <p className="inline-error" role="alert">
              {workersError}
            </p>
            <button
              type="button"
              className="btn btn-outline btn-block"
              onClick={reloadWorkers}
            >
              Retry
            </button>
          </>
        ) : workers.length === 0 ? (
          <>
            {/* The roster genuinely lives in the backend, so this is accurate
                reporting — but it used to be a dead end: the fetch ran only on
                mount, so a worker added in the dashboard stayed invisible. */}
            <p className="inline-warn">
              No active workers found. Add a worker in the admin dashboard, then
              reload the roster.
            </p>
            <button
              type="button"
              className="btn btn-outline btn-block"
              onClick={reloadWorkers}
            >
              Reload roster
            </button>
          </>
        ) : (
          <>
            <label className="field">
              <span className="field-label">Wristband owner</span>
              <select
                className="input"
                value={workerId}
                onChange={(e) => setWorkerId(e.target.value)}
                disabled={submitting}
              >
                {workers.map((w) => (
                  <option key={w.worker_id} value={w.worker_id}>
                    {w.worker_id} — {w.full_name}
                  </option>
                ))}
              </select>
            </label>
            {selected && (
              <p className="field-hint">
                {selected.department || "—"}
                {selected.shift ? ` · ${selected.shift} shift` : ""}
              </p>
            )}
          </>
        )}
      </section>

      <section className="card">
        <h2 className="card-title">2 · Strip photo</h2>

        {image ? (
          <div className="preview">
            <img src={image.previewUrl} alt="Captured dosimeter strip" className="preview-img" />
            <p className="field-hint">
              {image.width}×{image.height} px · {(image.file.size / 1024).toFixed(0)} KB
              {image.originalBytes > image.file.size
                ? ` (compressed from ${(image.originalBytes / 1024).toFixed(0)} KB)`
                : ""}
            </p>
            {image.warnings.length > 0 && (
              <ul className="warn-list" role="alert">
                {image.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            <button
              type="button"
              className="btn btn-outline btn-block"
              onClick={clearImage}
              disabled={submitting}
            >
              Retake photo
            </button>
          </div>
        ) : (
          <CameraCapture onImage={setImage} disabled={submitting} />
        )}
      </section>

      <section className="card">
        <button
          type="button"
          className="link-btn"
          onClick={() => setShowEnv((v) => !v)}
          disabled={submitting}
        >
          {showEnv ? "Hide" : "Add"} environment &amp; notes (optional)
        </button>

        {showEnv && (
          <div className="grid-2">
            <label className="field">
              <span className="field-label">Temperature (°C)</span>
              <input
                className="input"
                type="number"
                inputMode="decimal"
                step="0.1"
                value={temperatureC}
                onChange={(e) => setTemperatureC(e.target.value)}
                placeholder="32.5"
                disabled={submitting}
              />
            </label>
            <label className="field">
              <span className="field-label">Humidity (%)</span>
              <input
                className="input"
                type="number"
                inputMode="decimal"
                step="1"
                min="0"
                max="100"
                value={humidityPct}
                onChange={(e) => setHumidityPct(e.target.value)}
                placeholder="68"
                disabled={submitting}
              />
            </label>
            <label className="field span-2">
              <span className="field-label">Notes</span>
              <input
                className="input"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="e.g. Shaft 3 checkpoint"
                disabled={submitting}
              />
            </label>
          </div>
        )}
      </section>

      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}

      <button
        type="button"
        className="btn btn-primary btn-lg btn-block sticky-cta"
        onClick={submit}
        disabled={submitting || !image || !workerId}
      >
        {submitting ? (
          <>
            <span className="spinner" aria-hidden="true" /> Analysing strip…
          </>
        ) : (
          "Analyse & log reading"
        )}
      </button>

      {submitting && (
        <p className="field-hint centered" role="status">
          Running ΔE2000 colour analysis and the dose model on the server. This
          usually takes a couple of seconds.
        </p>
      )}
    </div>
  );
}
