import { useMemo } from "react";
import { GAUGE_MAX, THRESHOLDS, UNIT, classifyDose, statusMeta } from "../lib/dose";

/**
 * HistoryChart — cumulative-dose trend for one worker.
 *
 * Data comes from the existing `GET /readings/worker/{code}`. Drawn as a plain
 * SVG line/area chart: it is ~80 lines, scales cleanly on a phone and avoids
 * pulling Chart.js into the mobile bundle (the dashboard already owns that).
 */

const VB_W = 320;
const VB_H = 170;
const PAD = { top: 12, right: 10, bottom: 26, left: 34 };

export default function HistoryChart({ readings }) {
  const points = useMemo(() => {
    const rows = (readings || [])
      .filter((r) => Number.isFinite(Number(r?.dose_ppm_hr)))
      .slice()
      .sort(
        (a, b) =>
          new Date(a.scan_timestamp || 0).getTime() -
          new Date(b.scan_timestamp || 0).getTime(),
      );
    return rows;
  }, [readings]);

  if (points.length === 0) {
    return (
      <p className="empty-note">
        No previous readings for this worker yet. This scan is the first one.
      </p>
    );
  }

  const maxDose = Math.max(GAUGE_MAX, ...points.map((r) => Number(r.dose_ppm_hr)));
  const innerW = VB_W - PAD.left - PAD.right;
  const innerH = VB_H - PAD.top - PAD.bottom;

  const x = (i) =>
    PAD.left + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (d) => PAD.top + innerH - (Number(d) / maxDose) * innerH;

  const line = points.map((r, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(2)} ${y(r.dose_ppm_hr).toFixed(2)}`).join(" ");
  const area =
    `${line} L ${x(points.length - 1).toFixed(2)} ${(PAD.top + innerH).toFixed(2)}` +
    ` L ${x(0).toFixed(2)} ${(PAD.top + innerH).toFixed(2)} Z`;

  const yTicks = [0, THRESHOLDS.warning, THRESHOLDS.danger, THRESHOLDS.critical].filter(
    (v) => v <= maxDose,
  );

  const fmtDate = (ts) => {
    const d = new Date(ts);
    return Number.isNaN(d.getTime())
      ? ""
      : d.toLocaleDateString(undefined, { day: "2-digit", month: "short" });
  };

  const latest = points[points.length - 1];

  return (
    <div className="chart-wrap">
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        className="chart-svg"
        role="img"
        aria-label={`Dose history: ${points.length} readings, latest ${Number(
          latest.dose_ppm_hr,
        ).toFixed(1)} ${UNIT}`}
      >
        <defs>
          <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6366f1" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Grid + y labels */}
        {yTicks.map((v) => (
          <g key={v}>
            <line
              x1={PAD.left}
              y1={y(v)}
              x2={VB_W - PAD.right}
              y2={y(v)}
              stroke={v === 0 ? "var(--border)" : statusMeta(classifyDose(v)).color}
              strokeWidth="1"
              strokeDasharray={v === 0 ? "0" : "3 3"}
              opacity={v === 0 ? 1 : 0.5}
            />
            <text x={PAD.left - 6} y={y(v)} textAnchor="end" dominantBaseline="middle" className="chart-label">
              {v}
            </text>
          </g>
        ))}

        <path d={area} fill="url(#areaFill)" />
        <path d={line} fill="none" stroke="#818cf8" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {points.map((r, i) => (
          <circle
            key={r.id ?? i}
            cx={x(i)}
            cy={y(r.dose_ppm_hr)}
            r={i === points.length - 1 ? 4 : 2.6}
            fill={statusMeta(classifyDose(r.dose_ppm_hr)).color}
            stroke="var(--bg-card)"
            strokeWidth="1.2"
          />
        ))}

        {/* First / last x labels only — a phone has no room for more */}
        <text x={PAD.left} y={VB_H - 8} textAnchor="start" className="chart-label">
          {fmtDate(points[0].scan_timestamp)}
        </text>
        {points.length > 1 && (
          <text x={VB_W - PAD.right} y={VB_H - 8} textAnchor="end" className="chart-label">
            {fmtDate(latest.scan_timestamp)}
          </text>
        )}
      </svg>
      <p className="chart-note">
        {`Last ${points.length} reading${points.length === 1 ? "" : "s"} \u00B7 ${UNIT} \u00B7 dashed lines are the DGMS warning / danger / critical thresholds`}
      </p>
    </div>
  );
}
