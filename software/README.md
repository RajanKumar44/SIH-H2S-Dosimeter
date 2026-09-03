# Software Components

Three independent components that communicate over HTTP/JSON. See the [root README](../README.md) for the full
architecture, API surface, configuration reference and setup instructions.

| # | Component | Directory | Stack | Status |
|---|-----------|-----------|-------|--------|
| 1 | ML pipeline | [`ml_pipeline/`](ml_pipeline/) | Python, OpenCV, NumPy, scikit-learn, pandas, matplotlib | Complete |
| 2 | Backend API | [`backend/`](backend/) | FastAPI, SQLAlchemy 2.0, Pydantic v2, JWT, ReportLab | Complete — 49/49 API tests, 16/16 offline checks |
| 3 | Admin dashboard | [`dashboard/`](dashboard/) | React 19, Vite 8, Chart.js, oxlint | Complete — login, dashboard, workers, submit reading, alerts, reports |
| 4 | Mobile app | — | Flutter, TFLite | **Not started** — directory does not exist yet |

## What each component does

**`ml_pipeline/`** — Converts a strip photograph into a cumulative dose. Detects the strip ROI, converts
sRGB → CIE L\*a\*b\*, computes CIE ΔE2000 against a fresh-strip baseline, applies reference-card lighting
correction, and runs a regression to predict `dose_ppm_hr`. Standalone: it does not import from the backend.

**`backend/`** — Stores readings, evaluates the DGMS thresholds (60 / 80 / 100 ppm·hr), auto-creates alerts, and
serves the roster, alert, report and dashboard-summary endpoints. JWT-authenticated, with admin-only worker
mutations. **It does not run the ML model or OpenCV** — it receives an already-computed `dose_ppm_hr`.

**`dashboard/`** — Admin SPA for safety officers: login, exposure overview, worker roster, reading submission,
alert acknowledgement, and DGMS reports with authenticated PDF download.

## Quick start

```bash
# terminal 1 — backend
cd backend && pip install -r requirements.txt && uvicorn main:app --reload

# terminal 2 — dashboard
cd dashboard && npm install && npm run dev

# terminal 3 — ML pipeline (standalone)
cd ml_pipeline && pip install -r requirements.txt && python demo_simulator.py
```

Backend on `http://localhost:8000` (Swagger UI at `/docs`), dashboard on `http://localhost:5173`.
Dev login: `admin` / `admin123`.

Copy `backend/.env.example` and `dashboard/.env.example` to `.env` before changing any configuration. Never
commit a `.env`; production requires a real `SECRET_KEY`.
