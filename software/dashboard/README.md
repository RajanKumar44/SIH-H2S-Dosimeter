# Admin Dashboard

React + Vite single-page admin console for the SIH26118 H₂S dosimeter system. Safety officers log in here to
review worker exposure, submit wristband readings, acknowledge DGMS threshold alerts and download compliance
reports.

See the [root README](../../README.md) for the full system architecture and API reference.

## Quick start

```bash
npm install
npm run dev       # -> http://localhost:5173
```

The backend must be running for anything past the login screen:

```bash
cd ../backend && uvicorn main:app --reload
```

Dev login: **`admin` / `admin123`** (after `python seed.py`, `officer1` / `officer123` also exists as a non-admin
officer, useful for demonstrating the 403 on admin-only actions).

## Scripts

| Command | Purpose |
|---------|---------|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | Production bundle into `dist/` |
| `npm run preview` | Serve the built bundle locally |
| `npm run lint` | oxlint (config in `.oxlintrc.json`) |

`npm run lint` currently reports **0 errors and 6 warnings**, all pre-existing in `Dashboard.jsx`, `Workers.jsx`,
`Alerts.jsx` and `Reports.jsx` (unused import, `exhaustive-deps`, `set-state-in-effect`).

## Configuration

| Variable | Default | Notes |
|----------|---------|-------|
| `VITE_API_BASE` | `http://localhost:8000` | Backend base URL |

Copy `.env.example` to `.env` to change it. Only `VITE_`-prefixed variables reach the browser bundle — **never put
a secret in one**, since it ships to every client. `.env` is git-ignored.

The backend restricts CORS to `CORS_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173`), so a
dashboard served from another origin needs that variable updated on the backend side.

## Pages

| Route | File | What it does |
|-------|------|--------------|
| `#/login` | `pages/Login.jsx` | Username/password → JWT, stored in `localStorage` |
| `#/dashboard` | `pages/Dashboard.jsx` | Headline counts, status doughnut, top-dose bar chart, full worker table. Auto-refreshes every 30 s |
| `#/workers` | `pages/Workers.jsx` | Worker roster + registration form (creation is admin-only server-side) |
| `#/submit` | `pages/SubmitReading.jsx` | Submit a strip reading; demo presets for safe / warning / danger / critical |
| `#/alerts` | `pages/Alerts.jsx` | Alert list, filter by acknowledgement state, acknowledge |
| `#/reports` | `pages/Reports.jsx` | Per-worker exposure timeline against DGMS limits, reading table, PDF download |

## Architecture notes

- **Routing is manual and hash-based**, implemented in `App.jsx`. `react-router-dom` is a dependency but is not
  used — do not assume router APIs are available.
- **`src/api.js` is the only place that talks to the backend.** It holds the JWT, attaches the
  `Authorization` header, and on any `401` clears the token and redirects to `#/login`. Add new endpoints there
  rather than calling `fetch` from a page.
- **PDF download must stay an authenticated `fetch`.** `downloadPdf` streams the response into a Blob and
  triggers a save; a plain `window.open()` would drop the JWT and 401.
- **The backend owns all threshold logic.** Pages render the dose bands, alert types and messages the API returns;
  they must not re-derive whether a reading breached a threshold.
- **Styling is a single stylesheet**, `src/index.css`, using CSS custom properties for the dark theme. There is no
  CSS framework — reuse the existing `.stat-card`, `.table-card`, `.badge`, `.btn`, `.form-*` classes.
- Function components with hooks throughout; JSX, ES modules, React 19.

## Testing

There is **no automated frontend test suite** — no test runner is configured. Verification today is
`npm run build`, `npm run lint`, and manual browser checks against a live backend.

The Submit Reading flow was validated in headless Chrome against a live FastAPI instance (roster loading, all four
presets, backend-driven alert outcomes, the Alerts/Reports/Dashboard knock-on effects, client-side validation and
a backend 404 path). That harness was a one-off and is not committed.
