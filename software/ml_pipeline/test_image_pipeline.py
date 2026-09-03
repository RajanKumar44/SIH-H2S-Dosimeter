"""
test_image_pipeline.py
======================
Regression tests for the image-processing pipeline, covering the three defects
found in the Step-1 audit:

  1. ROI hue dead-zone. The old detector used two disjoint HSV hue windows
     (fresh 80-150, exposed <=35 on OpenCV's 0-179 scale). Mid-transition
     strips fell between them, ROI detection returned None, and the code
     silently centre-cropped — averaging in background pixels. Observed:
     true 35 ppm.hr predicted as ~62.5 ppm.hr. The whole 20-70 ppm.hr DGMS
     warning band was affected.

  2. Hue scale mismatch. Training data computed H in degrees (0-360) while
     inference read `cv2.cvtColor(..., COLOR_BGR2HSV)` on uint8, which packs
     hue into 0-179. The model was trained on doubled hue.

  3. Dead lighting correction. `build_color_correction_matrix` existed but no
     caller ever passed a matrix into `process_strip_image`.

Run:
  python test_image_pipeline.py            # uses models/h2s_model.pkl if present
  python test_image_pipeline.py --no-model # colour/ROI checks only

Predictions are checked for stability, ordering and bounded error — never
against exact values, because demo_simulator.py is unseeded (see README).
"""
import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

from image_processor import (
    BASELINE_LAB,
    REFERENCE_PATCHES_LAB,
    ROI_MIN_SCORE,
    apply_color_correction,
    build_color_correction_matrix,
    compute_delta_E2000,
    detect_strip_roi,
    process_strip_array,
    process_strip_image,
    rgb_to_hsv,
    rgb_to_lab,
)
from demo_simulator import simulate_strip_color

# The dose sweep required by the task, spanning fresh -> saturated exposure.
DOSES = [0, 10, 20, 35, 50, 60, 68, 80, 88, 100, 108, 120]

# Doses that the OLD two-window hue detector could not see at all.
FORMER_DEAD_ZONE = [20, 35, 50, 68]

PASS = 0
FAIL = 0
FAILURES = []


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name}   << {detail}")
        FAIL += 1
        FAILURES.append(f"{name}  {detail}")


def section(title):
    print(f"\n{'=' * 66}\n  {title}\n{'=' * 66}")


# ── Synthetic scene rendering ───────────────────────────────────────────────

def render_strip(dose, bg=210, size=(400, 600), noise=0.0, seed=None,
                 bbox=(150, 160, 300, 80)):
    """
    Render a strip patch of the colour that `dose` produces, on a flat
    background. Colour comes from the same `simulate_strip_color` model that
    generates training data, so the test exercises the real colour path.

    Returns (bgr_image, expected_features_dict).
    """
    rng = np.random.default_rng(seed)
    feats = simulate_strip_color(dose, noise_std=0.0)

    h, w = size
    img = np.full((h, w, 3), bg, np.uint8)
    x, y, bw, bh = bbox
    img[y:y + bh, x:x + bw] = (int(feats["B"]), int(feats["G"]), int(feats["R"]))

    if noise > 0:
        img = np.clip(img.astype(np.float32)
                      + rng.normal(0, noise * 255, img.shape), 0, 255).astype(np.uint8)
    return img, feats


def render_textured_scene(dose, seed=0):
    """
    A harder scene: gradient background, a distractor object, and sensor noise.
    Guards against the detector only working on a perfectly flat backdrop.
    """
    rng = np.random.default_rng(seed)
    feats = simulate_strip_color(dose, noise_std=0.0)

    h, w = 480, 640
    grad = np.linspace(150, 225, w, dtype=np.float32)
    img = np.repeat(grad[None, :], h, axis=0)
    img = np.stack([img, img, img], axis=2)

    # Distractor: a large dull rectangle elsewhere in the frame.
    cv2.rectangle(img, (40, 40), (190, 130), (120, 120, 118), -1)

    # The strip.
    cv2.rectangle(img, (260, 250), (520, 340),
                  (float(feats["B"]), float(feats["G"]), float(feats["R"])), -1)

    img = np.clip(img + rng.normal(0, 4.0, img.shape), 0, 255).astype(np.uint8)
    return img, feats


