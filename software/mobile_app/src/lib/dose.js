/**
 * dose.js — DGMS exposure bands and gauge geometry.
 *
 * The thresholds mirror the backend constants in
 * `software/backend/routes/readings.py` (WARNING 60 / DANGER 80 / CRITICAL 100
 * ppm·hr). The backend remains the source of truth for alerting: the app shows
 * `exposure_status` returned by POST /readings/scan and only falls back to
 * these bands when classifying a historical reading locally.
 *
 * Pure functions only — unit-tested in `test/dose.test.js` with no DOM.
 */

export const UNIT = "ppm\u00B7hr"; // ppm·hr (cumulative dose)

export const THRESHOLDS = {
  warning: 60,
  danger: 80,
  critical: 100,
};

/** Full-scale end of the gauge. 20% headroom above the critical threshold. */
export const GAUGE_MAX = 120;

/** Tick values drawn on the gauge scale — includes every band boundary. */
export const GAUGE_TICKS = [0, 20, 40, 60, 80, 100, 120];

export const STATUS_META = {
  safe: {
    label: "SAFE",
    color: "#22c55e",
    tone: "safe",
    headline: "Exposure within safe limits",
    advice: "Continue the shift. Re-scan the wristband at the next checkpoint.",
  },
  warning: {
    label: "WARNING",
    color: "#f59e0b",
    tone: "warning",
    headline: "Approaching the DGMS 8-hr limit",
    advice: "Limit further H\u2082S exposure and inform the shift supervisor.",
  },
  danger: {
    label: "DANGER",
    color: "#ef4444",
    tone: "danger",
    headline: "DGMS 8-hr TWA limit reached",
    advice: "Remove the worker from the exposure zone and log the incident.",
  },
  critical: {
    label: "CRITICAL",
    color: "#dc2626",
    tone: "critical",
    headline: "Critical over-exposure",
    advice: "IMMEDIATE EVACUATION. Medical assessment required.",
  },
};

/**
 * Classify a cumulative dose using the same bands as the backend.
 * @param {number} dose ppm·hr
 * @returns {"safe"|"warning"|"danger"|"critical"}
 */
export function classifyDose(dose) {
  const d = Number(dose);
  if (!Number.isFinite(d)) return "safe";
  if (d >= THRESHOLDS.critical) return "critical";
  if (d >= THRESHOLDS.danger) return "danger";
  if (d >= THRESHOLDS.warning) return "warning";
  return "safe";
}

/** Normalise a backend `exposure_status` string, falling back to the dose. */
export function resolveStatus(exposureStatus, dose) {
  const s = String(exposureStatus || "").toLowerCase();
  if (s in STATUS_META) return s;
  return classifyDose(dose);
}

export function statusMeta(status) {
  return STATUS_META[status] || STATUS_META.safe;
}

/** Percentage of the DGMS 8-hr limit (danger threshold = 100%). */
export function percentOfLimit(dose) {
  const d = Number(dose);
  if (!Number.isFinite(d)) return 0;
  return Math.round((d / THRESHOLDS.danger) * 1000) / 10;
}

/** Clamp a value into [min, max]. */
export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

// ── Gauge geometry ──────────────────────────────────────────────────────────
//
// The gauge is a 180° arc drawn in SVG user units. Every visual element —
// arc path, needle and each scale label — is derived from the SAME
// `valueToAngle` + `polar` pair, which is what keeps the labels locked to
// their tick marks at any viewport size (the previous implementation placed
// labels with independent percentage offsets, so they drifted out of
// alignment with the arc).

/** Sweep start (left end of the arc) and end (right end), in degrees. */
export const ARC_START_DEG = 180;
export const ARC_END_DEG = 0;

/**
 * Map a dose to its angle on the arc.
 * 0 → 180° (far left), GAUGE_MAX → 0° (far right). Out-of-range values clamp.
 * @param {number} value ppm·hr
 * @param {number} [max=GAUGE_MAX]
 * @returns {number} degrees
 */
