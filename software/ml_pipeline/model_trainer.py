"""
model_trainer.py
================
Trains a regression model: color features --> cumulative H2S dose (ppm.hr).

Workflow:
  1. Load dataset CSV (from dataset_builder.py)
  2. Feature engineering (deltaE, Lab, HSV features + derived features)
  3. Train multiple models; select best by cross-validated R2
  4. Save best model as models/h2s_model.pkl
  5. Print evaluation metrics

Usage:
  python model_trainer.py                        # uses datasets/dataset.csv
  python model_trainer.py --csv datasets/my.csv
"""

import os
import json
import argparse
import logging
import sys
import warnings
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split, cross_val_score, KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.linear_model import Ridge
from sklearn.svm import SVR
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

MODELS_DIR = Path("models")
MODELS_DIR.mkdir(exist_ok=True)

TARGET_COL = "cumulative_dose_ppm_hr"

# Feature columns read straight from the dataset CSV.
#
# HSV CONVENTION: H is in DEGREES on [0, 360), S and V on [0, 1] — the
# canonical convention defined by `image_processor.rgb_to_hsv`, which is the
# single producer used by both the simulator (training data) and
# `process_strip_image` (inference). Do not feed raw
# `cv2.cvtColor(..., COLOR_BGR2HSV)` output in here: on uint8 that is hue
# 0-179 and S/V 0-255, i.e. half-scale hue, which silently mistrains the model.
FEATURE_COLS = [
    "delta_E_corr",     # Primary: color difference from fresh baseline
    "L_corr",           # Lightness (darker = more exposed)
    "a_corr",           # Green-Red axis
    "b_corr",           # Blue-Yellow axis
    "H", "S", "V",      # HSV components (H degrees 0-360, S/V 0-1)
    "R", "G", "B",      # Raw RGB
    "delta_E",          # Uncorrected deltaE for comparison
]