# ── 1. Canonical hue convention ─────────────────────────────────────────────

def test_hue_convention():
    section("1. Canonical hue convention (H degrees 0-360, S/V 0-1)")

    # Anchors: a full 0-360 hue circle, not OpenCV's 0-179 half-degrees.
    for (rgb, eH, name) in [((255, 0, 0), 0.0, "red"),
                            ((255, 255, 0), 60.0, "yellow"),
                            ((0, 255, 0), 120.0, "green"),
                            ((0, 255, 255), 180.0, "cyan"),
                            ((0, 0, 255), 240.0, "blue"),
                            ((255, 0, 255), 300.0, "magenta")]:
        H, S, V = rgb_to_hsv(*rgb)
        check(f"rgb_to_hsv {name}: H={eH} deg", abs(H - eH) < 0.5, f"got {H:.2f}")
        check(f"rgb_to_hsv {name}: S,V in [0,1]", 0.0 <= S <= 1.0 and 0.0 <= V <= 1.0,
              f"S={S} V={V}")

    # THE regression: training features and inference features must agree.
    # Previously the simulator produced degrees while process_strip_image
    # produced OpenCV half-degrees, a factor-of-2 discrepancy in H.
    print("\n  Training feature vs inference feature, same physical colour:")
    print(f"    {'dose':>5} {'sim H':>9} {'photo H':>9} {'ratio':>7}   {'sim S':>7} {'photo S':>8}")
    worst_h = 0.0
    for dose in DOSES:
        img, sim = render_strip(dose)
        r = process_strip_array(img)
        ratio = (r.H / sim["H"]) if sim["H"] else 1.0
        worst_h = max(worst_h, abs(r.H - sim["H"]))
        print(f"    {dose:>5} {sim['H']:>9.3f} {r.H:>9.3f} {ratio:>7.3f}   "
              f"{sim['S']:>7.4f} {r.S:>8.4f}")

    # Tolerance covers uint8 quantisation of the rendered patch only.
    check("simulator H == process_strip_array H (no 2x scale mismatch)",
          worst_h < 3.0, f"max |dH| = {worst_h:.3f} deg")

    # Explicit guard: OpenCV's own conversion is half-scale, which is exactly
    # the bug. Assert we are NOT on that scale.
    px = np.full((4, 4, 3), (0, 255, 0), np.uint8)          # pure green, BGR
    cv_h = float(cv2.cvtColor(px, cv2.COLOR_BGR2HSV)[:, :, 0].mean())
    our_h, _, _ = rgb_to_hsv(0, 255, 0)
    check("canonical hue is NOT OpenCV's 0-179 scale",
          abs(our_h - 120.0) < 0.5 and abs(cv_h - 60.0) < 0.5 and abs(our_h - 2 * cv_h) < 1.0,
          f"ours={our_h:.1f} opencv={cv_h:.1f}")


# ── 2. ROI detection across the whole gradient ──────────────────────────────

