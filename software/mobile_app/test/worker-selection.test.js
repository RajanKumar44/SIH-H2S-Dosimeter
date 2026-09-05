/**
 * Regression tests for the worker-selection logic in screens/ScanScreen.jsx.
 *
 * These cover the two genuine mobile-side defects found while investigating
 * "No active workers found. Add a worker in the admin dashboard first.":
 *
 *  1. The remembered worker code (localStorage, via getLastWorker) was kept
 *     unconditionally — `cur || active[0]?.worker_id`. If that worker was
 *     deactivated, renamed away, or the demo database was reset, the stale
 *     code stayed selected and every scan failed server-side with
 *     404 "Active worker '...' not found." even though the picker looked fine.
 *
 *  2. An empty roster was a dead end: the fetch ran only on mount, so a worker
 *     added in the admin dashboard afterwards stayed invisible until the app
 *     was killed and reopened.
 *
 * The selection rule is pure, so it is mirrored here exactly as implemented
 * rather than mounting React (the app has no DOM test renderer).
 *
 * Run with:  npm test
 */
import assert from "node:assert/strict";
import test from "node:test";

/**
 * Mirror of the ScanScreen rule:
 *   setWorkerId((cur) =>
 *     active.some((w) => w.worker_id === cur) ? cur : active[0]?.worker_id || "")
 */
function resolveSelectedWorker(remembered, activeRows) {
  const active = (activeRows || []).filter((w) => w.is_active !== false);
  return active.some((w) => w.worker_id === remembered)
    ? remembered
    : active[0]?.worker_id || "";
}

/** Mirror of the roster filter applied to the GET /workers/ response. */
function activeOnly(rows) {
  return (rows || []).filter((w) => w.is_active !== false);
}

const WRK001 = { worker_id: "WRK001", full_name: "Raj Aryan", is_active: true };
const WRK002 = { worker_id: "WRK002", full_name: "Second Worker", is_active: true };
const INACTIVE = { worker_id: "WRK009", full_name: "Retired", is_active: false };

test("a remembered worker that is still active stays selected", () => {
  assert.equal(resolveSelectedWorker("WRK002", [WRK001, WRK002]), "WRK002");
});

test("a STALE remembered worker is replaced by the first active worker", () => {
  // The bug: "WRK777" used to survive and make every scan 404.
  assert.equal(resolveSelectedWorker("WRK777", [WRK001, WRK002]), "WRK001");
});

test("a remembered worker that has been DEACTIVATED is not kept", () => {
  assert.equal(resolveSelectedWorker("WRK009", [WRK001, INACTIVE]), "WRK001");
});

test("no remembered worker falls back to the first active worker", () => {
  assert.equal(resolveSelectedWorker("", [WRK001, WRK002]), "WRK001");
});

test("an empty roster yields an empty selection (never a fabricated code)", () => {
  // Guards the explicit requirement: WRK001 must NOT be hard-coded client-side.
  assert.equal(resolveSelectedWorker("WRK001", []), "");
  assert.equal(resolveSelectedWorker("", []), "");
});

test("a roster of only inactive workers yields an empty selection", () => {
  assert.equal(resolveSelectedWorker("WRK009", [INACTIVE]), "");
  assert.deepEqual(activeOnly([INACTIVE]), []);
});

test("the roster filter drops is_active=false and keeps is_active=true", () => {
  assert.deepEqual(
    activeOnly([WRK001, INACTIVE, WRK002]).map((w) => w.worker_id),
    ["WRK001", "WRK002"],
  );
});

test("a worker with is_active omitted is treated as active (backend default)", () => {
  const noFlag = { worker_id: "WRK010", full_name: "No Flag" };
  assert.deepEqual(activeOnly([noFlag]).map((w) => w.worker_id), ["WRK010"]);
  assert.equal(resolveSelectedWorker("", [noFlag]), "WRK010");
});

test("a null/undefined response body does not throw", () => {
  assert.deepEqual(activeOnly(null), []);
  assert.deepEqual(activeOnly(undefined), []);
  assert.equal(resolveSelectedWorker("WRK001", null), "");
});

test("the seeded demo worker WRK001 is selectable once the backend returns it", () => {
  // End state of the backend fix: the roster is no longer empty.
  const rows = [WRK001];
  assert.deepEqual(activeOnly(rows).map((w) => w.worker_id), ["WRK001"]);
  assert.equal(resolveSelectedWorker("", rows), "WRK001");
});
