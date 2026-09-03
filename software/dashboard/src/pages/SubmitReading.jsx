import { useState, useEffect, useMemo } from "react";
import { api } from "../api";

/**
 * SubmitReading
 * =============
 * Logs a wristband strip scan the same way the Phase 4 mobile app will: the
 * client sends the colorimetric measurements (CIE DE2000 deltaE, Lab, RGB)
 * plus the dose predicted by the ML model, and the backend remains the single
 * source of truth for storage, DGMS threshold evaluation and alert creation.
 *
 * Nothing here re-implements backend logic. The outcome shown after submission
 * comes from the API response (`alert_triggered`) and from the alert row the
 * backend created — never from a threshold comparison in React.
 */

// ── Demo presets ───────────────────────────────────────────────────────────
// These are NOT canned results. They only pre-fill the form; submission always
// goes through the real POST /readings/ endpoint and the backend decides the
// outcome. The colour values are the actual output of the Phase 1 pipeline's
// simulate_strip_color() physics model at each dose, so the deltaE / Lab / RGB
// combinations stay consistent with what the trained model would see.
const PRESETS = [
  {
    key: "safe",
    label: "Safe",
    tone: "safe",
    hint: "35 ppm.hr — normal occupational exposure, well under the DGMS limit",
    values: {
      dose_ppm_hr: "35.0",
      delta_E: "17.303",
      delta_E_corr: "17.303",
      R: "108.3", G: "142.3", B: "122.3",
      L_star: "56.14", a_star: "-16.20", b_star: "6.81",
      temperature_c: "26.0", humidity_pct: "50.0",
      model_confidence: "medium",
      notes: "Demo preset: safe exposure level",
    },
  },
  {
    key: "warning",
    label: "Warning",
    tone: "warning",
    hint: "68 ppm.hr — past the 60 ppm.hr warning threshold",
    values: {
      dose_ppm_hr: "68.0",
      delta_E: "22.134",
      delta_E_corr: "22.134",
      R: "125.8", G: "131.4", B: "111.4",
      L_star: "53.93", a_star: "-5.87", b_star: "10.12",
      temperature_c: "31.0", humidity_pct: "68.0",
      model_confidence: "medium",
      notes: "Demo preset: approaching DGMS limit",
    },
  },
  {
    key: "danger",
    label: "Danger",
    tone: "danger",
    hint: "88 ppm.hr — DGMS 8-hour limit (80 ppm.hr) exceeded",
    values: {
      dose_ppm_hr: "88.0",
      delta_E: "25.480",
      delta_E_corr: "25.480",
      R: "133.4", G: "126.6", B: "106.6",
      L_star: "53.12", a_star: "-0.99", b_star: "11.81",
      temperature_c: "34.0", humidity_pct: "75.0",
      model_confidence: "medium",
      notes: "Demo preset: DGMS limit exceeded",
    },
  },
  {
    key: "critical",
    label: "Critical",
    tone: "critical",
    hint: "108 ppm.hr — immediate-evacuation band (above 100 ppm.hr)",
    values: {
      dose_ppm_hr: "108.0",
      delta_E: "28.651",
      delta_E_corr: "28.651",
      R: "139.3", G: "123.0", B: "103.0",
      L_star: "52.56", a_star: "2.94", b_star: "13.25",
      temperature_c: "38.0", humidity_pct: "82.0",
      model_confidence: "medium",
      notes: "Demo preset: critical acute exposure",
    },
  },
];

const DASH = "\u2014";

function todayIso() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const EMPTY_FORM = {
  worker_id: "",
  badge_id: "",
  delta_E: "",
  delta_E_corr: "",
  dose_ppm_hr: "",
  R: "", G: "", B: "",
  L_star: "", a_star: "", b_star: "",
  model_confidence: "medium",
  temperature_c: "",
  humidity_pct: "",
  shift_date: todayIso(),
  notes: "",
};

