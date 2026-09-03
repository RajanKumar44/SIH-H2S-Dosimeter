/**
 * Unit tests for lib/dose.js — the gauge geometry and DGMS banding.
 *
 * Run with:  npm test        (node --test, no extra dependencies)
 *
 * These exist because the gauge is the one piece of the demo where a silent
 * geometry regression looks plausible on screen: the previous implementation
 * placed scale labels independently of the arc, so they drifted out of
 * alignment. The invariants below pin label position to tick position.
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  ARC_END_DEG,
  ARC_START_DEG,
  GAUGE_MAX,
  GAUGE_TICKS,
  THRESHOLDS,
  arcPath,
  buildScale,
  classifyDose,
  clamp,
  formatDose,
  gaugeBands,
  labelAnchor,
  percentOfLimit,
  polar,
  resolveStatus,
  statusMeta,
  valueToAngle,
} from "../src/lib/dose.js";

const CX = 120;
const CY = 112;
const R = 88;

test("thresholds mirror the backend constants", () => {
  assert.equal(THRESHOLDS.warning, 60);
  assert.equal(THRESHOLDS.danger, 80);
  assert.equal(THRESHOLDS.critical, 100);
});

test("classifyDose respects every band boundary", () => {
  assert.equal(classifyDose(0), "safe");
  assert.equal(classifyDose(59.9), "safe");
  assert.equal(classifyDose(60), "warning");
  assert.equal(classifyDose(79.9), "warning");
  assert.equal(classifyDose(80), "danger");
  assert.equal(classifyDose(99.9), "danger");
  assert.equal(classifyDose(100), "critical");
  assert.equal(classifyDose(250), "critical");
});

test("classifyDose is defensive about bad input", () => {
  assert.equal(classifyDose(undefined), "safe");
  assert.equal(classifyDose(null), "safe");
  assert.equal(classifyDose(Number.NaN), "safe");
  assert.equal(classifyDose("abc"), "safe");
});

test("resolveStatus trusts the backend status, else falls back to the dose", () => {
  assert.equal(resolveStatus("critical", 5), "critical");
  assert.equal(resolveStatus("SAFE", 95), "safe");
  assert.equal(resolveStatus(undefined, 95), "danger");
  assert.equal(resolveStatus("bogus", 61), "warning");
});

test("every status has display metadata with a colour", () => {
  for (const s of ["safe", "warning", "danger", "critical"]) {
    const m = statusMeta(s);
    assert.match(m.color, /^#[0-9a-f]{6}$/i, `${s} needs a hex colour`);
    assert.ok(m.label.length > 0);
    assert.ok(m.headline.length > 0);
    assert.ok(m.advice.length > 0);
  }
});

test("percentOfLimit is relative to the DGMS 8-hr limit", () => {
  assert.equal(percentOfLimit(80), 100);
  assert.equal(percentOfLimit(40), 50);
  assert.equal(percentOfLimit(0), 0);
  assert.equal(percentOfLimit("nope"), 0);
});

test("clamp bounds the value", () => {
  assert.equal(clamp(-1, 0, 1), 0);
  assert.equal(clamp(2, 0, 1), 1);
  assert.equal(clamp(0.5, 0, 1), 0.5);
});

test("formatDose never renders NaN", () => {
  assert.equal(formatDose(101.2612), "101.3");
  assert.equal(formatDose(0), "0.0");
  assert.equal(formatDose(undefined), "--");
});

// ── Gauge geometry ─────────────────────────────────────────────────────────

test("valueToAngle sweeps 180deg -> 0deg across the scale", () => {
  assert.equal(valueToAngle(0), ARC_START_DEG);
  assert.equal(valueToAngle(GAUGE_MAX), ARC_END_DEG);
  assert.equal(valueToAngle(GAUGE_MAX / 2), 90);
});

test("valueToAngle clamps out-of-range doses onto the dial", () => {
  assert.equal(valueToAngle(-50), ARC_START_DEG);
  assert.equal(valueToAngle(9999), ARC_END_DEG);
});

test("valueToAngle is monotonically decreasing in dose", () => {
  let prev = Number.POSITIVE_INFINITY;
  for (let d = 0; d <= GAUGE_MAX; d += 5) {
    const a = valueToAngle(d);
    assert.ok(a < prev, `angle must decrease at dose ${d}`);
    prev = a;
  }
});

test("polar places 180deg left, 90deg on top, 0deg right", () => {
  const left = polar(CX, CY, R, 180);
  const top = polar(CX, CY, R, 90);
  const right = polar(CX, CY, R, 0);
  assert.ok(Math.abs(left.x - (CX - R)) < 1e-9);
  assert.ok(Math.abs(left.y - CY) < 1e-9);
  assert.ok(Math.abs(top.x - CX) < 1e-9);
  assert.ok(Math.abs(top.y - (CY - R)) < 1e-9);
  assert.ok(Math.abs(right.x - (CX + R)) < 1e-9);
  assert.ok(Math.abs(right.y - CY) < 1e-9);
});

test("every gauge point sits on the arc radius", () => {
  for (const d of [0, 17, 60, 80, 100, GAUGE_MAX]) {
    const p = polar(CX, CY, R, valueToAngle(d));
    const dist = Math.hypot(p.x - CX, p.y - CY);
    assert.ok(Math.abs(dist - R) < 1e-9, `dose ${d} off-radius`);
  }
});

test("arcPath emits a clockwise sweep between the two doses", () => {
  const d = arcPath(CX, CY, R, 0, GAUGE_MAX);
  assert.match(d, /^M [\d.-]+ [\d.-]+ A 88 88 0 0 1 [\d.-]+ [\d.-]+$/);
  // Starts at the left end, finishes at the right end.
  assert.ok(d.startsWith(`M ${(CX - R).toFixed(3)}`));
});

test("the gauge scale includes all three DGMS boundaries", () => {
  const values = GAUGE_TICKS;
  for (const t of [THRESHOLDS.warning, THRESHOLDS.danger, THRESHOLDS.critical]) {
    assert.ok(values.includes(t), `tick missing for threshold ${t}`);
  }
});

test("buildScale returns one entry per tick, in ascending dose order", () => {
  const scale = buildScale({ cx: CX, cy: CY, radius: R });
  assert.equal(scale.length, GAUGE_TICKS.length);
  scale.forEach((s, i) => assert.equal(s.value, GAUGE_TICKS[i]));
});

test("REGRESSION: each scale label lies on its own tick's radial line", () => {
  // The bug: labels were positioned independently of the arc, so they drifted
  // away from the tick they annotate. Both must share one angle.
  const scale = buildScale({ cx: CX, cy: CY, radius: R, labelOffset: 15 });
  for (const t of scale) {
    const tickAngle = (Math.atan2(CY - t.y2, t.x2 - CX) * 180) / Math.PI;
    const labelAngle = (Math.atan2(CY - t.labelY, t.labelX - CX) * 180) / Math.PI;
    assert.ok(
      Math.abs(tickAngle - labelAngle) < 1e-6,
      `tick ${t.value}: label angle ${labelAngle} != tick angle ${tickAngle}`,
    );
    assert.ok(
      Math.abs(tickAngle - t.angle) < 1e-6,
      `tick ${t.value}: stored angle disagrees with geometry`,
    );
  }
});

test("scale labels sit outside the arc and tick marks inside it", () => {
  const labelOffset = 15;
  const tickLength = 10;
  const scale = buildScale({ cx: CX, cy: CY, radius: R, tickLength, labelOffset });
  for (const t of scale) {
    const rLabel = Math.hypot(t.labelX - CX, t.labelY - CY);
    const rInner = Math.hypot(t.x1 - CX, t.y1 - CY);
    const rOuter = Math.hypot(t.x2 - CX, t.y2 - CY);
    assert.ok(Math.abs(rLabel - (R + labelOffset)) < 1e-9, `label radius for ${t.value}`);
    assert.ok(Math.abs(rInner - (R - tickLength)) < 1e-9, `inner radius for ${t.value}`);
    assert.ok(Math.abs(rOuter - R) < 1e-9, `outer radius for ${t.value}`);
  }
});

test("scale labels never overlap: monotonic x, sane spacing", () => {
  const scale = buildScale({ cx: CX, cy: CY, radius: R, labelOffset: 15 });
  for (let i = 1; i < scale.length; i += 1) {
    assert.ok(
      scale[i].labelX > scale[i - 1].labelX,
      `label ${scale[i].value} must be right of ${scale[i - 1].value}`,
    );
  }
  // Endpoints must stay inside the 240-unit viewBox with the "0"/"120" glyphs.
  assert.ok(scale[0].labelX >= 0, "first label off the left edge");
  assert.ok(scale[scale.length - 1].labelX <= 240, "last label off the right edge");
});

test("label anchors point text away from the dial", () => {
  const scale = buildScale({ cx: CX, cy: CY, radius: R });
  const byValue = Object.fromEntries(scale.map((s) => [s.value, s.anchor]));
  assert.equal(byValue[0], "end"); // far left → grows leftwards
  assert.equal(byValue[60], "middle"); // apex → centred
  assert.equal(byValue[120], "start"); // far right → grows rightwards
  assert.equal(labelAnchor(180), "end");
  assert.equal(labelAnchor(90), "middle");
  assert.equal(labelAnchor(0), "start");
});

test("bands tile the whole scale with no gaps or overlaps", () => {
  const bands = gaugeBands();
  assert.equal(bands[0].from, 0);
  assert.equal(bands[bands.length - 1].to, GAUGE_MAX);
  for (let i = 1; i < bands.length; i += 1) {
    assert.equal(bands[i].from, bands[i - 1].to, "band boundary mismatch");
  }
});

test("each band's midpoint classifies as that band's status", () => {
  for (const b of gaugeBands()) {
    const mid = (b.from + b.to) / 2;
    assert.equal(classifyDose(mid), b.status, `midpoint ${mid} of ${b.status}`);
    assert.equal(b.color, statusMeta(b.status).color);
  }
});

test("needle for a critical dose lands in the critical band's arc segment", () => {
  const dose = 101.261; // the value observed in the live E2E scan
  const angle = valueToAngle(dose);
  const critical = gaugeBands().find((b) => b.status === "critical");
  const a0 = valueToAngle(critical.from);
  const a1 = valueToAngle(critical.to);
  assert.ok(angle <= a0 && angle >= a1, `angle ${angle} outside [${a1}, ${a0}]`);
  assert.equal(classifyDose(dose), "critical");
});