def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived features that help the model learn non-linear relationships."""
    df = df.copy()
    # Color magnitude in Lab space
    df["C_star"] = np.sqrt(df["a_corr"]**2 + df["b_corr"]**2)
    # Hue angle in Lab
    df["h_angle"] = np.degrees(np.arctan2(df["b_corr"], df["a_corr"])) % 360
    # Darkness indicator (lower L = darker = more H2S)
    df["darkness"] = 100.0 - df["L_corr"]
    # B/G ratio (copper sulfide makes strip browner, reducing blue)
    df["B_G_ratio"] = df["B"] / (df["G"] + 1e-6)
    # Log transform of deltaE (handles non-linear response at saturation)
    df["log_delta_E"] = np.log1p(df["delta_E_corr"])
    return df


DERIVED_FEATURES = ["C_star", "h_angle", "darkness", "B_G_ratio", "log_delta_E"]
ALL_FEATURES = FEATURE_COLS + DERIVED_FEATURES


def build_model_candidates() -> dict:
    """Return a dict of named model pipelines to compare."""
    return {
        "PolyRidge_deg2": Pipeline([
            ("scaler", StandardScaler()),
            ("poly", PolynomialFeatures(degree=2, include_bias=False)),
            ("model", Ridge(alpha=1.0)),
        ]),
        "PolyRidge_deg3": Pipeline([
            ("scaler", StandardScaler()),
            ("poly", PolynomialFeatures(degree=3, include_bias=False)),
            ("model", Ridge(alpha=1.0)),
        ]),
        "SVR_rbf": Pipeline([
            ("scaler", StandardScaler()),
            ("model", SVR(kernel="rbf", C=10.0, epsilon=0.1, gamma="scale")),
        ]),
        "GradientBoosting": Pipeline([
            ("scaler", StandardScaler()),
            ("model", GradientBoostingRegressor(
                n_estimators=300, max_depth=5, learning_rate=0.03,
                subsample=0.8, min_samples_leaf=3, random_state=42
            )),
        ]),
        "RandomForest": Pipeline([
            ("model", RandomForestRegressor(
                n_estimators=300, max_depth=12, min_samples_leaf=2,
                random_state=42, n_jobs=-1
            )),
        ]),
    }


def evaluate_model(model, X_test, y_test) -> dict:
    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))
    mae = mean_absolute_error(y_test, y_pred)
    return {"r2": r2, "rmse": rmse, "mae": mae, "y_pred": y_pred}


def train(csv_path: str, test_size: float = 0.2, random_state: int = 42) -> dict:
    """
    Main training function.
    Returns dict with best model info and metrics.
    """
    df = pd.read_csv(csv_path)
    log.info(f"Loaded dataset: {len(df)} rows from {csv_path}")

    if len(df) < 10:
        raise ValueError(
            f"Dataset too small ({len(df)} rows). Need at least 10 labeled strips. "
            "Run demo_simulator.py to generate synthetic data for testing."
        )

    df = engineer_features(df)

    # Select available features
    available = [c for c in ALL_FEATURES if c in df.columns]
    log.info(f"Using {len(available)} features: {available}")

    X = df[available].values
    y = df[TARGET_COL].values

    # Train / test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )
    log.info(f"Train: {len(X_train)} samples | Test: {len(X_test)} samples")

    # Cross-validation to pick best model
    kf = KFold(n_splits=min(5, len(X_train)), shuffle=True, random_state=random_state)
    candidates = build_model_candidates()

    results = {}
    print("\n" + "=" * 60)
    print("MODEL COMPARISON (5-fold cross-validation on training set)")
    print("=" * 60)
    print(f"{'Model':<25} {'CV R2 (mean)':>12} {'CV R2 (std)':>12}")
    print("-" * 60)

    best_name, best_score, best_model = None, -np.inf, None
    for name, pipeline in candidates.items():
        scores = cross_val_score(pipeline, X_train, y_train, cv=kf, scoring="r2")
        mean_r2 = scores.mean()
        std_r2 = scores.std()
        results[name] = {"cv_r2_mean": mean_r2, "cv_r2_std": std_r2}
        print(f"{name:<25} {mean_r2:>12.4f} {std_r2:>12.4f}")
        if mean_r2 > best_score:
            best_score = mean_r2
            best_name = name
            best_model = pipeline

    print("-" * 60)
    print(f"Winner: {best_name} (CV R2 = {best_score:.4f})")

    # Fit winner on full training set
    best_model.fit(X_train, y_train)

    # Final evaluation on held-out test set
    metrics = evaluate_model(best_model, X_test, y_test)
    print("\n" + "=" * 60)
    print("FINAL TEST-SET EVALUATION")
    print("=" * 60)
    print(f"  R2   : {metrics['r2']:.4f}  (target: > 0.85)")
    print(f"  RMSE : {metrics['rmse']:.4f} ppm.hr")
    print(f"  MAE  : {metrics['mae']:.4f} ppm.hr")
    if metrics["r2"] < 0.85:
        print("  [WARN] R2 below target. Consider more calibration data or lower noise.")
    else:
        print("  [OK] R2 target met!")
    print("=" * 60)

    # Save model + metadata
    model_path = MODELS_DIR / "h2s_model.pkl"
    metadata = {
        "model_name": best_name,
        "features": available,
        "target": TARGET_COL,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "cv_r2": float(best_score),
        "test_r2": float(metrics["r2"]),
        "test_rmse": float(metrics["rmse"]),
        "test_mae": float(metrics["mae"]),
        "all_models": results,
    }
    joblib.dump({"model": best_model, "features": available, "metadata": metadata}, model_path)

    meta_path = MODELS_DIR / "h2s_model_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    log.info(f"Model saved: {model_path}")
    log.info(f"Metadata saved: {meta_path}")

    return {"model": best_model, "features": available, "metrics": metrics, "metadata": metadata}


def predict(image_features: dict, model_path: str = "models/h2s_model.pkl") -> dict:
    """
    Predict H2S cumulative dose from a StripReading features dict.

    This is the reference inference function (also the contract the future
    mobile app should mirror).

    Args:
        image_features: dict keyed like the dataset CSV columns. The easiest
            correct way to build it is ``StripReading.features_for_model()``,
            which handles the ``a``/``a_star`` naming difference. H must be in
            degrees [0, 360) and S/V in [0, 1] — see FEATURE_COLS.
        model_path: Path to saved model .pkl

    Returns:
        {"dose_ppm_hr": float, "confidence": str, "model": str}

    Raises:
        KeyError: if a required feature is absent, rather than letting pandas
            substitute NaN and return a silently meaningless dose.
        ValueError: if any engineered feature is non-finite.
    """
    payload = joblib.load(model_path)
    model = payload["model"]
    features = payload["features"]
    metadata = payload["metadata"]

    # Fail loudly on a malformed feature dict. Without this, a missing key
    # becomes NaN and the model still returns a number that looks plausible.
    missing = [f for f in FEATURE_COLS if f in features and f not in image_features]
    if missing:
        raise KeyError(
            f"predict() is missing required features: {missing}. "
            f"Build the dict with StripReading.features_for_model()."
        )

    # Engineer derived features
    df = pd.DataFrame([image_features])
    df = engineer_features(df)

    X = df[features].values
    if not np.all(np.isfinite(X)):
        bad = [f for f, v in zip(features, X[0]) if not np.isfinite(v)]
        raise ValueError(f"Non-finite value(s) in features: {bad}")

    dose = float(model.predict(X)[0])
    dose = max(0.0, dose)  # Clip negative predictions

    # Confidence label based on test R2
    test_r2 = metadata.get("test_r2", 0.0)
    conf = "high" if test_r2 >= 0.90 else ("medium" if test_r2 >= 0.75 else "low")

    return {
        "dose_ppm_hr": round(dose, 3),
        "confidence": conf,
        "model": metadata.get("model_name", "unknown"),
    }



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train H2S dose regression model.")
    parser.add_argument("--csv", default="./datasets/dataset.csv",
                        help="Path to labeled dataset CSV")
    parser.add_argument("--test_size", type=float, default=0.2)
    args = parser.parse_args()

    if not Path(args.csv).exists():
        print(f"Dataset not found: {args.csv}")
        print("Run demo_simulator.py first to generate a synthetic dataset for testing.")
        print("  python demo_simulator.py")
    else:
        train(args.csv, test_size=args.test_size)