/** Parse a form string into a number, or undefined when left blank/invalid. */
function toNum(v) {
  if (v === "" || v === null || v === undefined) return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

function validate(form) {
  const errors = {};

  if (!form.worker_id) {
    errors.worker_id = "Select the worker this wristband belongs to.";
  }

  if (form.delta_E === "") {
    errors.delta_E = "DeltaE is required — it comes from the strip photo.";
  } else {
    const dE = toNum(form.delta_E);
    if (dE === undefined) errors.delta_E = "Enter a valid number.";
    else if (dE < 0) errors.delta_E = "DeltaE cannot be negative.";
  }

  if (form.dose_ppm_hr === "") {
    errors.dose_ppm_hr = "Cumulative dose is required.";
  } else {
    const dose = toNum(form.dose_ppm_hr);
    if (dose === undefined) errors.dose_ppm_hr = "Enter a valid number.";
    else if (dose < 0) errors.dose_ppm_hr = "Dose cannot be negative.";
  }

  if (form.delta_E_corr !== "") {
    const dEc = toNum(form.delta_E_corr);
    if (dEc === undefined || dEc < 0) {
      errors.delta_E_corr = "Must be a number of 0 or more, or left blank.";
    }
  }

  for (const ch of ["R", "G", "B"]) {
    if (form[ch] === "") continue;
    const v = toNum(form[ch]);
    if (v === undefined || v < 0 || v > 255) errors[ch] = "Must be between 0 and 255.";
  }

  for (const ch of ["L_star", "a_star", "b_star"]) {
    if (form[ch] === "") continue;
    if (toNum(form[ch]) === undefined) errors[ch] = "Enter a valid number.";
  }

  if (form.temperature_c !== "") {
    const t = toNum(form.temperature_c);
    if (t === undefined || t < -50 || t > 100) {
      errors.temperature_c = "Expected -50 to 100 degrees Celsius.";
    }
  }

  if (form.humidity_pct !== "") {
    const h = toNum(form.humidity_pct);
    if (h === undefined || h < 0 || h > 100) errors.humidity_pct = "Expected 0 to 100 percent.";
  }

  if (form.shift_date !== "" && !/^\d{4}-\d{2}-\d{2}$/.test(form.shift_date)) {
    errors.shift_date = "Use the YYYY-MM-DD format.";
  }

  return errors;
}

/** Build the POST /readings/ body, omitting optional fields left blank. */
function buildPayload(form, officerUsername) {
  const payload = {
    worker_id: form.worker_id,
    delta_E: toNum(form.delta_E),
    dose_ppm_hr: toNum(form.dose_ppm_hr),
    model_confidence: form.model_confidence,
    scanned_by: officerUsername || "dashboard",
  };

  const numericFields = [
    "delta_E_corr", "R", "G", "B",
    "L_star", "a_star", "b_star",
    "temperature_c", "humidity_pct",
  ];
  for (const key of numericFields) {
    const v = toNum(form[key]);
    if (v !== undefined) payload[key] = v;
  }

  const badge = form.badge_id.trim();
  if (badge) payload.badge_id = badge;

  if (form.shift_date) payload.shift_date = form.shift_date;

  const notes = form.notes.trim();
  if (notes) payload.notes = notes;

  return payload;
}

export default function SubmitReading({ user }) {
  const [workers, setWorkers] = useState([]);
  const [workersLoading, setWorkersLoading] = useState(true);
  const [workersError, setWorkersError] = useState("");

  const [form, setForm] = useState(EMPTY_FORM);
  const [activePreset, setActivePreset] = useState(null);
  const [errors, setErrors] = useState({});
  const [showErrors, setShowErrors] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await api.listWorkers();
        if (!cancelled) setWorkers(Array.isArray(data) ? data : []);
      } catch (e) {
        if (!cancelled) setWorkersError(e.message || "Could not load the worker roster.");
      } finally {
        if (!cancelled) setWorkersLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const selectedWorker = useMemo(
    () => workers.find((w) => w.worker_id === form.worker_id) || null,
    [workers, form.worker_id],
  );

  function setField(name, value) {
    setForm((f) => ({ ...f, [name]: value }));
    setActivePreset(null);
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: undefined }));
  }

  function applyPreset(preset) {
    setForm((f) => ({ ...f, ...preset.values }));
    setActivePreset(preset.key);
    setErrors({});
    setShowErrors(false);
    setSubmitError("");
  }

  function clearForm() {
    // Keep the selected worker — an officer usually re-scans the same badge.
    setForm((f) => ({ ...EMPTY_FORM, worker_id: f.worker_id }));
    setActivePreset(null);
    setErrors({});
    setShowErrors(false);
    setSubmitError("");
  }

  function startNewReading() {
    setResult(null);
    clearForm();
  }

  async function handleSubmit(e) {
    e.preventDefault();

    const found = validate(form);
    setErrors(found);
    setShowErrors(true);
    if (Object.keys(found).length > 0) return;

    setSubmitting(true);
    setSubmitError("");
    setResult(null);

    try {
      const reading = await api.submitReading(buildPayload(form, user?.username));

      // The backend decides whether a threshold was breached. When it reports an
      // alert, fetch the alert row it created so the UI can show the real alert
      // type / threshold / message rather than recomputing anything locally.
      let alert = null;
      let alertLookupFailed = false;
      if (reading?.alert_triggered) {
        try {
          const workerAlerts = await api.getWorkerAlerts(form.worker_id);
          alert = (Array.isArray(workerAlerts) ? workerAlerts : [])
            .find((a) => a.reading_id === reading.id) || null;
          if (!alert) alertLookupFailed = true;
        } catch {
          alertLookupFailed = true;
        }
      }

      setResult({ reading, alert, alertLookupFailed });
      setShowErrors(false);
    } catch (err) {
      setSubmitError(err.message || "Submission failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const fieldError = (name) => (showErrors ? errors[name] : undefined);

  function field(name, label, opts = {}) {
    const {
      type = "number", step = "any", hint, required = false,
      placeholder, min, max,
    } = opts;
    const err = fieldError(name);
    const errId = `${name}-error`;
    const hintId = `${name}-hint`;
    const describedBy = [err ? errId : null, hint ? hintId : null]
      .filter(Boolean).join(" ") || undefined;

    return (
      <div className="form-group" key={name}>
        <label htmlFor={name}>
          {label}{required && <span className="req" aria-hidden="true"> *</span>}
        </label>
        <input
          id={name}
          name={name}
          type={type}
          step={type === "number" ? step : undefined}
          min={type === "number" ? min : undefined}
          max={type === "number" ? max : undefined}
          inputMode={type === "number" ? "decimal" : undefined}
          value={form[name]}
          placeholder={placeholder}
          onChange={(e) => setField(name, e.target.value)}
          required={required}
          aria-invalid={err ? "true" : undefined}
          aria-describedby={describedBy}
          disabled={submitting}
        />
        {hint && <p className="form-hint" id={hintId}>{hint}</p>}
        {err && <p className="form-error" id={errId}>{err}</p>}
      </div>
    );
  }

  // ── Result view ─────────────────────────────────────────────────────────
  if (result) {
    const { reading, alert, alertLookupFailed } = result;
    const triggered = Boolean(reading.alert_triggered);
    // Tone comes from the backend's alert record, not a local threshold check.
    const tone = triggered ? (alert?.alert_type || "danger") : "safe";
    const workerLabel = selectedWorker
      ? `${selectedWorker.worker_id} ${DASH} ${selectedWorker.full_name}`
      : form.worker_id;
    const alertTypeLabel = (alert?.alert_type || "threshold breach").toUpperCase();

    return (
      <>
        <div className="page-header">
          <div>
            <h2>Reading Submitted</h2>
            <p className="subtitle">
              Stored by the backend, which also ran the DGMS threshold evaluation
            </p>
          </div>
          <button className="btn btn-primary" onClick={startNewReading}>
            + Submit Another Reading
          </button>
        </div>

        <div className={`result-banner ${tone}`} role="status" aria-live="polite">
          <span className="result-banner-icon" aria-hidden="true">
            {triggered ? "!" : "\u2713"}
          </span>
          <div className="result-banner-body">
            <h3>
              {triggered
                ? `Alert generated by backend ${DASH} ${alertTypeLabel}`
                : "No DGMS threshold breached"}
            </h3>
            <p>
              {triggered
                ? (alert?.message || "The backend recorded a threshold breach for this reading.")
                : `Reading recorded for ${workerLabel}. Cumulative dose stayed below the 60 ppm.hr warning threshold.`}
            </p>
            {triggered && alert?.threshold != null && (
              <p className="result-banner-meta">
                {`Threshold crossed: ${alert.threshold} ppm.hr`}
                {alert.dose_at_alert != null && ` \u00b7 dose at alert: ${alert.dose_at_alert} ppm.hr`}
                {` \u00b7 ${alert.is_acknowledged ? "acknowledged" : "awaiting acknowledgement"}`}
              </p>
            )}
            {triggered && alertLookupFailed && (
              <p className="result-banner-meta">
                The backend reported <code>alert_triggered: true</code>. Full alert
                details are on the Alerts page.
              </p>
            )}
          </div>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-label">Cumulative Dose</div>
            <div className="stat-value">{reading.dose_ppm_hr?.toFixed(1)}</div>
            <div className="stat-sub">ppm.hr (stored)</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Colour Shift DeltaE</div>
            <div className="stat-value">{reading.delta_E?.toFixed(2)}</div>
            <div className="stat-sub">
              {reading.delta_E_corr != null
                ? `corrected ${reading.delta_E_corr.toFixed(2)}`
                : "CIE DE2000"}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Reading ID</div>
            <div className="stat-value">#{reading.id}</div>
            <div className="stat-sub">{reading.shift_date || DASH}</div>
          </div>
          <div className={`stat-card ${tone}`}>
            <div className="stat-label">Alert Triggered</div>
            <div className="stat-value" style={{ fontSize: 24 }}>
              {triggered ? "Yes" : "No"}
            </div>
            <div className="stat-sub">decided by backend</div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-card-header">
            <h3>Stored Record</h3>
            <span className="muted-note">as returned by POST /readings/</span>
          </div>
          <table className="record-table">
            <tbody>
              <tr><th scope="row">Worker</th><td>{workerLabel}</td></tr>
              <tr><th scope="row">Badge</th><td>{reading.badge_id || DASH}</td></tr>
              <tr>
                <th scope="row">Scan timestamp</th>
                <td>{reading.scan_timestamp ? new Date(reading.scan_timestamp).toLocaleString() : DASH}</td>
              </tr>
              <tr><th scope="row">Shift date</th><td>{reading.shift_date || DASH}</td></tr>
              <tr><th scope="row">Model confidence</th><td>{reading.model_confidence || DASH}</td></tr>
              <tr>
                <th scope="row">Temperature</th>
                <td>{reading.temperature_c != null ? `${reading.temperature_c} \u00b0C` : DASH}</td>
              </tr>
              <tr>
                <th scope="row">Humidity</th>
                <td>{reading.humidity_pct != null ? `${reading.humidity_pct} %` : DASH}</td>
              </tr>
              <tr><th scope="row">Scanned by</th><td>{reading.scanned_by || DASH}</td></tr>
              <tr><th scope="row">Notes</th><td>{reading.notes || DASH}</td></tr>
            </tbody>
          </table>
        </div>

        <div className="form-actions">
          <button className="btn btn-primary" onClick={startNewReading}>
            + Submit Another Reading
          </button>
          <a className="btn btn-outline" href="#/alerts">View Alerts</a>
          <a className="btn btn-outline" href="#/reports">Open Reports</a>
          <a className="btn btn-outline" href="#/dashboard">Back to Dashboard</a>
        </div>
      </>
    );
  }

  // ── Form view ───────────────────────────────────────────────────────────
  const workerError = fieldError("worker_id");
  const errorCount = Object.keys(errors).filter((k) => errors[k]).length;
  const activePresetInfo = PRESETS.find((p) => p.key === activePreset);

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Submit Reading</h2>
          <p className="subtitle">
            Log a wristband strip scan {DASH} the backend evaluates DGMS thresholds and raises alerts
          </p>
        </div>
      </div>

      <div className="table-card">
        <div className="table-card-header">
          <h3>Demo Presets</h3>
          <span className="muted-note">fills the form only {DASH} the API decides the outcome</span>
        </div>
        <div className="form-section">
          <p className="form-hint" style={{ marginTop: 0, marginBottom: 14 }}>
            Each preset pre-fills realistic colorimetric values taken from the Phase 1
            {" "}<code>simulate_strip_color()</code> model at that dose. Nothing is faked:
            these values are sent to <code>POST /readings/</code>, and the dose band,
            alert type and alert message all come back from the backend.
          </p>
          <div className="preset-bar">
            {PRESETS.map((p) => (
              <button
                key={p.key}
                type="button"
                className={`preset-btn ${p.tone} ${activePreset === p.key ? "active" : ""}`}
                onClick={() => applyPreset(p)}
                disabled={submitting}
                title={p.hint}
                aria-pressed={activePreset === p.key}
              >
                <span className="preset-btn-label">{p.label}</span>
                <span className="preset-btn-dose">{p.values.dose_ppm_hr} ppm.hr</span>
              </button>
            ))}
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={clearForm}
              disabled={submitting}
            >
              Clear
            </button>
          </div>
          {activePresetInfo && (
            <p className="form-hint" style={{ marginTop: 12, marginBottom: 0 }}>
              Loaded the <strong>{activePresetInfo.label}</strong> preset: {activePresetInfo.hint}.
              {" "}Edit any field before submitting.
            </p>
          )}
        </div>
      </div>

      <form onSubmit={handleSubmit} noValidate>
        <div className="table-card">
          <div className="table-card-header">
            <h3>Worker &amp; Scan Context</h3>
          </div>
          <div className="form-section">
            <div className="form-grid">
              <div className="form-group">
                <label htmlFor="worker_id">
                  Worker<span className="req" aria-hidden="true"> *</span>
                </label>
                <select
                  id="worker_id"
                  name="worker_id"
                  value={form.worker_id}
                  onChange={(e) => setField("worker_id", e.target.value)}
                  disabled={submitting || workersLoading}
                  aria-invalid={workerError ? "true" : undefined}
                  aria-describedby={
                    [workerError ? "worker_id-error" : null, "worker_id-hint"]
                      .filter(Boolean).join(" ")
                  }
                  required
                >
                  <option value="">
                    {workersLoading ? "Loading roster..." : "Select a worker"}
                  </option>
                  {workers.map((w) => (
                    <option key={w.worker_id} value={w.worker_id}>
                      {`${w.worker_id} ${DASH} ${w.full_name}${w.site ? ` (${w.site})` : ""}`}
                    </option>
                  ))}
                </select>
                <p className="form-hint" id="worker_id-hint">
                  Active workers from the roster. Add people on the Workers page.
                </p>
                {workerError && <p className="form-error" id="worker_id-error">{workerError}</p>}
                {workersError && <p className="form-error">{workersError}</p>}
                {!workersLoading && !workersError && workers.length === 0 && (
                  <p className="form-error">
                    No active workers found. Register one on the Workers page first.
                  </p>
                )}
              </div>

              {field("badge_id", "Badge Serial", {
                type: "text",
                placeholder: selectedWorker ? `BADGE-${selectedWorker.worker_id}` : "BADGE-WRK001",
                hint: "Physical wristband serial number. Optional.",
              })}

              {field("shift_date", "Shift Date", {
                type: "date",
                hint: "Groups the reading into a shift. Defaults to today; the backend uses today if cleared.",
              })}

              <div className="form-group">
                <label htmlFor="model_confidence">Model Confidence</label>
                <select
                  id="model_confidence"
                  name="model_confidence"
                  value={form.model_confidence}
                  onChange={(e) => setField("model_confidence", e.target.value)}
                  disabled={submitting}
                  aria-describedby="model_confidence-hint"
                >
                  <option value="high">high</option>
                  <option value="medium">medium</option>
                  <option value="low">low</option>
                </select>
                <p className="form-hint" id="model_confidence-hint">
                  Reported by the ML model. The current trained model (test R2 0.863)
                  reports <strong>medium</strong>.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-card-header">
            <h3>Colorimetric Measurement</h3>
            <span className="muted-note">extracted from the strip photo</span>
          </div>
          <div className="form-section">
            <div className="form-grid">
              {field("delta_E", "DeltaE (CIE DE2000)", {
                required: true, min: "0", step: "0.001", placeholder: "17.303",
                hint: "Perceptual colour difference between the strip and a fresh baseline strip.",
              })}
              {field("delta_E_corr", "DeltaE (lighting-corrected)", {
                min: "0", step: "0.001", placeholder: "17.303",
                hint: "After reference-card correction. Equals DeltaE when no card is used.",
              })}
              {field("R", "Mean R", {
                min: "0", max: "255", step: "0.1", placeholder: "108.3",
                hint: "Strip ROI mean red, 0-255.",
              })}
              {field("G", "Mean G", {
                min: "0", max: "255", step: "0.1", placeholder: "142.3",
                hint: "Strip ROI mean green, 0-255.",
              })}
              {field("B", "Mean B", {
                min: "0", max: "255", step: "0.1", placeholder: "122.3",
                hint: "Strip ROI mean blue, 0-255.",
              })}
              {field("L_star", "CIE L*", {
                step: "0.01", placeholder: "56.14",
                hint: "Lightness. Lower means a darker, more exposed strip.",
              })}
              {field("a_star", "CIE a*", {
                step: "0.01", placeholder: "-16.20",
                hint: "Green-to-red axis.",
              })}
              {field("b_star", "CIE b*", {
                step: "0.01", placeholder: "6.81",
                hint: "Blue-to-yellow axis.",
              })}
            </div>
          </div>
        </div>

        <div className="table-card">
          <div className="table-card-header">
            <h3>Dose &amp; Environment</h3>
            <span className="muted-note">ML model output</span>
          </div>
          <div className="form-section">
            <div className="form-grid">
              {field("dose_ppm_hr", "Cumulative Dose (ppm.hr)", {
                required: true, min: "0", step: "0.01", placeholder: "35.0",
                hint: "Predicted by the ML regression model. The backend compares this against the DGMS thresholds (60 warning / 80 danger / 100 critical) and raises any alert.",
              })}
              {field("temperature_c", "Temperature (deg C)", {
                step: "0.1", placeholder: "26.0",
                hint: "Ambient temperature at scan time. Optional.",
              })}
              {field("humidity_pct", "Relative Humidity (%)", {
                min: "0", max: "100", step: "0.1", placeholder: "50.0",
                hint: "Ambient humidity at scan time. Optional.",
              })}
              {field("notes", "Notes", {
                type: "text", placeholder: "Observations for the compliance record",
                hint: "Free text stored with the reading. Optional.",
              })}
            </div>
            <p className="form-hint" style={{ marginBottom: 0 }}>
              Recorded as scanned by <strong>{user?.username || "dashboard"}</strong>.
            </p>
          </div>

          <div className="form-actions">
            <button
              type="submit"
              className="btn btn-primary btn-lg"
              disabled={submitting || workersLoading || workers.length === 0}
            >
              {submitting && <span className="inline-spinner" aria-hidden="true" />}
              {submitting ? "Submitting..." : "Submit Reading"}
            </button>
            <span className="form-hint" style={{ margin: 0 }}>
              Sends one <code>POST /readings/</code> request.
            </span>
          </div>

          {showErrors && errorCount > 0 && (
            <div className="form-section" style={{ paddingTop: 0 }}>
              <p className="form-error" role="alert">
                {`Please correct the highlighted ${errorCount === 1 ? "field" : "fields"} and submit again.`}
              </p>
            </div>
          )}

          {submitError && (
            <div className="form-section" style={{ paddingTop: 0 }}>
              <div className="result-banner danger compact" role="alert">
                <span className="result-banner-icon" aria-hidden="true">!</span>
                <div className="result-banner-body">
                  <h3>Submission failed</h3>
                  <p>{submitError}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </form>
    </>
  );
}
