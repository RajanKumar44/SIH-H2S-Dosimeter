# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

**SIH26118** — Passive Colorimetric H₂S Exposure-Dosimeter Wristband with AI-Based Quantitative Reading.
Smart India Hackathon 2026 entry, team **DSCE** (Dayananda Sagar College of Engineering). Hybrid hardware + software.

A disposable wristband holds a copper-acetate colorimetric strip that darkens with cumulative H₂S exposure
(`Cu(CH₃COO)₂ + H₂S → CuS + 2 CH₃COOH`). A phone photographs the strip next to a printed reference color card;
software applies lighting correction and an ML regression to quantify the **cumulative dose in ppm·hr**. Worker
exposure is logged to a backend and surfaced on an admin dashboard for DGMS/OISD occupational-safety compliance.

## Architecture

All code lives under `software/`. The three built components are **independent processes** that communicate over HTTP/JSON:

```
Phone (strip photo)                    software/ml_pipeline/  (Python, standalone)
  └─ ROI detect → RGB→Lab → ΔE2000 → lighting correct → ML predict → dose_ppm_hr
                                            │  (this pipeline is intended to run ON the mobile app;
                                            │   model_trainer.predict() is the reference inference fn)
                                            ▼  POST /readings/  {worker_id, delta_E, dose_ppm_hr, ...}
software/backend/  (FastAPI + SQLAlchemy)
  ├─ stores reading, auto-creates threshold alerts
  └─ serves /dashboard/summary, /reports/... , /workers/..., /alerts/...
                                            ▲  fetch()  (VITE_API_BASE, default http://localhost:8000)
software/dashboard/  (React 19 + Vite + Chart.js)
```

**Key architectural fact:** the backend does **not** run the ML model or OpenCV — it receives the already-computed
`dose_ppm_hr` from the client and only stores/aggregates/alerts. Keep the ML pipeline and the backend decoupled;
do not add `scikit-learn`/`opencv` to the backend.

### Components

| Dir | Stack | Role |
|-----|-------|------|
| `software/ml_pipeline/` | Python, OpenCV, NumPy, scikit-learn, pandas, matplotlib | Color science + dose regression. Trains `models/h2s_model.pkl`. |
| `software/backend/` | FastAPI, SQLAlchemy 2.0, SQLite(dev)/PostgreSQL(prod), JWT (bcrypt + python-jose), reportlab | REST API, DB, PDF reports, alerting. |
| `software/dashboard/` | React 19, Vite 8, Chart.js, react-chartjs-2 | Admin SPA (login, dashboard, workers, submit reading, alerts, reports). |
| `software/mobile_app/` | Flutter + TFLite (**not yet created** — only referenced in `.gitignore`) | Phase 4, planned. |

### ML pipeline files (`software/ml_pipeline/`)
- `image_processor.py` — sRGB→XYZ→CIE L\*a\*b\*, **CIE ΔE2000**, ROI detection (OpenCV/HSV), reference-card lighting correction. `python image_processor.py` runs a math self-test.
- `demo_simulator.py` — **primary end-to-end test**: generates a synthetic dataset, trains, saves model + plots. Run this when there's no real strip data.
- `dataset_builder.py` — turns a folder of labeled strip photos into `datasets/dataset.csv`.
- `model_trainer.py` — compares 5 models by CV R², saves best to `models/h2s_model.pkl` + metadata JSON. Exposes `predict(features)` (the mobile-app reference inference fn).
- `model_evaluator.py` — diagnostic plots / calibration curve into `results/`.
- `env_compensation.py` — trains a temp/humidity correction model from a large local IoT dataset (`archive.zip`, git-ignored, not in repo).

### Backend (`software/backend/`)
- `main.py` — app entry, CORS, router wiring, `/auth/login`, `/auth/me`, `/health`; **lifespan** handler (not the deprecated `on_event`) creates the default `admin` on startup.
- `config.py` — **centralized env config**: `APP_ENV`, `SECRET_KEY`, `JWT_ALGORITHM`, `TOKEN_EXPIRE_MINUTES`, `DATABASE_URL`, `CORS_ORIGINS`. Fails fast in production if `SECRET_KEY` is unset.
- `database.py` — engine/session; `DATABASE_URL` comes from `config.py`.
- `models.py` — ORM: `SafetyOfficer`, `Worker`, `Reading`, `Alert` (`Alert.worker_code`/`worker_name` properties expose the linked worker).
- `schemas.py` — Pydantic v2 request/response models.
- `auth.py` — bcrypt hashing, JWT create/decode (secret/alg from `config.py`), `get_current_officer` (→401) / `require_admin` (→403) deps.
- `routes/` — `workers`, `readings`, `alerts`, `reports`, `dashboard` (all router-level auth-guarded).
- `seed.py` — **wipes** and re-seeds demo data. `test_api.py` — stdlib HTTP integration tests (needs a running server **and** `python-jose`/`bcrypt`/`reportlab` installed). `test_offline_checks.py` — offline dashboard-refactor + alert-serialization checks (no server, no extra deps).

## Commands

### ML pipeline
```bash
cd software/ml_pipeline
pip install -r requirements.txt
python image_processor.py     # math self-test (no data needed)
python demo_simulator.py      # generate synthetic data → train → save model + plots
python model_evaluator.py     # diagnostic plots (needs a trained model/dataset)
python model_trainer.py --csv datasets/dataset.csv    # train on a specific CSV
```

### Backend
```bash
cd software/backend
pip install -r requirements.txt
uvicorn main:app --reload     # → http://localhost:8000  (Swagger UI at /docs)
python seed.py                # WIPES DB, loads demo workers/readings/alerts
python test_api.py            # integration tests — server must already be running
```
Default login: **`admin` / `admin123`** (also `officer1` / `officer123` after seeding).

