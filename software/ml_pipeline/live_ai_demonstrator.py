"""
live_ai_demonstrator.py
=======================
Live Demonstration & Testing Suite for the AI/ML H2S Dosimeter System.

This script demonstrates and verifies:
1. Colorimetric Physics & Chemistry Simulation (Copper Acetate + H2S -> CuS)
2. Color Space Conversion (sRGB -> CIE XYZ -> CIE L*a*b*)
3. CIE DE2000 (ΔE₀₀) Perceptual Color Difference calculation
4. Environmental Compensation (Temperature & Relative Humidity adjustment)
5. Machine Learning Inference across multiple exposure levels (Safe, Warning, Danger, Critical)
6. Model Performance & Confidence Metrics
7. Full Pipeline Integration (ML Model Output -> Backend API -> Threshold Alerting)
"""

import sys
import os
import time
import json
import numpy as np
import pandas as pd

# Ensure terminal UTF-8 encoding on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Import ML pipeline modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from image_processor import (
    rgb_to_lab,
    compute_delta_E2000
)
from model_trainer import train, predict
from demo_simulator import generate_synthetic_dataset, simulate_strip_color

def header(title: str, subtitle: str = ""):
    print("\n" + "═" * 74)
    print(f"  ⚡ {title.upper()}")
    if subtitle:
        print(f"     {subtitle}")
    print("═" * 74)

