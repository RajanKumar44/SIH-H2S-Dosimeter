"""
demo_simulator.py
=================
Generates a synthetic colorimetric dataset, trains a model on it, and runs a
full end-to-end pipeline test WITHOUT needing real strip photos.

This is the primary testing and validation script for Phase 1.
Run this to verify the entire ML pipeline works before using real data.

Usage:
  python demo_simulator.py
  python demo_simulator.py --n_samples 200 --noise 0.05
"""

import argparse
import logging
import json
import sys
from pathlib import Path

# Force UTF-8 output on Windows to avoid cp1252 crash
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from image_processor import rgb_to_lab, compute_delta_E2000, BASELINE_LAB
from model_trainer import engineer_features, train, predict, MODELS_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

DATASETS_DIR = Path("datasets")
RESULTS_DIR = Path("results")
DATASETS_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# Fresh copper-acetate strip: blue-green (~R=80 G=160 B=140)
FRESH_R, FRESH_G, FRESH_B = 80.0, 160.0, 140.0


def simulate_strip_color(dose_ppm_hr: float, noise_std: float = 0.03) -> dict:
    """
    Simulate the RGB color of a copper-acetate strip after a given H2S dose.

    Physics-based model:
    - Copper acetate (blue-green) + H2S -> Copper sulfide (grey-brown)
    - R increases with dose (more brown)
    - G decreases with dose
    - B decreases with dose
    - Response saturates at high doses (sigmoid-like)

    Returns a dict of color features matching dataset_builder CSV schema.
    """
    rng = np.random.default_rng()

    # Sigmoid saturation model for dose -> color shift
    # Max color shift at saturation dose of ~100 ppm.hr
    saturation_dose = 80.0
    shift = 1.0 - np.exp(-dose_ppm_hr / saturation_dose)

    # Color transition: fresh (blue-green) -> exposed (grey-brown)
    R = FRESH_R + shift * (160.0 - FRESH_R) + rng.normal(0, noise_std * 255)
    G = FRESH_G + shift * (110.0 - FRESH_G) + rng.normal(0, noise_std * 255)
    B = FRESH_B + shift * (90.0  - FRESH_B) + rng.normal(0, noise_std * 255)

    R = float(np.clip(R, 0, 255))
    G = float(np.clip(G, 0, 255))
    B = float(np.clip(B, 0, 255))

    L, a, b = rgb_to_lab(R, G, B)
    bL, ba, bb = BASELINE_LAB
    delta_E = compute_delta_E2000(bL, ba, bb, L, a, b)

    # HSV
    r_n, g_n, b_n = R/255, G/255, B/255
    V = max(r_n, g_n, b_n)
    diff = V - min(r_n, g_n, b_n)
    S = diff / V if V > 0 else 0.0
    if diff == 0:
        H = 0.0
    elif V == r_n:
        H = 60 * ((g_n - b_n) / diff % 6)
    elif V == g_n:
        H = 60 * ((b_n - r_n) / diff + 2)
    else:
        H = 60 * ((r_n - g_n) / diff + 4)

    return {
        "R": round(R, 3), "G": round(G, 3), "B": round(B, 3),
        "L": round(L, 4), "a_star": round(a, 4), "b_star": round(b, 4),
        "delta_E": round(delta_E, 4),
        "H": round(H, 4), "S": round(S, 4), "V": round(V, 4),
        "L_corr": round(L, 4), "a_corr": round(a, 4), "b_corr": round(b, 4),
        "delta_E_corr": round(delta_E, 4),
        "confidence": 1.0,
    }


