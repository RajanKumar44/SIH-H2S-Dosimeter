# SIH 2026 — H₂S Dosimeter Wristband | AI-Based Quantitative Reading

> **Problem Statement**: SIH26118 — Passive Colorimetric H₂S Exposure-Dosimeter Wristband with AI-Based Quantitative Reading
> **Team**: Dayananda Sagar College of Engineering (DSCE)
> **Category**: Hardware + Software (Hybrid)

---

## Project Overview

A low-cost, disposable wristband carrying a copper-acetate colorimetric strip that darkens progressively with
cumulative H₂S exposure. A phone photographs the strip next to a printed reference colour card; software applies
lighting correction and an ML regression to quantify the **cumulative dose in ppm·hr**.

Worker identity, shift data and exposure history are logged to a backend and surfaced on an admin dashboard for
occupational-health compliance reporting (DGMS / OISD).

The detection chemistry:

```
Cu(CH3COO)2  +  H2S  ->  CuS (grey-brown)  +  2 CH3COOH
copper acetate + H2S -> copper sulfide (dark) + acetic acid
```

Colour change is quantified with **CIE ΔE2000**, the international standard for perceptual colour difference,
implemented from the matrix formulas in:

> *"Deep learning-assisted colorimetric/electrical dual-sensing system for ultra-fast detection of hydrogen sulfide"*
> — ACS (se3c02793)

---

## Software Status

| # | Component | Directory | Status |
|---|-----------|-----------|--------|
| 1 | ML pipeline (colour science + dose regression) | `software/ml_pipeline/` | Complete |
| 2 | Backend API (FastAPI + SQLAlchemy + JWT + PDF) | `software/backend/` | Complete — 49/49 API tests, 16/16 offline checks |
| 3 | Admin dashboard (React + Vite + Chart.js) | `software/dashboard/` | Complete — login, dashboard, workers, submit reading, alerts, reports |
| 4 | Mobile app (Flutter + on-device TFLite) | — | **Not started** — directory does not exist yet |

All three built components are **independent processes** that talk over HTTP/JSON.

---

## Architecture

```
Worker wears wristband
      |  copper-acetate strip darkens with cumulative H2S exposure
      v
Colorimetric reading  (today: ml_pipeline/ on a workstation; Phase 4: on-device in the Flutter app)
      |- ROI detection (OpenCV / HSV)
      |- sRGB -> CIE XYZ -> CIE L*a*b*
      |- CIE DE2000 dE vs a fresh-strip baseline
      |- reference-card lighting correction
      |- ML regression  ->  dose_ppm_hr
      v
      |  POST /readings/   {worker_id, delta_E, dose_ppm_hr, Lab, RGB, temp, humidity, ...}
      v
Backend  (software/backend/ — FastAPI + SQLAlchemy)
      |- stores the reading
      |- evaluates DGMS thresholds and auto-creates alerts
      |- serves /dashboard/summary, /workers, /readings, /alerts, /reports
      v
      |  fetch() with a JWT bearer token   (VITE_API_BASE, default http://localhost:8000)
      v
Admin dashboard  (software/dashboard/ — React 19 + Chart.js)
```

**The backend does not run the ML model or OpenCV.** It receives an already-computed `dose_ppm_hr` and only
stores, aggregates and alerts. Keep the two decoupled — do not add `scikit-learn` or `opencv` to the backend.

---

## Repository Layout