### Dashboard
```bash
cd software/dashboard
npm install
npm run dev       # Vite dev server (default http://localhost:5173)
npm run build     # production build
npm run lint      # oxlint
```
The dashboard reads the backend URL from `VITE_API_BASE` (defaults to `http://localhost:8000`; see `.env.example`). Run backend + dashboard together.

## Conventions & rules

- **DGMS dose thresholds (ppm·hr):** `WARNING = 60`, `DANGER = 80`, `CRITICAL = 100`. These are currently
  **duplicated** as module constants in `routes/readings.py`, `routes/dashboard.py`, and `seed.py` — change all of them together.
- **Color science is paper-derived.** RGB→Lab and ΔE2000 formulas follow ACS paper *se3c02793*. `BASELINE_LAB` and
  `REFERENCE_PATCHES_LAB` in `image_processor.py` are calibration constants — treat changes as recalibration, not refactors.
- **R² target is > 0.85.** If a change drops test R² below target, `model_trainer.py` prints a `[WARN]`. Note that
  `demo_simulator.py` is **not reproducible run-to-run** — `simulate_strip_color()` uses an unseeded RNG and the dose
  array is shuffled with an unseeded global shuffle, so R² varies (observed ≈0.89–0.93) and the winning model
  alternates between RandomForest and PolyRidge_deg2. Quote the run you actually performed, not a fixed figure.
- **Windows UTF-8 guard:** Python entry-point scripts start with `sys.stdout.reconfigure(encoding='utf-8', ...)`. Keep this in new CLI scripts (the app runs on Windows machines too).
- **Config via env vars** — backend config is centralized in `config.py` and documented in `software/backend/.env.example`: `APP_ENV`, `SECRET_KEY`, `JWT_ALGORITHM`, `TOKEN_EXPIRE_MINUTES`, `DATABASE_URL`, `CORS_ORIGINS`. Defaults are **dev-only**; when `APP_ENV=production` the app **refuses to start** unless `SECRET_KEY` is set (no insecure fallback in prod). The dashboard uses `VITE_API_BASE` (see `software/dashboard/.env.example`).
- **Do not commit** secrets (`.env`), databases (`*.db`), trained models (`*.pkl`), generated datasets/plots (`*.csv`, `results/*.png`), or the large `archive.zip`. All are git-ignored; models/datasets are regenerated via `demo_simulator.py`.
- **JS/React:** JSX, ES modules, React 19, function components + hooks. Routing is **manual hash-based** in `App.jsx` (not react-router, despite it being a dependency). Lint with oxlint (config in `.oxlintrc.json`).

## Known state / caveats

- **Auth model (enforced).** Safety officers/admins are the only login accounts; **workers are data subjects, not user accounts** (so there is no per-worker login/IDOR surface). All data endpoints — `/workers`, `/readings`, `/alerts`, `/reports`, `/dashboard` — require a valid JWT via a **router-level** `Depends(get_current_officer)` (→401). Worker-roster **mutations** (`POST`/`PUT`/`DELETE /workers/...`) additionally require the **admin** role via `require_admin` (→403). Public endpoints: `/`, `/health`, `POST /auth/login`, and Swagger `/docs`.
- **CORS** is restricted to `CORS_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173`), **not** `*`. Set it to the deployed dashboard origin in production.
- **PDF report download** must be an authenticated `fetch` (Authorization header) that streams the response to a Blob — a plain `window.open()` would drop the JWT. The dashboard's `downloadPdf` in `src/api.js` does this and handles 401/403.
- **Docs are current** as of the documentation-cleanup commit: root `README.md`, `software/README.md`,
  `software/ml_pipeline/README.md` and `software/dashboard/README.md` all describe the shipped state. There is no
  `docs/` directory and no reference to one. Keep them in step with the code, and prefer git history when in doubt.
- **No frontend test suite.** The dashboard has no test runner; verification is `npm run build`, `npm run lint`
  (0 errors, 6 pre-existing warnings) plus manual browser checks. Only the backend has automated tests.
- **No DB migrations.** Schema comes from `create_all()` at startup, so an existing SQLite file will not gain new
  columns after a model change — delete it or re-run `seed.py`.
- `mobile_app/` does not exist yet — only `.gitignore` entries anticipate it.

## Roadmap

| Phase | Component | Status |
|-------|-----------|--------|
| 1 | ML pipeline (image processing + dose regression) | ✅ Complete — synthetic-data R² ≈0.89–0.93 (see caveat above); no real strip photos yet |
| 2 | Backend API (FastAPI + DB + JWT + PDF reports) | ✅ Complete — 49/49 `test_api.py`, 16/16 `test_offline_checks.py` |
| 3 | Admin dashboard (React + Chart.js) | ✅ Complete — login, dashboard, workers, submit reading, alerts, reports |
| 4 | Mobile app (Flutter + on-device TFLite inference) | 📋 Not started — largest remaining piece |

Also genuinely missing, verified against the tree: real strip-photo dataset (`sample_images/` is empty);
`env_compensation` output is not wired into the dose path; no Dockerfile/CI/CD; no Alembic migrations; no frontend
test runner; worker edit/deactivate exists in the API but not the dashboard UI; `POST /auth/login` is unthrottled.

Likely next work: build the Flutter app (Phase 4), set a production `SECRET_KEY`/`CORS_ORIGINS` and migrate to PostgreSQL,
and wire `env_compensation` output into the on-device prediction path.