def test_roi_across_gradient():
    section("2. ROI detection across the exposure gradient")

    print(f"  {'dose':>5} {'detected':>9} {'score':>7} {'method':>20} {'bbox':>22}")
    detected = 0
    for dose in DOSES:
        img, _ = render_strip(dose)
        bbox, det = detect_strip_roi(img, return_details=True)
        ok = bbox is not None
        detected += ok
        print(f"  {dose:>5} {str(ok):>9} {det['score']:>7.3f} {det['method']:>20} "
              f"{str(bbox):>22}")
        check(f"dose {dose}: ROI detected", ok,
              f"best score {det['score']:.3f} < {ROI_MIN_SCORE}")

    check(f"ROI found at every one of {len(DOSES)} doses", detected == len(DOSES),
          f"{detected}/{len(DOSES)}")

    # The specific regression.
    print("\n  Former hue dead-zone (old detector saw NONE of these):")
    for dose in FORMER_DEAD_ZONE:
        img, _ = render_strip(dose)
        bbox, det = detect_strip_roi(img, return_details=True)
        print(f"    dose {dose:>3}: {'OK' if bbox else 'MISSED'} score={det['score']:.3f}")
        check(f"dead-zone dose {dose} now detected", bbox is not None)

    # Geometry: the returned box should land on the strip we drew.
    img, _ = render_strip(35, bbox=(150, 160, 300, 80))
    bbox, _ = detect_strip_roi(img, return_details=True)
    if bbox:
        x, y, w, h = bbox
        check("bbox is close to the drawn strip rect (150,160,300,80)",
              abs(x - 150) <= 6 and abs(y - 160) <= 6
              and abs(w - 300) <= 8 and abs(h - 80) <= 8,
              f"got {bbox}")

    # Harder scene with a gradient background and a distractor.
    print("\n  Textured background + distractor object:")
    for dose in (20, 50, 88):
        img, sim = render_textured_scene(dose, seed=dose)
        r = process_strip_array(img)
        drgb = abs(r.R - sim["R"]) + abs(r.G - sim["G"]) + abs(r.B - sim["B"])
        print(f"    dose {dose:>3}: roi={r.roi_detected} conf={r.roi_confidence:.3f} "
              f"sum|dRGB|={drgb:.1f}")
        check(f"textured scene dose {dose}: strip located, not the distractor",
              r.roi_detected and drgb < 45.0, f"sum|dRGB|={drgb:.1f}")


def test_roi_fallback_is_low_confidence():
    section("3. Fallback never masquerades as a confident detection")

    # A featureless frame: nothing to find, so the fallback must engage.
    blank = np.full((300, 400, 3), 200, np.uint8)
    r = process_strip_array(blank)
    check("blank frame -> roi_detected is False", r.roi_detected is False)
    check("blank frame -> method names the fallback",
          r.roi_method == "center_crop_fallback", r.roi_method)
    check("blank frame -> roi_confidence is low", r.roi_confidence <= 0.3,
          f"{r.roi_confidence}")
    check("blank frame -> overall confidence is low", r.confidence <= 0.3,
          f"{r.confidence}")
    check("blank frame -> a diagnostic reason is given", bool(r.roi_reason), r.roi_reason)
    print(f"    reason: {r.roi_reason}")

    # A real detection must score clearly higher than any fallback.
    img, _ = render_strip(35)
    good = process_strip_array(img)
    check("real detection outranks the fallback",
          good.roi_confidence > r.roi_confidence + 0.3,
          f"{good.roi_confidence:.3f} vs {r.roi_confidence:.3f}")
    check("real detection reports a bbox", good.roi_bbox is not None)
    check("fallback reports no bbox", r.roi_bbox is None)


# ── 4. Feature sanity ───────────────────────────────────────────────────────

def test_features_finite_and_sane():
    section("4. Extracted features are finite and in range")

    for dose in DOSES:
        img, _ = render_strip(dose, noise=0.01, seed=dose)
        r = process_strip_array(img)
        feats = r.features_for_model()

        check(f"dose {dose}: all features finite",
              all(np.isfinite(v) for v in feats.values()),
              str({k: v for k, v in feats.items() if not np.isfinite(v)}))
        check(f"dose {dose}: RGB within 0-255",
              all(0 <= feats[c] <= 255 for c in "RGB"),
              f"R={feats['R']} G={feats['G']} B={feats['B']}")
        check(f"dose {dose}: H in [0,360), S/V in [0,1]",
              0 <= feats["H"] < 360 and 0 <= feats["S"] <= 1 and 0 <= feats["V"] <= 1,
              f"H={feats['H']} S={feats['S']} V={feats['V']}")
        check(f"dose {dose}: L in [0,100]", 0 <= feats["L"] <= 100, f"L={feats['L']}")
        check(f"dose {dose}: delta_E finite and >= 0",
              np.isfinite(feats["delta_E"]) and feats["delta_E"] >= 0,
              f"dE={feats['delta_E']}")
        check(f"dose {dose}: confidence in [0,1]",
              np.isfinite(r.confidence) and 0.0 <= r.confidence <= 1.0,
              f"confidence={r.confidence}")
        check(f"dose {dose}: roi_confidence in [0,1]",
              np.isfinite(r.roi_confidence) and 0.0 <= r.roi_confidence <= 1.0,
              f"roi_confidence={r.roi_confidence}")

    # features_for_model must supply exactly what predict() consumes.
    from model_trainer import FEATURE_COLS
    img, _ = render_strip(50)
    keys = set(process_strip_array(img).features_for_model())
    missing = [c for c in FEATURE_COLS if c not in keys]
    check("features_for_model covers every model FEATURE_COL", not missing, str(missing))


