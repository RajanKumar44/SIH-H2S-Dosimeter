# SIH 2026 — H2S Dosimeter Wristband | AI-Based Quantitative Reading

> **Problem Statement**: SIH26118 — Passive Colorimetric H₂S Exposure-Dosimeter Wristband with AI-Based Quantitative Reading  
> **Team**: Dayananda Sagar College of Engineering (DSCE)  
> **Category**: Hardware + Software (Hybrid)

---

## Project Overview

An indigenous, low-cost, disposable wristband containing a chemically-reactive colorimetric strip (copper-acetate based) that darkens progressively with cumulative H₂S exposure. Paired with a smartphone application that photographs the strip alongside a printed reference color scale, applies AI-based color correction for ambient lighting, and quantifies the cumulative exposure dose.

Worker identity, shift data, and exposure history are logged to a cloud dashboard for occupational health compliance reporting (DGMS / OISD standards).

---

## Repository Structure

`
SIH-H2S-Dosimeter/
├── software/
│   ├── ml_pipeline/          # Phase 1 — ML Pipeline Core (COMPLETE)
│   │   ├── image_processor.py      # RGB→Lab, CIE DE2000 ΔE, ROI detection
│   │   ├── dataset_builder.py      # Batch strip photos → labeled CSV
│   │   ├── model_trainer.py        # Multi-model training + best selector
│   │   ├── model_evaluator.py      # Diagnostic plots + calibration curve
│   │   ├── demo_simulator.py       # End-to-end synthetic test (no hardware needed)
│   │   ├── env_compensation.py     # Environmental correction (ZIP dataset)
│   │   └── requirements.txt
│   │
│   ├── backend/              # Phase 2 — FastAPI Backend (Upcoming)
│   ├── dashboard/            # Phase 3 — React Admin Dashboard (Upcoming)
│   └── mobile_app/           # Phase 4 — Flutter Mobile App (Upcoming)
│
└── docs/
    ├── architecture.md
    └── dgms_compliance.md
`

---

## Phase Status

| Phase | Component | Status |
|-------|-----------|--------|
| **1** | ML Pipeline (image processing + model training) | ✅ **COMPLETE** |
| **2** | Backend API (FastAPI + PostgreSQL) | 🔄 Next |
| **3** | Admin Dashboard (React + Chart.js) | 📋 Planned |
| **4** | Mobile App (Flutter + TFLite) | 📋 Planned |

---

## Phase 1 — ML Pipeline Results

| Metric | Value |
|--------|-------|
| **Test R²** | **0.8630** ✅ (target > 0.85) |
| **RMSE** | 11.37 ppm·hr |
| **MAE** | 8.89 ppm·hr |
| **Best Model** | RandomForest (CV R² = 0.9152) |
| **deltaE** | CIE DE2000 (from ACS research paper se3c02793) |

### Run the end-to-end test (no hardware needed):
`ash
cd software/ml_pipeline
pip install -r requirements.txt
python image_processor.py        # Math self-test (RGB→Lab, ΔE)
python demo_simulator.py         # Full synthetic pipeline test
python model_evaluator.py        # Diagnostic plots
`

---

## System Architecture

`
Worker wears wristband
        │
        ▼
Copper-acetate strip darkens with H2S exposure
        │ (Phone camera captures image)
        ▼
Smartphone App
  ├── ROI Detection (OpenCV)
  ├── RGB -> CIE L*a*b* Conversion (ACS paper formulas)
  ├── CIE DE2000 deltaE calculation
  ├── Reference card normalization (lighting correction)
  └── ML Regression → Cumulative Dose (ppm·hr)
        │ (API call)
        ▼
Cloud Backend (FastAPI)
  ├── Worker database
  ├── Exposure logging
  ├── DGMS threshold alerts (> 80 ppm·hr)
  └── Compliance report generation
        │
        ▼
Admin Dashboard (React)
  ├── Worker exposure heatmap
  ├── Time-series charts
  └── PDF compliance reports
`

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Image Processing | Python, OpenCV, NumPy |
| ML Model | scikit-learn (RandomForest / GBM) |
| Color Science | CIE L*a*b*, CIE DE2000 (ACS paper) |
| Backend | FastAPI, SQLAlchemy, PostgreSQL |
| Dashboard | React, Vite, Chart.js |
| Mobile App | Flutter, TFLite |
| Cloud | Firebase / Railway (free tier) |

---

## Key Science

The colorimetric detection uses the reaction:
`
Cu(CH3COO)2  +  H2S  →  CuS (grey-brown)  +  2 CH3COOH
Copper acetate  + H2S → Copper sulfide (dark)  + Acetic acid
`

Color quantification uses **CIE DE2000** (ΔE) — the international standard for perceptual color difference — implemented using the exact matrix formulas from:
> *"Deep learning-assisted colorimetric/electrical dual-sensing system for ultra-fast detection of hydrogen sulfide"* — ACS Journal (se3c02793)

---

## DGMS Compliance

| Standard | Limit |
|----------|-------|
| TWA (8-hour) | 10 ppm |
| STEL (15-min) | 15 ppm |
| Alert threshold | **80 ppm·hr** cumulative dose |
| Danger threshold | **100 ppm·hr** cumulative dose |

---

## Team
**College**: Dayananda Sagar College of Engineering (DSCE)  
**Competition**: Smart India Hackathon 2026  
**Problem Statement**: SIH26118