```
SIH-H2S-Dosimeter/
├── README.md                     this file
├── CLAUDE.md                     working notes / conventions for AI coding agents
└── software/
    ├── README.md                 component index
    ├── ml_pipeline/              Phase 1 — colour science + dose regression
    │   ├── image_processor.py         sRGB->Lab, CIE DE2000, ROI detection, lighting correction
    │   ├── dataset_builder.py         folder of labelled strip photos -> datasets/dataset.csv
    │   ├── model_trainer.py           compares 5 regressors by CV R2, saves the best; exposes predict()
    │   ├── model_evaluator.py         residual / calibration / feature-importance plots
    │   ├── demo_simulator.py          synthetic dataset -> train -> plots (primary end-to-end test)
    │   ├── env_compensation.py        temperature/humidity correction (needs a local IoT dataset)
    │   ├── live_ai_demonstrator.py    narrated walkthrough; optionally POSTs to a running backend
    │   ├── requirements.txt
    │   └── README.md
    ├── backend/                  Phase 2 — REST API, database, auth, reports
    │   ├── main.py                    app entry, CORS, router wiring, /auth/*, /health, lifespan startup
    │   ├── config.py                  centralized env config (fails fast in production)
    │   ├── database.py                engine / session / init_db
    │   ├── models.py                  ORM: SafetyOfficer, Worker, Reading, Alert
    │   ├── schemas.py                 Pydantic v2 request/response models
    │   ├── auth.py                    bcrypt hashing, JWT, get_current_officer / require_admin
    │   ├── routes/                    workers, readings, alerts, reports, dashboard
    │   ├── seed.py                    WIPES and re-seeds demo data
    │   ├── test_api.py                49 integration tests (needs a running server)
    │   ├── test_offline_checks.py     16 offline checks (no server needed)
    │   ├── requirements.txt
    │   └── .env.example
    └── dashboard/                Phase 3 — admin SPA
        ├── src/api.js                 single API client; holds the JWT, handles 401
        ├── src/App.jsx                hash-based routing + sidebar
        ├── src/index.css              all styling (no CSS framework)
        ├── src/pages/                 Login, Dashboard, Workers, SubmitReading, Alerts, Reports
        ├── package.json
        ├── .oxlintrc.json
        └── .env.example
```

Generated artefacts are git-ignored and regenerated on demand: `ml_pipeline/models/`, `ml_pipeline/datasets/*.csv`,
`ml_pipeline/results/*.png`, `backend/*.db`, `dashboard/node_modules/`, `dashboard/dist/`.

---

## Running the System

Three terminals. The backend and dashboard are needed for a full demo; the ML pipeline is standalone.

### 1. Backend — `software/backend/`

```bash
cd software/backend
pip install -r requirements.txt
python seed.py                 # optional: WIPES the DB and loads demo workers/readings/alerts
uvicorn main:app --reload      # -> http://localhost:8000   (Swagger UI at /docs)
```

Dev login: **`admin` / `admin123`**. After seeding, **`officer1` / `officer123`** also exists as a non-admin
officer. These are development defaults defined in `seed.py` and the startup hook in `main.py` — change them
before any real deployment.

### 2. Dashboard — `software/dashboard/`

```bash
cd software/dashboard
npm install
npm run dev                    # -> http://localhost:5173
npm run build                  # production bundle into dist/
npm run lint                   # oxlint
```

Reads the backend URL from `VITE_API_BASE` (default `http://localhost:8000`). See `.env.example`.

### 3. ML pipeline — `software/ml_pipeline/`

```bash
cd software/ml_pipeline
pip install -r requirements.txt

python image_processor.py      # colour-math self-test, no data required
python demo_simulator.py       # synthetic dataset -> train -> save model + calibration plot
python model_evaluator.py      # diagnostic plots (needs a trained model + dataset)
python live_ai_demonstrator.py # narrated walkthrough; POSTs to the backend if one is running

# with real labelled strip photos:
python dataset_builder.py --images_dir ./sample_images --output datasets/dataset.csv
python model_trainer.py --csv datasets/dataset.csv
```

`demo_simulator.py` must be run at least once before `model_evaluator.py`, since `models/` and `datasets/` ship
empty. `sample_images/` is also empty — no real strip photographs have been collected yet.

`env_compensation.py` requires a large IoT sensor archive that is **not** in the repository (git-ignored, local
only); it will report a missing-file error without it.

---

## API Surface

Every endpoint below is implemented in `software/backend/routes/`.

**Public** — no token required:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Service banner + docs links |
| `GET` | `/health` | Liveness + database probe |
| `POST` | `/auth/login` | Exchange username/password for a JWT (form-encoded) |
| `GET` | `/docs` | Swagger UI |