def test_delta_e_monotonic():
    section("5. delta_E increases with dose (physical ordering)")

    rows = []
    for dose in DOSES:
        img, _ = render_strip(dose)
        r = process_strip_array(img)
        rows.append((dose, r.delta_E))
        print(f"    dose {dose:>5} -> dE {r.delta_E:8.3f}")

    des = [dE for _, dE in rows]
    # Spearman-style: count non-decreasing adjacent pairs. The strip colour is
    # monotonic in dose by construction, so dE should be too.
    increases = sum(1 for i in range(1, len(des)) if des[i] >= des[i - 1] - 0.5)
    check("delta_E is monotonically non-decreasing in dose",
          increases == len(des) - 1, f"{increases}/{len(des)-1} adjacent pairs ordered")
    check("delta_E spans a useful range across 0-120 ppm.hr",
          des[-1] - des[0] > 8.0, f"span {des[-1] - des[0]:.2f}")


# ── 6. Lighting correction ──────────────────────────────────────────────────

def test_lighting_correction():
    section("6. Lighting correction is wired up and honestly reported")

    img, _ = render_strip(50)

    # Default path: no card information, so no correction — and it must say so.
    raw = process_strip_array(img)
    check("default: lighting_corrected is False", raw.lighting_corrected is False)
    check("default: correction_method == 'none'", raw.correction_method == "none",
          raw.correction_method)
    check("default: L_corr == L (pass-through)", abs(raw.L_corr - raw.L) < 1e-9)
    check("default: delta_E_corr == delta_E",
          abs(raw.delta_E_corr - raw.delta_E) < 1e-9)

    # An identity card measurement must be a no-op, proving the maths is sane.
    ident = build_color_correction_matrix(REFERENCE_PATCHES_LAB)
    corrected = process_strip_array(img, correction_matrix=ident)
    check("identity card -> correction applied flag set",
          corrected.lighting_corrected is True)
    check("identity card -> method reported",
          corrected.correction_method == "caller_supplied_matrix",
          corrected.correction_method)
    check("identity card -> Lab unchanged (within solver tolerance)",
          abs(corrected.L_corr - raw.L) < 0.5
          and abs(corrected.a_corr - raw.a) < 0.5
          and abs(corrected.b_corr - raw.b) < 0.5,
          f"({corrected.L_corr:.3f},{corrected.a_corr:.3f},{corrected.b_corr:.3f}) "
          f"vs ({raw.L:.3f},{raw.a:.3f},{raw.b:.3f})")

    # A warm-cast card: correction should pull the measurement back toward the
    # reference, i.e. undo the cast rather than shifting arbitrarily.
    warm = {k: (L * 0.92, a + 6.0, b + 9.0) for k, (L, a, b) in REFERENCE_PATCHES_LAB.items()}
    M = build_color_correction_matrix(warm)
    fixed = process_strip_array(img, measured_patches=warm)
    check("measured_patches -> correction applied",
          fixed.lighting_corrected is True and fixed.correction_method == "reference_card_lstsq",
          f"{fixed.lighting_corrected} {fixed.correction_method}")
    check("measured_patches path changes the corrected Lab",
          abs(fixed.L_corr - raw.L) > 0.01 or abs(fixed.a_corr - raw.a) > 0.01)

    # Round-trip: applying the fitted matrix to each measured patch should
    # recover its reference value.
    resid = max(
        float(np.linalg.norm(np.array(apply_color_correction(*warm[k], M))
                             - np.array(REFERENCE_PATCHES_LAB[k])))
        for k in REFERENCE_PATCHES_LAB
    )
    check("fitted matrix maps measured patches back onto references",
          resid < 1.0, f"max residual {resid:.4f}")
    print(f"    max patch residual after correction: {resid:.4f} Lab units")

    # Guard rails on bad input, rather than silently fitting garbage.
    try:
        build_color_correction_matrix({"white": (95, 0, 0)})
        check("incomplete patch dict raises", False, "no exception raised")
    except KeyError:
        check("incomplete patch dict raises KeyError", True)
    try:
        build_color_correction_matrix({"a": (1, 2, 3)}, {"a": (1, 2, 3)})
        check("under-determined fit raises", False, "no exception raised")
    except ValueError:
        check("under-determined fit raises ValueError", True)


