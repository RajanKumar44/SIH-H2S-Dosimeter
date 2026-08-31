"""
env_compensation.py
===================
Trains an environmental compensation model using the ZIP dataset.

The real-world dataset (archive.zip) contains 12.7M IoT sensor readings with:
  H2S_ppm, temperature, humidity, CO2, pressure, PM2.5, etc.

This module trains a model to predict: given temperature + humidity,
what is the expected offset/correction factor for H2S readings?

This compensation model improves accuracy of the colorimetric strip reading
when the phone app detects ambient environmental conditions.

Usage:
  python env_compensation.py --zip "../../archive (1).zip"
  python env_compensation.py --zip "../../archive (1).zip" --max_rows 100000
"""

import argparse
import json
import logging
import zipfile
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_squared_error
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

MODELS_DIR = Path("models")
RESULTS_DIR = Path("results")
MODELS_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)


def load_zip_dataset(zip_path: str, max_rows: int = 200_000) -> pd.DataFrame:
    """
    Load H2S readings from the archive zip (AEOLUS MQTT dataset).
    Extracts relevant columns and drops nulls.
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"Dataset zip not found: {zip_path}")

    log.info(f"Loading dataset from {zip_path} (max {max_rows:,} rows)...")

    KEEP_COLS = ["time", "H2S_ppm", "temperature", "humidity",
                 "bme_temp", "bme_humi", "bme_pressure",
                 "CO2_ppm", "CH4", "AirQ", "device_id", "room_id"]

    all_dfs = []
    total_loaded = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        for fname in sorted(zf.namelist()):
            if total_loaded >= max_rows:
                break
            raw = json.loads(zf.read(fname))
            cols = raw["columns"]
            vals = raw["values"]

            # Map available columns
            available = {c: i for i, c in enumerate(cols) if c in KEEP_COLS}
            if "H2S_ppm" not in available:
                continue

            rows = []
            for v in vals:
                row = {}
                for col, idx in available.items():
                    row[col] = v[idx] if idx < len(v) else None
                rows.append(row)

            df = pd.DataFrame(rows)
            # Keep only rows with H2S reading
            df = df[df["H2S_ppm"].notna()].copy()
            if len(df) == 0:
                continue

            all_dfs.append(df)
            total_loaded += len(df)
            log.info(f"  {fname}: {len(df):,} H2S rows (total: {total_loaded:,})")

            if total_loaded >= max_rows:
                break

    if not all_dfs:
        raise ValueError("No H2S data found in the zip file.")

    df = pd.concat(all_dfs, ignore_index=True)

    # Use bme_temp/humidity if temperature/humidity is missing
    if "temperature" in df.columns and "bme_temp" in df.columns:
        df["temperature"] = df["temperature"].fillna(df["bme_temp"])
    if "humidity" in df.columns and "bme_humi" in df.columns:
        df["humidity"] = df["humidity"].fillna(df["bme_humi"])

    df = df.dropna(subset=["H2S_ppm", "temperature", "humidity"])
    df["H2S_ppm"] = pd.to_numeric(df["H2S_ppm"], errors="coerce")
    df["temperature"] = pd.to_numeric(df["temperature"], errors="coerce")
    df["humidity"] = pd.to_numeric(df["humidity"], errors="coerce")
    df = df.dropna(subset=["H2S_ppm", "temperature", "humidity"])

    # Remove outliers
    q99 = df["H2S_ppm"].quantile(0.99)
    df = df[df["H2S_ppm"] <= q99]
    df = df[df["H2S_ppm"] >= 0]

    log.info(f"Final dataset: {len(df):,} rows | H2S: {df['H2S_ppm'].min():.3f} - {df['H2S_ppm'].max():.3f} ppm")
    return df.reset_index(drop=True)


def train_compensation_model(df: pd.DataFrame) -> dict:
    """
    Train a model: temperature + humidity -> H2S baseline offset.

    We model: H2S_ppm = f(temperature, humidity) + noise
    This captures how ambient conditions affect sensor readings,
    which we use to correct colorimetric readings taken in the field.
    """
    features = []
    for col in ["temperature", "humidity", "bme_pressure", "CO2_ppm"]:
        if col in df.columns and df[col].notna().sum() > 100:
            features.append(col)

    log.info(f"Compensation features: {features}")

    df = df[features + ["H2S_ppm"]].dropna()
    X = df[features].values
    y = df["H2S_ppm"].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("model", GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42
        )),
    ])
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    rmse = np.sqrt(mean_squared_error(y_test, y_pred))

    log.info(f"Compensation model: R²={r2:.4f} RMSE={rmse:.4f} ppm")
    return {"model": model, "features": features, "r2": r2, "rmse": rmse}


def save_and_plot(result: dict, df: pd.DataFrame):
    """Save the compensation model and generate summary plots."""
    # Save model
    model_path = MODELS_DIR / "env_compensation_model.pkl"
    joblib.dump({
        "model": result["model"],
        "features": result["features"],
        "metadata": {"r2": result["r2"], "rmse": result["rmse"]},
    }, model_path)

    meta_path = MODELS_DIR / "env_compensation_metadata.json"
    with open(meta_path, "w") as f:
        json.dump({
            "features": result["features"],
            "r2": result["r2"],
            "rmse": result["rmse"],
        }, f, indent=2)

    log.info(f"Compensation model saved: {model_path}")

    # Plot
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("Environmental Compensation Model (AEOLUS Dataset)", fontsize=12, fontweight="bold")

    # Temp vs H2S
    sample = df.sample(min(5000, len(df)), random_state=42)
    axes[0].scatter(sample["temperature"], sample["H2S_ppm"], alpha=0.3, s=5)
    axes[0].set_xlabel("Temperature (°C)")
    axes[0].set_ylabel("H2S (ppm)")
    axes[0].set_title("Temperature vs H2S")
    axes[0].grid(alpha=0.3)

    # Humidity vs H2S
    axes[1].scatter(sample["humidity"], sample["H2S_ppm"], alpha=0.3, s=5, color="orange")
    axes[1].set_xlabel("Humidity (%)")
    axes[1].set_ylabel("H2S (ppm)")
    axes[1].set_title("Humidity vs H2S")
    axes[1].grid(alpha=0.3)

    # H2S distribution
    axes[2].hist(df["H2S_ppm"], bins=50, edgecolor="black", alpha=0.8, color="steelblue")
    axes[2].set_xlabel("H2S (ppm)")
    axes[2].set_ylabel("Count")
    axes[2].set_title(f"H2S Distribution\n({len(df):,} readings)")
    axes[2].grid(alpha=0.3)

    out_path = RESULTS_DIR / "env_compensation_analysis.png"
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"Analysis plot saved: {out_path}")

    print("\n" + "=" * 55)
    print("ENVIRONMENTAL COMPENSATION MODEL")
    print("=" * 55)
    print(f"  Features : {result['features']}")
    print(f"  R²       : {result['r2']:.4f}")
    print(f"  RMSE     : {result['rmse']:.4f} ppm")
    print(f"  Model    : {model_path}")
    print(f"  Plot     : {out_path}")
    print("=" * 55)


def predict_compensation(
    temperature: float,
    humidity: float,
    model_path: str = "models/env_compensation_model.pkl",
) -> float:
    """
    Predict the H2S baseline offset for given environmental conditions.
    Returns the expected ambient H2S noise level to subtract from readings.
    """
    payload = joblib.load(model_path)
    model = payload["model"]
    features = payload["features"]

    values = {"temperature": temperature, "humidity": humidity,
               "bme_pressure": 1013.25, "CO2_ppm": 400.0}
    X = np.array([[values.get(f, 0.0) for f in features]])
    return float(model.predict(X)[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Train environmental compensation model from ZIP dataset."
    )
    parser.add_argument(
        "--zip",
        default="../../archive (1).zip",
        help="Path to the AEOLUS dataset ZIP file"
    )
    parser.add_argument(
        "--max_rows", type=int, default=200_000,
        help="Max H2S rows to load (default: 200000)"
    )
    args = parser.parse_args()

    try:
        df = load_zip_dataset(args.zip, max_rows=args.max_rows)
        result = train_compensation_model(df)
        save_and_plot(result, df)
    except FileNotFoundError as e:
        print(f"\n{e}")
        print("Place the archive zip at the default path or pass --zip <path>")