**Authenticated** — require `Authorization: Bearer <token>`; a missing or invalid token returns **401**:

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/auth/me` | Current officer identity + role |
| `GET` | `/workers/` | List workers; filter by `site`, `shift`, `active_only` |
| `GET` | `/workers/{worker_id}` | Single worker by code, e.g. `WRK001` |
| `POST` | `/workers/` | **admin only** (→403 otherwise) |
| `PUT` | `/workers/{worker_id}` | **admin only** |
| `DELETE` | `/workers/{worker_id}` | **admin only** — soft-delete (sets `is_active=false`) |
| `POST` | `/readings/` | Submit a scan; evaluates thresholds and may create an alert |
| `GET` | `/readings/today` | All readings for today's shift date |
| `GET` | `/readings/worker/{worker_id}` | Per-worker history; optional `shift_date`, `limit` |
| `GET` | `/readings/{reading_id}` | Single reading |
| `GET` | `/alerts/` | All alerts; filter by `unacknowledged_only`, `alert_type` |
| `GET` | `/alerts/worker/{worker_id}` | Per-worker alerts |
| `POST` | `/alerts/{alert_id}/acknowledge` | Sign off an alert |
| `GET` | `/alerts/summary/counts` | Counts by type and acknowledgement state |
| `GET` | `/dashboard/summary` | Aggregated worker statuses + headline counts |
| `GET` | `/reports/worker/{worker_id}/json` | Report data for charts |
| `GET` | `/reports/worker/{worker_id}/pdf` | DGMS-format PDF (ReportLab) |

Safety officers and admins are the only login accounts. **Workers are data subjects, not user accounts**, so
there is no per-worker login and no per-worker IDOR surface.

---

## DGMS Compliance Thresholds

| Parameter | Limit |
|-----------|-------|
| TWA (8-hour average) | 10 ppm |
| STEL (15-minute) | 15 ppm |
| Cumulative dose — **warning** | 60 ppm·hr |
| Cumulative dose — **danger** (8-hr TWA reached) | 80 ppm·hr |
| Cumulative dose — **critical** (evacuate) | 100 ppm·hr |

The backend owns these thresholds and is the single source of truth for alert generation. They are currently
**duplicated** as module constants in `routes/readings.py`, `routes/dashboard.py` and `seed.py` — change all
three together.

---

## Configuration

No secrets are committed. Copy the templates and edit locally; `.env` files are git-ignored.

### Backend — `software/backend/.env.example`

| Variable | Default (dev) | Notes |
|----------|---------------|-------|
| `APP_ENV` | `development` | Set to `production` to enforce the checks below |
| `SECRET_KEY` | insecure dev fallback | **Required in production** — the app refuses to start without it |
| `JWT_ALGORITHM` | `HS256` | |
| `TOKEN_EXPIRE_MINUTES` | `480` | 8-hour shift |
| `DATABASE_URL` | `sqlite:///./h2s_dosimeter.db` | PostgreSQL-ready, e.g. `postgresql+psycopg2://user:pass@host:5432/db` |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated. **Not** `*` — set it to the deployed dashboard origin |

Generate a production secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Dashboard — `software/dashboard/.env.example`

| Variable | Default | Notes |
|----------|---------|-------|
| `VITE_API_BASE` | `http://localhost:8000` | Only `VITE_`-prefixed vars reach the browser bundle — never put a secret here |

Also note: schema changes are applied by SQLAlchemy `create_all()` at startup. There is no migration tool, so an
existing SQLite file will not pick up new columns — delete it or re-run `seed.py` after a model change.

---

## Testing

### Backend

```bash
cd software/backend
python test_offline_checks.py    # 16 checks, no server and no jose/bcrypt/reportlab needed
```

```bash
# terminal 1
uvicorn main:app --reload
# terminal 2
python test_api.py               # 49 integration tests; re-seeds the DB first
```

`test_api.py` covers health, login, 401/403 enforcement across every protected route, worker CRUD, reading
submission with alert generation, alert acknowledgement, the dashboard summary and both report formats
(including an authenticated PDF download).

`test_offline_checks.py` verifies the dashboard aggregation refactor against the previous per-worker query loop
and confirms alert serialization, using an in-memory SQLite database.