export function valueToAngle(value, max = GAUGE_MAX) {
  const v = Number.isFinite(Number(value)) ? Number(value) : 0;
  const t = clamp(v / max, 0, 1);
  return ARC_START_DEG - t * (ARC_START_DEG - ARC_END_DEG);
}

/**
 * Polar → cartesian for the gauge's coordinate system (SVG y grows downward).
 * @returns {{x:number,y:number}}
 */
export function polar(cx, cy, radius, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  return {
    x: cx + radius * Math.cos(rad),
    y: cy - radius * Math.sin(rad),
  };
}

/**
 * SVG arc path between two dose values along the gauge.
 * @returns {string} `d` attribute
 */
export function arcPath(cx, cy, radius, fromValue, toValue, max = GAUGE_MAX) {
  const a0 = valueToAngle(fromValue, max);
  const a1 = valueToAngle(toValue, max);
  const p0 = polar(cx, cy, radius, a0);
  const p1 = polar(cx, cy, radius, a1);
  const largeArc = Math.abs(a1 - a0) > 180 ? 1 : 0;
  // Angle decreases as value increases, so the sweep is clockwise (1).
  return `M ${p0.x.toFixed(3)} ${p0.y.toFixed(3)} A ${radius} ${radius} 0 ${largeArc} 1 ${p1.x.toFixed(3)} ${p1.y.toFixed(3)}`;
}

/**
 * Text anchor that keeps a scale label from overlapping the arc it labels.
 * Left half → anchor at the end, apex → middle, right half → start.
 */
export function labelAnchor(angleDeg) {
  if (angleDeg > 100) return "end";
  if (angleDeg < 80) return "start";
  return "middle";
}

/**
 * Build the fully-resolved scale ticks for a gauge of the given geometry.
 * Each entry carries the tick line endpoints AND the label position/anchor,
 * all from the same angle — so a label can never drift off its tick.
 *
 * @returns {Array<{value:number,angle:number,x1:number,y1:number,x2:number,y2:number,labelX:number,labelY:number,anchor:string,isBand:boolean}>}
 */
export function buildScale({
  cx,
  cy,
  radius,
  tickLength = 8,
  labelOffset = 20,
  ticks = GAUGE_TICKS,
  max = GAUGE_MAX,
}) {
  const bandValues = new Set([
    THRESHOLDS.warning,
    THRESHOLDS.danger,
    THRESHOLDS.critical,
  ]);

  return ticks.map((value) => {
    const angle = valueToAngle(value, max);
    const outer = polar(cx, cy, radius, angle);
    const inner = polar(cx, cy, radius - tickLength, angle);
    const label = polar(cx, cy, radius + labelOffset, angle);
    return {
      value,
      angle,
      x1: inner.x,
      y1: inner.y,
      x2: outer.x,
      y2: outer.y,
      labelX: label.x,
      labelY: label.y,
      anchor: labelAnchor(angle),
      isBand: bandValues.has(value),
    };
  });
}

/**
 * Coloured band segments of the arc, in dose order.
 * @returns {Array<{status:string,from:number,to:number,color:string}>}
 */
export function gaugeBands(max = GAUGE_MAX) {
  return [
    { status: "safe", from: 0, to: THRESHOLDS.warning, color: STATUS_META.safe.color },
    {
      status: "warning",
      from: THRESHOLDS.warning,
      to: THRESHOLDS.danger,
      color: STATUS_META.warning.color,
    },
    {
      status: "danger",
      from: THRESHOLDS.danger,
      to: THRESHOLDS.critical,
      color: STATUS_META.danger.color,
    },
    {
      status: "critical",
      from: THRESHOLDS.critical,
      to: max,
      color: STATUS_META.critical.color,
    },
  ];
}

/** Format a dose for display (1 decimal, never "NaN"). */
export function formatDose(dose) {
  const d = Number(dose);
  return Number.isFinite(d) ? d.toFixed(1) : "--";
}
