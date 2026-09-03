import { useEffect, useMemo, useRef, useState } from "react";
import {
  GAUGE_MAX,
  UNIT,
  arcPath,
  buildScale,
  clamp,
  formatDose,
  gaugeBands,
  percentOfLimit,
  polar,
  statusMeta,
  valueToAngle,
} from "../lib/dose";

/**
 * DoseGauge — 180° cumulative-dose gauge.
 *
 * Alignment fix: the arc, the tick marks, the needle AND every scale label are
 * all positioned from the single `valueToAngle`/`polar` pair in `lib/dose.js`
 * inside one fixed 240×150 SVG viewBox. The SVG scales as a unit, so a label
 * stays welded to its tick at every screen width — the earlier version placed
 * labels with separate CSS percentage offsets, which is what made them drift.
 */

// Fixed geometry in viewBox units. VB_H leaves room under the arc for the
// numeric readout, and the 20-unit side padding fits the "0"/"120" labels.
const VB_W = 240;
const VB_H = 150;
const CX = VB_W / 2;
const CY = 112;
const R = 88;
const TRACK_WIDTH = 14;

export default function DoseGauge({
  dose,
  status,
  max = GAUGE_MAX,
  animate = true,
  label = "Cumulative dose",
}) {
  const meta = statusMeta(status);
  const target = Number.isFinite(Number(dose)) ? Number(dose) : 0;

  // Needle sweep-in animation (respects reduced-motion; skipped in tests/SSR).
  const [shown, setShown] = useState(animate ? 0 : target);
  const raf = useRef(0);

  useEffect(() => {
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!animate || reduce) {
      setShown(target);
      return undefined;
    }
    const from = 0;
    const duration = 750;
    const t0 = performance.now();
    const step = (now) => {
      const t = clamp((now - t0) / duration, 0, 1);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      setShown(from + (target - from) * eased);
      if (t < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [target, animate]);

  const bands = useMemo(() => gaugeBands(max), [max]);
  const scale = useMemo(
    () =>
      buildScale({
        cx: CX,
        cy: CY,
        radius: R,
        tickLength: TRACK_WIDTH / 2 + 3,
        labelOffset: 15,
        max,
      }),
    [max],
  );

  const needleAngle = valueToAngle(shown, max);
  const needleTip = polar(CX, CY, R - TRACK_WIDTH - 4, needleAngle);
  const needleTail = polar(CX, CY, 12, needleAngle + 180);
  const overRange = target > max;

  return (
    <figure className="gauge" style={{ "--gauge-color": meta.color }}>
      <svg
        className="gauge-svg"
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        role="img"
        aria-label={`${label}: ${formatDose(target)} ${UNIT}, status ${meta.label}`}
      >
        {/* Track */}
        <path
          d={arcPath(CX, CY, R, 0, max, max)}
          fill="none"
          stroke="var(--border)"
          strokeWidth={TRACK_WIDTH}
          strokeLinecap="round"
        />

        {/* Coloured DGMS bands */}
        {bands.map((b) => (
          <path
            key={b.status}
            d={arcPath(CX, CY, R, b.from, b.to, max)}
            fill="none"
            stroke={b.color}
            strokeWidth={TRACK_WIDTH}
            strokeLinecap="butt"
            opacity="0.92"
          />
        ))}

        {/* Scale: tick + label share one angle → always aligned */}
        <g className="gauge-scale">
          {scale.map((t) => (
            <g key={t.value}>
              <line
                x1={t.x1}
                y1={t.y1}
                x2={t.x2}
                y2={t.y2}
                stroke={t.isBand ? "var(--text-primary)" : "var(--text-muted)"}
                strokeWidth={t.isBand ? 1.6 : 1}
                strokeLinecap="round"
              />
              <text
                x={t.labelX}
                y={t.labelY}
                textAnchor={t.anchor}
                dominantBaseline="middle"
                className={`gauge-tick-label${t.isBand ? " is-band" : ""}`}
              >
                {t.value}
              </text>
            </g>
          ))}
        </g>

        {/* Needle */}
        <g className="gauge-needle">
          <line
            x1={needleTail.x}
            y1={needleTail.y}
            x2={needleTip.x}
            y2={needleTip.y}
            stroke="var(--text-primary)"
            strokeWidth="3.2"
            strokeLinecap="round"
          />
          <circle cx={CX} cy={CY} r="7" fill="var(--bg-card)" stroke={meta.color} strokeWidth="2.5" />
        </g>

        {/* Readout inside the dial */}
        <text x={CX} y={CY - 34} textAnchor="middle" className="gauge-value">
          {formatDose(target)}
        </text>
        <text x={CX} y={CY - 16} textAnchor="middle" className="gauge-unit">
          {UNIT}
        </text>
      </svg>

      <figcaption className="gauge-caption">
        <span className={`badge badge-${meta.tone}`}>{meta.label}</span>
        <span className="gauge-caption-meta">
          {percentOfLimit(target)}% of the DGMS 8-hr limit
          {overRange ? " \u00B7 above full scale" : ""}
        </span>
      </figcaption>
    </figure>
  );
}
