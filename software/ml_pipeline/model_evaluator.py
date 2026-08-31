"""
model_evaluator.py
==================
Evaluates a trained model: residual plots, calibration curve, feature importance.
Run after model_trainer.py to get diagnostic charts.

Usage:
  python model_evaluator.py
  python model_evaluator.py --csv datasets/dataset.csv --model models/h2s_model.pkl
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server / headless
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

from sklearn.model_selection import cross_val_predict, KFold
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

from model_trainer import engineer_features

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)


def evaluate_and_plot(
    csv_path: str = "./datasets/dataset.csv",
    model_path: str = "./models/h2s_model.pkl",
):
    """Load dataset and model, run full evaluation, save diagnostic plots."""

    df = pd.read_csv(csv_path)
    df = engineer_features(df)

    payload = joblib.load(model_path)
    model = payload["model"]
    features = payload["features"]
    metadata = payload["metadata"]

    X = df[features].values
    y = df["cumulative_dose_ppm_hr"].values

    # Cross-validated predictions for unbiased evaluation
    kf = KFold(n_splits=min(5, len(X)), shuffle=True, random_state=42)
    y_cv_pred = cross_val_predict(model, X, y, cv=kf)

    r2 = r2_score(y, y_cv_pred)
    rmse = np.sqrt(mean_squared_error(y, y_cv_pred))
    mae = mean_absolute_error(y, y_cv_pred)
    residuals = y - y_cv_pred

    print("\n" + "=" * 55)
    print("MODEL EVALUATION (Cross-validated)")
    print("=" * 55)
    print(f"  Model    : {metadata.get('model_name', 'unknown')}")
    print(f"  Samples  : {len(y)}")
    print(f"  R²       : {r2:.4f}")
    print(f"  RMSE     : {rmse:.4f} ppm.hr")
    print(f"  MAE      : {mae:.4f} ppm.hr")
    print("=" * 55)

    # ---- Plots ----
    fig = plt.figure(figsize=(16, 10))
    fig.suptitle(
        f"H₂S Dose Model Evaluation — {metadata.get('model_name', '')}\n"
        f"R²={r2:.4f}  RMSE={rmse:.4f}  MAE={mae:.4f}",
        fontsize=13, fontweight="bold"
    )
    gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.4, wspace=0.35)

    # 1. Predicted vs Actual
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.scatter(y, y_cv_pred, alpha=0.7, edgecolors="k", linewidths=0.4, s=50)
    lims = [min(y.min(), y_cv_pred.min()), max(y.max(), y_cv_pred.max())]
    ax1.plot(lims, lims, "r--", linewidth=1.5, label="Perfect prediction")
    ax1.set_xlabel("Actual Dose (ppm·hr)")
    ax1.set_ylabel("Predicted Dose (ppm·hr)")
    ax1.set_title("Predicted vs Actual")
    ax1.legend(fontsize=8)
    ax1.text(0.05, 0.92, f"R²={r2:.3f}", transform=ax1.transAxes, fontsize=10)

    # 2. Residuals vs Predicted
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.scatter(y_cv_pred, residuals, alpha=0.7, edgecolors="k", linewidths=0.4, s=50)
    ax2.axhline(0, color="red", linestyle="--", linewidth=1.5)
    ax2.set_xlabel("Predicted Dose (ppm·hr)")
    ax2.set_ylabel("Residual (Actual - Predicted)")
    ax2.set_title("Residuals")

    # 3. Residual distribution
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.hist(residuals, bins=20, edgecolor="black", alpha=0.8, color="steelblue")
    ax3.axvline(0, color="red", linestyle="--")
    ax3.set_xlabel("Residual (ppm·hr)")
    ax3.set_ylabel("Count")
    ax3.set_title("Residual Distribution")

    # 4. deltaE vs Dose scatter (scientific insight)
    ax4 = fig.add_subplot(gs[1, 0])
    delta_e_col = "delta_E_corr" if "delta_E_corr" in df.columns else "delta_E"
    ax4.scatter(df[delta_e_col], y, alpha=0.7, edgecolors="k", linewidths=0.4, s=50)
    ax4.set_xlabel("ΔE (CIE DE2000)")
    ax4.set_ylabel("Dose (ppm·hr)")
    ax4.set_title("ΔE vs Cumulative Dose")
    # Fit a quick polynomial trendline
    try:
        z = np.polyfit(df[delta_e_col], y, 2)
        p = np.poly1d(z)
        xs = np.linspace(df[delta_e_col].min(), df[delta_e_col].max(), 100)
        ax4.plot(xs, p(xs), "r-", linewidth=2, label="poly fit")
        ax4.legend(fontsize=8)
    except Exception:
        pass

    # 5. Error percentage distribution
    ax5 = fig.add_subplot(gs[1, 1])
    pct_error = np.abs(residuals) / (np.abs(y) + 1e-6) * 100
    ax5.hist(pct_error, bins=20, edgecolor="black", alpha=0.8, color="coral")
    ax5.axvline(15, color="green", linestyle="--", label="15% threshold")
    ax5.set_xlabel("Absolute % Error")
    ax5.set_ylabel("Count")
    ax5.set_title("Error Distribution")
    ax5.legend(fontsize=8)
    within_15 = (pct_error < 15).mean() * 100
    ax5.text(0.55, 0.92, f"{within_15:.1f}% within 15%",
             transform=ax5.transAxes, fontsize=9,
             bbox=dict(boxstyle="round", facecolor="white", alpha=0.7))

    # 6. Feature importance (if GBM/RF) or coefficient magnitude (if linear)
    ax6 = fig.add_subplot(gs[1, 2])
    try:
        if hasattr(model.named_steps.get("model", None), "feature_importances_"):
            # Tree-based model
            importances = model.named_steps["model"].feature_importances_
            # Features may be expanded by PolyFeatures; use first N
            n = min(len(features), len(importances))
            idx = np.argsort(importances[:n])[-10:]
            ax6.barh([features[i] for i in idx], importances[idx], color="steelblue")
            ax6.set_title("Feature Importance")
        else:
            # Show correlation of each feature with target
            corrs = [abs(np.corrcoef(df[f], y)[0, 1]) for f in features if f in df.columns]
            feat_names = [f for f in features if f in df.columns]
            idx = np.argsort(corrs)[-10:]
            ax6.barh([feat_names[i] for i in idx], [corrs[i] for i in idx], color="steelblue")
            ax6.set_title("Feature-Target Correlation")
    except Exception as e:
        ax6.text(0.3, 0.5, f"Not available:\n{e}", transform=ax6.transAxes)
        ax6.set_title("Feature Importance")

    out_path = RESULTS_DIR / "model_evaluation.png"
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"Evaluation plots saved: {out_path}")
    print(f"\n  Plots saved to: {out_path}")
    print(f"  Samples within 15% error: {within_15:.1f}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate trained H2S model.")
    parser.add_argument("--csv", default="./datasets/dataset.csv")
    parser.add_argument("--model", default="./models/h2s_model.pkl")
    args = parser.parse_args()

    if not Path(args.csv).exists() or not Path(args.model).exists():
        print("Run demo_simulator.py first to create dataset + model:")
        print("  python demo_simulator.py")
    else:
        evaluate_and_plot(args.csv, args.model)