# ── 7. End-to-end prediction ────────────────────────────────────────────────

def test_end_to_end_prediction(model_path):
    section("7. End-to-end: image -> ROI -> features -> model -> dose")

    from model_trainer import predict

    print(f"  {'true':>6} {'dE':>8} {'roi':>6} {'conf':>6} {'pred':>9} {'error':>9}")
    rows = []
    for dose in DOSES:
        img, _ = render_strip(dose, noise=0.01, seed=1000 + dose)
        r = process_strip_array(img)
        p = predict(r.features_for_model(), model_path=str(model_path))
        err = p["dose_ppm_hr"] - dose
        rows.append((dose, p["dose_ppm_hr"], err, r))
        print(f"  {dose:>6} {r.delta_E:>8.3f} {str(r.roi_detected):>6} "
              f"{r.roi_confidence:>6.3f} {p['dose_ppm_hr']:>9.3f} {err:>+9.3f}")

        check(f"dose {dose}: prediction is finite and non-negative",
              np.isfinite(p["dose_ppm_hr"]) and p["dose_ppm_hr"] >= 0,
              str(p))
        check(f"dose {dose}: ROI detected (no silent centre-crop)", r.roi_detected)

    errs = [abs(e) for _, _, e, _ in rows]
    mae = float(np.mean(errs))
    print(f"\n    MAE across the sweep: {mae:.2f} ppm.hr   (max {max(errs):.2f})")

    # Tolerances, not exact values: the model is retrained unseeded each run.
    # The RMSE on synthetic data is ~10 ppm.hr, so ~25 is a generous ceiling
    # that still catches a systemic pipeline break.
    check("MAE across the dose sweep is within tolerance", mae < 20.0,
          f"MAE={mae:.2f}")
    check("no single dose is off by more than 30 ppm.hr", max(errs) < 30.0,
          f"max |err|={max(errs):.2f}")

    # THE headline regression: dose 35 used to predict ~62.5 (ROI failure).
    d35 = next(r for r in rows if r[0] == 35)
    print(f"\n    dose=35 regression: predicted {d35[1]:.2f} ppm.hr "
          f"(old broken pipeline: ~62.5)")
    check("dose 35 predicted within 20 ppm.hr of truth", abs(d35[2]) < 20.0,
          f"predicted {d35[1]:.2f}, error {d35[2]:+.2f}")
    check("dose 35 no longer lands in the old ~62 ppm.hr failure band",
          d35[1] < 55.0, f"predicted {d35[1]:.2f}")
    check("dose 35 is classified below the 60 ppm.hr warning threshold",
          d35[1] < 60.0, f"predicted {d35[1]:.2f}")

    # Ordering: predictions should broadly track dose.
    preds = [p for _, p, _, _ in rows]
    pairs = sum(1 for i in range(1, len(preds)) if preds[i] >= preds[i - 1] - 8.0)
    check("predictions broadly increase with dose",
          pairs >= len(preds) - 3, f"{pairs}/{len(preds)-1} adjacent pairs ordered")

    # Stability: same scene, different sensor noise -> similar answer.
    spread = []
    for dose in (35, 68, 100):
        vals = []
        for s in range(5):
            img, _ = render_strip(dose, noise=0.015, seed=s)
            vals.append(predict(process_strip_array(img).features_for_model(),
                                model_path=str(model_path))["dose_ppm_hr"])
        sd = float(np.std(vals))
        spread.append(sd)
        print(f"    dose {dose}: 5 noisy repeats -> sd {sd:.2f} ppm.hr "
              f"(min {min(vals):.1f}, max {max(vals):.1f})")
        check(f"dose {dose}: repeat predictions are stable under noise", sd < 10.0,
              f"sd={sd:.2f}")

    # Different background brightness must not swing the answer much: the ROI
    # is now measured from an inset of the detected box, so the surround should
    # barely matter.
    print()
    for dose in (35, 88):
        vals = []
        for bg in (60, 130, 200, 245):
            img, _ = render_strip(dose, bg=bg)
            vals.append(predict(process_strip_array(img).features_for_model(),
                                model_path=str(model_path))["dose_ppm_hr"])
        rng_ = max(vals) - min(vals)
        print(f"    dose {dose}: backgrounds 60/130/200/245 -> "
              f"{[round(v,1) for v in vals]} range {rng_:.2f}")
        check(f"dose {dose}: background brightness barely affects the dose",
              rng_ < 12.0, f"range {rng_:.2f}")


