# ML Pipeline - Phase 1

Core image processing and machine learning pipeline for the H2S colorimetric dosimeter.

## Quick Start
```bash
pip install -r requirements.txt
python image_processor.py   # Math self-test
python demo_simulator.py    # Full end-to-end synthetic test
```

## Phase 1 Results
- R2 = 0.8630 (PASSED, target > 0.85)
- Best model: RandomForest (CV R2 = 0.9152)
- RMSE = 11.37 ppm.hr
