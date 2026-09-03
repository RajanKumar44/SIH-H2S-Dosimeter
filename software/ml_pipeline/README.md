# ML Pipeline

Colour science and dose regression for the H₂S colorimetric dosimeter: turns a strip photograph into a
cumulative exposure dose in **ppm·hr**.

This component is standalone — it does not import from the backend, and the backend does not import from it.
The contract between them is the JSON body of `POST /readings/`. See the [root README](../../README.md) for the
full system architecture.

## Quick start

```bash
pip install -r requirements.txt

python image_processor.py      # colour-math self-test, no data required
python demo_simulator.py       # synthetic dataset -> train -> save model + calibration plot
python model_evaluator.py      # diagnostic plots (run demo_simulator.py first)
```

`models/`, `datasets/` and `results/` ship empty and are git-ignored, so **`demo_simulator.py` must be run at
least once** before `model_evaluator.py` or `predict()` will work.

## Files

| File | Role |
|------|------|
| `image_processor.py` | sRGB → XYZ → CIE L\*a\*b\*, **CIE ΔE2000**, ROI detection (OpenCV/HSV), reference-card lighting correction. Run directly for a self-test. |
| `dataset_builder.py` | Batch-processes a folder of labelled strip photos into `datasets/dataset.csv`. |
| `model_trainer.py` | Compares 5 regressors by cross-validated R², saves the best to `models/h2s_model.pkl` plus a metadata JSON. Exposes `predict(features)` — the reference inference function for the mobile app. |
| `model_evaluator.py` | Residual, calibration and feature-importance plots into `results/`. |
| `demo_simulator.py` | Generates a synthetic dataset, trains, and plots. Primary end-to-end test when no real strip data exists. |
| `env_compensation.py` | Trains a temperature/humidity correction model. **Requires a large local IoT archive that is not in this repository.** |
| `live_ai_demonstrator.py` | Narrated walkthrough of the chemistry, colour maths and inference. Optionally POSTs a reading to a running backend. |

## Working with real strip photos

```bash
# name files as P001_5ppm_30min.jpg, or supply a labels.json
python dataset_builder.py --images_dir ./sample_images --output datasets/dataset.csv
python model_trainer.py --csv datasets/dataset.csv
python model_evaluator.py
```

`sample_images/` is currently **empty** — no real strip photographs have been collected yet, so every result to
date comes from the synthetic simulator.

## Model performance

Representative `demo_simulator.py` run on synthetic data:

| Metric | Value |
|--------|-------|
| Test R² | 0.8630 (target: > 0.85) |
| RMSE | 11.37 ppm·hr |
| MAE | 8.89 ppm·hr |
| Selected model | RandomForest (CV R² 0.9152) |

**Not reproducible run-to-run.** `simulate_strip_color()` uses an unseeded RNG and the dose array is shuffled
with an unseeded global shuffle, so each run yields a different dataset. Observed spread across recent runs was
roughly **R² 0.89–0.93**, with the winner alternating between RandomForest and PolyRidge_deg2. Quote your own run
rather than this table. `model_trainer.py` prints a `[WARN]` if test R² drops below 0.85.

Real-world accuracy is unknown until strip photographs are collected.

## Conventions

- **Colour science is paper-derived.** The RGB→Lab matrices and ΔE2000 implementation follow ACS paper
  *se3c02793*. `BASELINE_LAB` and `REFERENCE_PATCHES_LAB` in `image_processor.py` are calibration constants —
  changing them is a recalibration, not a refactor.
- **Windows UTF-8 guard.** CLI entry points begin with `sys.stdout.reconfigure(encoding='utf-8', ...)`. Keep this
  in any new script; the project is also run on Windows machines.
- **Do not commit generated artefacts.** `models/*.pkl`, `datasets/*.csv` and `results/*.png` are git-ignored and
  regenerated via `demo_simulator.py`.
