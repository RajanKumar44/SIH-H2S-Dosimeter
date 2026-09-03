import { useEffect, useState } from "react";
import DoseGauge from "../components/DoseGauge";
import HistoryChart from "../components/HistoryChart";
import { ApiError, api } from "../lib/api";
import {
  THRESHOLDS,
  UNIT,
  formatDose,
  resolveStatus,
  statusMeta,
} from "../lib/dose";

const DASH = "\u2014";

/**
 * ResultScreen — renders the ScanReadingOut payload from POST /readings/scan.
 *
 * Nothing is recomputed here: `dose_ppm_hr` comes from the ML model and
 * `exposure_status` from the backend's shared `evaluate_thresholds`.
 */
export default function ResultScreen({ result, previewUrl, onNewScan, onAuthError }) {
  const dose = Number(result?.dose_ppm_hr);
  const status = resolveStatus(result?.exposure_status, dose);
  const meta = statusMeta(status);
  const workerCode = result?.worker_code;

  const [history, setHistory] = useState(null);
  const [historyState, setHistoryState] = useState("loading"); // loading|ready|error
  const [historyError, setHistoryError] = useState("");

  useEffect(() => {
    if (!workerCode) {
      setHistoryState("error");
      setHistoryError("No worker code on this reading.");
      return undefined;
    }
    let alive = true;
    setHistoryState("loading");
    (async () => {
      try {
        const rows = await api.workerReadings(workerCode, 30);
        if (!alive) return;
        setHistory(rows || []);
        setHistoryState("ready");
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiError && err.kind === "auth") {
          onAuthError?.(err);
          return;
        }
        setHistoryError(
          err instanceof ApiError ? err.message : "History could not be loaded.",
        );
        setHistoryState("error");
      }
    })();
    return () => {
      alive = false;
    };
  }, [workerCode, onAuthError]);

  const lowConfidence =
    result?.image_confidence !== undefined && Number(result.image_confidence) < 0.6;
  const roiMissing = result?.roi_detected === false;

  const scannedAt = result?.scan_timestamp
    ? new Date(result.scan_timestamp).toLocaleString()
    : DASH;

  return (
    <div className="screen">
      <section className={`card result-hero tone-${meta.tone}`}>
        <p className="result-worker">
          {workerCode ? `${workerCode} · ${result.worker_name}` : "Reading"}
        </p>
        <DoseGauge dose={dose} status={status} />
        <h2 className="result-headline">{meta.headline}</h2>
        <p className="result-advice">{meta.advice}</p>
      </section>

      <section className="card">
        <h2 className="card-title">Exposure summary</h2>
        <dl className="kv">
          <div>
            <dt>Cumulative dose</dt>
            <dd className="kv-strong">
              {formatDose(dose)} <span className="kv-unit">{UNIT}</span>
            </dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <span className={`badge badge-${meta.tone}`}>{meta.label}</span>
            </dd>
          </div>
          <div>
            <dt>DGMS 8-hr limit</dt>
            <dd>
              {THRESHOLDS.danger} {UNIT}
            </dd>
          </div>
          <div>
            <dt>Alert raised</dt>
            <dd>{result?.alert_triggered ? "Yes" : "No"}</dd>
          </div>
        </dl>

        {result?.alert?.message && (
          <p className={`alert-banner tone-${meta.tone}`} role="alert">
            {result.alert.message}
          </p>
        )}
      </section>

      {(lowConfidence || roiMissing) && (
        <p className="inline-warn" role="alert">
          {roiMissing
            ? "The strip region could not be located confidently in this photo."
            : "Image quality was low for this scan."}{" "}
          Treat the value as indicative and re-scan with the strip filling the
          guide box in even light.
        </p>
      )}

      <section className="card">
        <h2 className="card-title">Dose history · {workerCode || DASH}</h2>
        {historyState === "loading" && (
          <div className="skeleton-row">
            <span className="spinner" aria-hidden="true" /> Loading history…
          </div>
        )}
        {historyState === "error" && <p className="inline-warn">{historyError}</p>}
        {historyState === "ready" && <HistoryChart readings={history} />}
      </section>

      <details className="card details">
        <summary>Measurement details</summary>
        <dl className="kv kv-compact">
          <div>
            <dt>ΔE2000</dt>
            <dd>{result?.delta_E ?? DASH}</dd>
          </div>
          <div>
            <dt>ΔE corrected</dt>
            <dd>{result?.delta_E_corr ?? DASH}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{result?.model_name || DASH}</dd>
          </div>
          <div>
            <dt>Model confidence</dt>
            <dd>{result?.model_confidence || DASH}</dd>
          </div>
          <div>
            <dt>Image confidence</dt>
            <dd>
              {result?.image_confidence !== undefined
                ? `${(Number(result.image_confidence) * 100).toFixed(0)}%`
                : DASH}
            </dd>
          </div>
          <div>
            <dt>Strip detected</dt>
            <dd>
              {result?.roi_detected ? "Yes" : "No"}
              {result?.roi_method ? ` (${result.roi_method})` : ""}
            </dd>
          </div>
          <div>
            <dt>Lighting corrected</dt>
            <dd>{result?.lighting_corrected ? "Yes" : "No reference card"}</dd>
          </div>
          <div>
            <dt>Scanned at</dt>
            <dd>{scannedAt}</dd>
          </div>
        </dl>

        {previewUrl && (
          <>
            <p className="field-label" style={{ marginTop: 12 }}>
              Analysed frame
            </p>
            <img src={previewUrl} alt="Analysed dosimeter strip" className="preview-img" />
          </>
        )}
      </details>

      <button type="button" className="btn btn-primary btn-lg btn-block" onClick={onNewScan}>
        Scan another wristband
      </button>
    </div>
  );
}