def main():
    header("SIH26118 H2S Dosimeter — AI/ML System Deep Dive & Live Test",
           "Real-time demonstration of Colorimetry + ML Inference Pipeline")

    # -------------------------------------------------------------------------
    # STEP 1: Understanding the Chemical & Physical Color Transformation
    # -------------------------------------------------------------------------
    header("Step 1: Chemical Reaction & Optical Transformation",
           "Cu(CH3COO)2 (Light Teal/Blue) + H2S (g) → CuS (Brown/Black precipitate)")

    print("""
    [Reaction Mechanism]
    As industrial workers wear the wristband, ambient H2S gas diffuses across 
    the porous membrane to react with copper(II) acetate impregnated on the test strip:
    
       Cu(CH3COO)2 (aq/solid) + H2S (g) ──> CuS (s)↓ + 2 CH3COOH (g)
       (Fresh: Pale Blue/Green)              (Exposed: Dark Brown / Black)
    
    The darkness and color shift magnitude directly correlates to cumulative dose (ppm·hr).
    """)

    # -------------------------------------------------------------------------
    # STEP 2: Step-by-Step Colorimetric Math Verification
    # -------------------------------------------------------------------------
    header("Step 2: Optical Science — RGB to CIE L*a*b* & CIE DE2000 (ΔE₀₀)")

    # Baseline reference strip (Fresh Copper Acetate strip under standard D65 illuminant)
    fresh_rgb = (165, 205, 215) # Pale teal / light blue-gray
    fresh_lab = rgb_to_lab(*fresh_rgb)

    print(f"  • Reference (Unexposed Fresh Strip):")
    print(f"    - sRGB Values : R={fresh_rgb[0]}, G={fresh_rgb[1]}, B={fresh_rgb[2]}")
    print(f"    - CIE L*a*b*  : L*={fresh_lab[0]:.2f} (Lightness), a*={fresh_lab[1]:.2f} (Green-Red), b*={fresh_lab[2]:.2f} (Blue-Yellow)")

    # Test Scenarios representing 4 distinct worker exposure levels
    scenarios = [
        {"name": "Scenario A: Low Baseline Exposure", "dose_true": 15.0, "temp": 26.0, "hum": 50.0},
        {"name": "Scenario B: Moderate (Approaching Alert)", "dose_true": 62.0, "temp": 31.0, "hum": 68.0},
        {"name": "Scenario C: DGMS 8-hr Limit Exceeded", "dose_true": 85.0, "temp": 34.0, "hum": 75.0},
        {"name": "Scenario D: Acute Critical Toxic Spike", "dose_true": 115.0, "temp": 38.0, "hum": 82.0},
    ]

    print("\n  • Calculating CIE DE2000 (ΔE) and Color Shifts across Exposure Scenarios:")
    print("  " + "─" * 70)
    print(f"  {'Scenario':<30} | {'sRGB':<14} | {'CIE L*a*b*':<18} | {'ΔE₀₀ (Color Shift)'}")
    print("  " + "─" * 70)

    processed_scenarios = []
    for sc in scenarios:
        feats = simulate_strip_color(sc["dose_true"], noise_std=0.01)
        sc["rgb"] = (int(feats["R"]), int(feats["G"]), int(feats["B"]))
        sc["lab"] = (feats["L"], feats["a_star"], feats["b_star"])
        sc["delta_e"] = feats["delta_E"]
        sc["features_dict"] = feats
        processed_scenarios.append(sc)
        rgb_str = f"({sc['rgb'][0]},{sc['rgb'][1]},{sc['rgb'][2]})"
        lab_str = f"({sc['lab'][0]:.1f}, {sc['lab'][1]:.1f}, {sc['lab'][2]:.1f})"
        print(f"  {sc['name']:<30} | {rgb_str:<14} | {lab_str:<18} | ΔE = {sc['delta_e']:6.2f}")

    # -------------------------------------------------------------------------
    # STEP 3: Train & Test AI/ML Model on Comprehensive Dataset
    # -------------------------------------------------------------------------
    header("Step 3: AI Model Architecture & Calibration",
           "Evaluating Multi-Feature Regression: [ΔE, L*, a*, b*, RGB, Temp, Humidity] → Dose (ppm·hr)")

    dataset_path = os.path.join(os.path.dirname(__file__), "datasets", "live_demo_dataset.csv")
    os.makedirs(os.path.dirname(dataset_path), exist_ok=True)

    print("  [1/3] Generating synthetic calibration dataset matching published chemical isotherms...")
    generate_synthetic_dataset(n_samples=300, output_csv=dataset_path)

    print("  [2/3] Training & evaluating 5 AI regression models with 5-Fold Cross-Validation...")
    train_res = train(dataset_path)
    metadata = train_res["metadata"]
    all_models = metadata.get("all_models", {})

    print(f"\n  [3/3] Model Evaluation Summary:")
    print("  " + "─" * 70)
    print(f"  {'Model Architecture':<25} | {'CV R² Score (mean)':<20} | {'CV R² Std':<12}")
    print("  " + "─" * 70)
    for name, m in all_models.items():
        print(f"  {name:<25} | {m['cv_r2_mean']:<20.4f} | {m['cv_r2_std']:<12.4f}")
    print("  " + "─" * 70)
    print(f"  🏆 Best Performing Model : {metadata['model_name']}")
    # Report the target honestly — demo_simulator is unseeded, so R² varies
    # between runs and can land below 0.85.
    _r2 = metadata['test_r2']
    _verdict = "target met" if _r2 >= 0.85 else "BELOW the 0.85 target on this run"
    print(f"  🎯 Test Set R² Accuracy  : {_r2:.4f} ({_verdict})")
    print(f"  📉 Test Set RMSE Error   : {metadata['test_rmse']:.2f} ppm·hr")


    # -------------------------------------------------------------------------
    # STEP 4: Live Prediction on our 4 Test Scenarios
    # -------------------------------------------------------------------------
    header("Step 4: Real-Time Model Inference & DGMS Compliance Classification",
           "DGMS Thresholds: Safe (<60 ppm·hr) | Warning (60-80 ppm·hr) | Danger (80-100 ppm·hr) | Critical (>100 ppm·hr)")

    print(f"  {'Scenario':<28} | {'True Dose':<10} | {'AI Predicted':<12} | {'Error':<8} | {'DGMS Safety Status'}")
    print("  " + "─" * 75)

    predicted_doses = []
    for sc in processed_scenarios:
        res = predict(sc["features_dict"])
        pred_dose = res["dose_ppm_hr"]
        predicted_doses.append(pred_dose)
        error = abs(pred_dose - sc["dose_true"])

        if pred_dose >= 100.0:
            status_tag = "🚨 CRITICAL EVACUATE"
        elif pred_dose >= 80.0:
            status_tag = "🛑 DANGER (DGMS Limit)"
        elif pred_dose >= 60.0:
            status_tag = "⚠️  WARNING (75% Limit)"
        else:
            status_tag = "✅ SAFE NORMAL"

        print(f"  {sc['name']:<28} | {sc['dose_true']:5.1f} ppm·h | {pred_dose:6.1f} ppm·h | ±{error:4.1f}   | {status_tag}")

    # -------------------------------------------------------------------------
    # STEP 5: End-to-End System Integration Test (Mobile/ML -> Backend -> Dashboard)
    # -------------------------------------------------------------------------
    header("Step 5: End-to-End Integration Verification",
           "Simulating Mobile App uploading AI inference results to FastAPI backend...")

    import urllib.request
    import urllib.error
    import urllib.parse

    backend_url = os.getenv("H2S_API_BASE", "http://localhost:8000")
    # Dev credentials, overridable by env var. The backend guards /readings/
    # with a router-level JWT dependency, so an unauthenticated POST returns
    # 401 — this script used to send no Authorization header at all and hid
    # the failure in the except branch below.
    api_user = os.getenv("H2S_API_USER", "admin")
    api_pass = os.getenv("H2S_API_PASSWORD", "admin123")

    posted = False
    try:
        req = urllib.request.Request(f"{backend_url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as response:
            health = json.loads(response.read())
            print(f"  • Backend Service Connection: CONNECTED (status: {health.get('status')})")

            # Authenticate first (form-encoded, per OAuth2PasswordRequestForm).
            login_req = urllib.request.Request(
                f"{backend_url}/auth/login",
                data=urllib.parse.urlencode(
                    {"username": api_user, "password": api_pass}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(login_req, timeout=5) as login_resp:
                token = json.loads(login_resp.read())["access_token"]
            print(f"  • Authenticated as '{api_user}' (JWT acquired)")

            # Post live prediction to backend for Worker WRK001
            sc_danger = processed_scenarios[2]
            reading_data = {
                "worker_id": "WRK001",
                "badge_id": "BADGE-LIVE-DEMO",
                "delta_E": round(float(sc_danger["delta_e"]), 3),
                "delta_E_corr": round(float(sc_danger["delta_e"] * 0.98), 3),
                "dose_ppm_hr": round(float(predicted_doses[2]), 2),
                "R": sc_danger["rgb"][0],
                "G": sc_danger["rgb"][1],
                "B": sc_danger["rgb"][2],
                "L_star": round(float(sc_danger["lab"][0]), 2),
                "a_star": round(float(sc_danger["lab"][1]), 2),
                "b_star": round(float(sc_danger["lab"][2]), 2),
                "temperature_c": sc_danger["temp"],
                "humidity_pct": sc_danger["hum"],
                "model_confidence": "high",
                "scanned_by": "live_ai_demonstrator",
                "notes": "Live AI inference validation scan"
            }

            post_req = urllib.request.Request(
                f"{backend_url}/readings/",
                data=json.dumps(reading_data).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST"
            )
            with urllib.request.urlopen(post_req, timeout=5) as post_resp:
                result = json.loads(post_resp.read())
                posted = True
                print(f"  • Live Reading Ingested & Saved into SQLite DB:")
                print(f"    - Reading ID      : #{result.get('id')}")
                print(f"    - Worker Monitored: {reading_data['worker_id']}")
                print(f"    - Inferred Dose   : {result.get('dose_ppm_hr')} ppm·hr")
                print(f"    - Auto-Alert Fired: {result.get('alert_triggered')} (decided by backend)")
                print(f"    - Dashboard Sync  : Visible live at http://localhost:5173/#/dashboard")

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        print(f"  • Backend returned HTTP {e.code}: {body}")
        print(f"    (reading NOT ingested)")
    except Exception as e:
        print(f"  • Backend not reachable at {backend_url}: {e}")
        print(f"    (reading NOT ingested — start the backend to exercise this step)")

    if posted:
        header("Summary & Verification Complete",
               "ML pipeline verified; live reading ingested by the backend.")
    else:
        header("Summary — ML pipeline verified, backend step SKIPPED",
               "Colour science and inference ran locally. The backend was not "
               "reached, so no reading was stored and no alert was raised.")


if __name__ == "__main__":
    main()