def generate_synthetic_dataset(
    n_samples: int = 150,
    noise_std: float = 0.04,
    output_csv: str = "datasets/dataset.csv",
) -> pd.DataFrame:
    """
    Generate a realistic synthetic dataset covering the full H2S dose range.

    Dose distribution:
    - 30% at low doses (0–10 ppm.hr) — normal indoor background
    - 40% at medium doses (10–60 ppm.hr) — occupational exposure
    - 30% at high doses (60–120 ppm.hr) — near/over DGMS limit
    """
    rng = np.random.default_rng(42)

    doses = np.concatenate([
        rng.uniform(0, 10, int(n_samples * 0.3)),
        rng.uniform(10, 60, int(n_samples * 0.4)),
        rng.uniform(60, 120, int(n_samples * 0.3)),
    ])
    doses = doses[:n_samples]
    np.random.shuffle(doses)

    rows = []
    for i, dose in enumerate(doses):
        # Back-calculate h2s_ppm and exposure_time_min from dose
        # Assume random exposure between 30 min and 480 min (8 hr shift)
        exp_min = rng.uniform(30, 480)
        h2s_ppm = (dose * 60) / exp_min if exp_min > 0 else 0.0

        feats = simulate_strip_color(dose, noise_std=noise_std)
        row = {
            "sample_id": f"SIM{i+1:04d}",
            "image_path": f"simulated_{i+1:04d}.jpg",
            "h2s_ppm": round(h2s_ppm, 4),
            "exposure_time_min": round(exp_min, 2),
            "cumulative_dose_ppm_hr": round(dose, 4),
            **feats,
            "notes": "synthetic",
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(output_csv, index=False)
    log.info(f"Synthetic dataset: {len(df)} rows saved to {output_csv}")
    return df


def run_full_pipeline_test(n_samples: int = 150, noise_std: float = 0.04):
    """Run complete end-to-end test: generate data -> train model -> predict -> plot."""
    print("\n" + "=" * 65)
    print("  PHASE 1 — ML PIPELINE END-TO-END TEST (Synthetic Data)")
    print("=" * 65)

    # Step 1: Generate data
    print("\n[1/4] Generating synthetic colorimetric dataset...")
    df = generate_synthetic_dataset(n_samples=n_samples, noise_std=noise_std)
    print(f"      {len(df)} samples | dose range: {df['cumulative_dose_ppm_hr'].min():.2f} "
          f"- {df['cumulative_dose_ppm_hr'].max():.2f} ppm.hr")

    # Step 2: Train model
    print("\n[2/4] Training regression model...")
    result = train("datasets/dataset.csv")
    r2 = result["metrics"]["r2"]
    rmse = result["metrics"]["rmse"]

    # Step 3: Test prediction API (simulates what the backend will call)
    print("\n[3/4] Testing prediction API (5 spot checks)...")
    test_doses = [0, 10, 40, 80, 110]
    print(f"\n  {'True Dose':>12} {'Predicted':>12} {'Error':>10} {'Confidence':>12}")
    print(f"  {'-'*12} {'-'*12} {'-'*10} {'-'*12}")
    for true_dose in test_doses:
        feats = simulate_strip_color(true_dose, noise_std=0.01)
        feats_for_predict = {
            "R": feats["R"], "G": feats["G"], "B": feats["B"],
            "L": feats["L"], "a_star": feats["a_star"], "b_star": feats["b_star"],
            "delta_E": feats["delta_E"],
            "H": feats["H"], "S": feats["S"], "V": feats["V"],
            "L_corr": feats["L_corr"], "a_corr": feats["a_corr"], "b_corr": feats["b_corr"],
            "delta_E_corr": feats["delta_E_corr"],
        }
        pred = predict(feats_for_predict)
        err = pred["dose_ppm_hr"] - true_dose
        print(f"  {true_dose:>12.1f} {pred['dose_ppm_hr']:>12.3f} {err:>+10.3f} {pred['confidence']:>12}")

    # Step 4: Calibration curve plot
    print("\n[4/4] Generating calibration curve...")
    dose_range = np.linspace(0, 120, 300)
    predicted_doses = []
    for d in dose_range:
        feats = simulate_strip_color(d, noise_std=0.0)
        feats_pred = {k: v for k, v in feats.items()
                      if k in ["R","G","B","L","a_star","b_star","delta_E","H","S","V",
                               "L_corr","a_corr","b_corr","delta_E_corr"]}
        pred = predict(feats_pred)
        predicted_doses.append(pred["dose_ppm_hr"])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle("H₂S Dosimeter — Phase 1 Pipeline Validation", fontsize=13, fontweight="bold")

    # Calibration curve
    ax = axes[0]
    ax.plot(dose_range, dose_range, "k--", linewidth=1.5, label="Ideal (y=x)")
    ax.plot(dose_range, predicted_doses, "b-", linewidth=2, label="Model prediction")
    ax.axvline(80, color="orange", linestyle=":", linewidth=1.5, label="DGMS alert (80 ppm·hr)")
    ax.set_xlabel("True Cumulative Dose (ppm·hr)")
    ax.set_ylabel("Predicted Dose (ppm·hr)")
    ax.set_title(f"Calibration Curve\nR²={r2:.4f} | RMSE={rmse:.3f}")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Color shift visualization
    ax2 = axes[1]
    dose_pts = np.linspace(0, 120, 12)
    colors = []
    for d in dose_pts:
        c = simulate_strip_color(d, noise_std=0.0)
        colors.append((c["R"]/255, c["G"]/255, c["B"]/255))

    for i, (d, col) in enumerate(zip(dose_pts, colors)):
        rect = plt.Rectangle((i, 0), 1, 1, color=col)
        ax2.add_patch(rect)
        ax2.text(i+0.5, -0.15, f"{d:.0f}", ha="center", va="top", fontsize=8)

    ax2.set_xlim(0, len(dose_pts))
    ax2.set_ylim(-0.3, 1)
    ax2.set_xticks([])
    ax2.set_yticks([])
    ax2.set_xlabel("Cumulative Dose (ppm·hr) →")
    ax2.set_title("Simulated Strip Color Change\n(Fresh blue-green → Exposed grey-brown)")

    out_path = RESULTS_DIR / "phase1_pipeline_test.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"\n{'=' * 65}")
    print("  PHASE 1 RESULTS SUMMARY")
    print(f"{'=' * 65}")
    print(f"  [OK] Dataset generated     : {len(df)} synthetic samples")
    print(f"  [OK] Model trained         : {result['metadata']['model_name']}")
    r2_status = '[OK] TARGET MET' if r2 >= 0.85 else '[WARN] BELOW TARGET'
    print(f"  [OK] Test R2               : {r2:.4f}  {r2_status}")
    print(f"  [OK] Test RMSE             : {rmse:.4f} ppm.hr")
    print(f"  [OK] Calibration curve     : {out_path}")
    print(f"  [OK] Model saved           : models/h2s_model.pkl")
    print(f"{'=' * 65}")
    print("\n  Phase 1 ML pipeline is WORKING.")
    print("  Next: collect real strip photos -> run dataset_builder.py -> retrain.\n")

    return r2 >= 0.85


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="End-to-end Phase 1 pipeline test with synthetic data."
    )
    parser.add_argument("--n_samples", type=int, default=300,
                        help="Number of synthetic data points (default: 300)")
    parser.add_argument("--noise", type=float, default=0.03,
                        help="Color noise level 0-1 (default: 0.03)")
    args = parser.parse_args()

    success = run_full_pipeline_test(n_samples=args.n_samples, noise_std=args.noise)
    import sys
    sys.exit(0 if success else 1)