### ML pipeline

```bash
cd software/ml_pipeline
python image_processor.py        # asserts RGB->Lab against 5 known colours and dE(x,x)==0
python demo_simulator.py         # end-to-end; warns if test R2 falls below the 0.85 target
```

### Dashboard

```bash
cd software/dashboard
npm run build                    # must succeed
npm run lint                     # 0 errors (6 pre-existing warnings in Dashboard/Workers/Alerts/Reports)
```

There is **no automated frontend test suite.** The Submit Reading flow was verified manually against a live
backend in headless Chrome — login, roster load, all four presets, alert generation, the Alerts/Reports/Dashboard
knock-on effects, client-side validation and a backend 404 path. That was a one-off harness and is not committed;
re-verification is manual.

### Last recorded results

| Check | Result |
|-------|--------|
| `test_api.py` | 49/49 passed |
| `test_offline_checks.py` | 16/16 passed |
| `npm run build` | succeeds |
| `npm run lint` | 0 errors, 6 pre-existing warnings |
| Submit Reading browser walkthrough | 69/69 assertions passed (manual) |

---

## ML Model Performance

From `demo_simulator.py` on **synthetic** data — a physics-based colour model, not real strip photographs:

| Metric | Representative run |
|--------|--------------------|
| Test R² | 0.8630 (target: > 0.85) |
| RMSE | 11.37 ppm·hr |
| MAE | 8.89 ppm·hr |
| Selected model | RandomForest (CV R² 0.9152) |
| ΔE metric | CIE DE2000 |

**These numbers are not reproducible run-to-run.** `simulate_strip_color()` draws noise from an unseeded
generator and the dose array is shuffled with an unseeded global shuffle, so each run produces a different
dataset. Observed spread across recent runs was roughly **R² 0.89–0.93**, and the winning model alternates
between RandomForest and PolyRidge_deg2. Treat the table as one representative run, not a fixed benchmark, and
quote your own run when reporting.

Accuracy on real hardware is still unknown — no strip photographs have been collected. The
`BASELINE_LAB` and `REFERENCE_PATCHES_LAB` constants in `image_processor.py` are calibration values; changing
them is a recalibration, not a refactor.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Image processing | Python, OpenCV, NumPy |
| Colour science | CIE L\*a\*b\*, CIE DE2000 |
| ML | scikit-learn (RandomForest / GBM / SVR / Ridge), joblib |
| Backend | FastAPI, SQLAlchemy 2.0, Pydantic v2, python-jose, bcrypt, ReportLab |
| Database | SQLite (dev), PostgreSQL-ready (prod) |
| Dashboard | React 19, Vite 8, Chart.js, react-chartjs-2, oxlint |
| Mobile (planned) | Flutter, TFLite |

---

## Not Yet Implemented

Verified against the repository as of this commit:

- **Mobile app** — the largest remaining piece. `software/mobile_app/` does not exist; only `.gitignore` entries
  anticipate it. The intended path is Flutter with on-device TFLite inference, reusing the `model_trainer.predict()`
  contract and posting to `POST /readings/`.
- **Real strip-photo dataset** — `sample_images/` is empty; all results to date are synthetic.
- **Environmental compensation wired into prediction** — `env_compensation.py` trains a standalone model but
  nothing consumes its output in the dose path yet, and its input archive is not in the repository.
- **Production deployment** — no Dockerfile, no CI/CD, no hosting configuration. A real `SECRET_KEY`,
  `CORS_ORIGINS` and a PostgreSQL `DATABASE_URL` must be supplied.
- **Database migrations** — schema is created by `create_all()`; there is no Alembic setup.
- **Automated frontend tests** — no test runner is configured for the dashboard.
- **Worker edit / deactivate UI** — the API supports both (admin only); the dashboard only lists and creates.
- **Login rate limiting** — `POST /auth/login` is unthrottled.

---

## Team

**College**: Dayananda Sagar College of Engineering (DSCE)
**Competition**: Smart India Hackathon 2026
**Problem Statement**: SIH26118