def test_file_and_array_paths_agree(tmpdir):
    section("8. process_strip_image (file) == process_strip_array (memory)")

    img, _ = render_strip(68)
    p = Path(tmpdir) / "strip_68.png"
    cv2.imwrite(str(p), img)

    a = process_strip_array(img)
    b = process_strip_image(str(p))
    for field in ("R", "G", "B", "L", "a", "b", "delta_E", "H", "S", "V"):
        va, vb = getattr(a, field), getattr(b, field)
        check(f"{field} matches between file and array paths", abs(va - vb) < 1e-6,
              f"{va} vs {vb}")
    check("roi_detected matches", a.roi_detected == b.roi_detected)

    try:
        process_strip_image(str(Path(tmpdir) / "does_not_exist.png"))
        check("missing file raises FileNotFoundError", False, "no exception")
    except FileNotFoundError:
        check("missing file raises FileNotFoundError", True)


def test_predict_rejects_bad_input(model_path):
    section("9. predict() fails loudly on malformed features")

    from model_trainer import predict

    img, _ = render_strip(50)
    feats = process_strip_array(img).features_for_model()

    ok = dict(feats)
    check("well-formed features predict fine",
          np.isfinite(predict(ok, model_path=str(model_path))["dose_ppm_hr"]))

    incomplete = {k: v for k, v in feats.items() if k != "delta_E_corr"}
    try:
        predict(incomplete, model_path=str(model_path))
        check("missing feature raises instead of returning a silent number",
              False, "no exception raised")
    except KeyError:
        check("missing feature raises KeyError", True)

    nan_feats = dict(feats)
    nan_feats["delta_E_corr"] = float("nan")
    try:
        predict(nan_feats, model_path=str(model_path))
        check("NaN feature raises instead of predicting", False, "no exception raised")
    except ValueError:
        check("NaN feature raises ValueError", True)


# ── main ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Image-pipeline regression tests.")
    ap.add_argument("--model", default="models/h2s_model.pkl")
    ap.add_argument("--no-model", action="store_true",
                    help="Skip prediction tests (colour/ROI checks only).")
    args = ap.parse_args()

    print("=" * 66)
    print("  IMAGE PIPELINE REGRESSION TESTS")
    print("=" * 66)
    print(f"  doses under test: {DOSES}")
    print(f"  baseline Lab    : {BASELINE_LAB}")
    print(f"  ROI_MIN_SCORE   : {ROI_MIN_SCORE}")

    test_hue_convention()
    test_roi_across_gradient()
    test_roi_fallback_is_low_confidence()
    test_features_finite_and_sane()
    test_delta_e_monotonic()
    test_lighting_correction()

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        test_file_and_array_paths_agree(td)

    model_path = Path(args.model)
    if args.no_model:
        print("\n  [SKIP] prediction tests (--no-model)")
    elif not model_path.exists():
        print(f"\n  [SKIP] prediction tests: {model_path} not found."
              f"\n         Run `python demo_simulator.py` first to train a model.")
    else:
        test_end_to_end_prediction(model_path)
        test_predict_rejects_bad_input(model_path)

    total = PASS + FAIL
    print(f"\n{'=' * 66}")
    print(f"  RESULTS: {PASS}/{total} passed, {FAIL} failed")
    print(f"{'=' * 66}")
    if FAILURES:
        print("\nFAILURES:")
        for f in FAILURES:
            print(f"  - {f}")
    print()
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
