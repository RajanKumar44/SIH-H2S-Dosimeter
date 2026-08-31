const API_BASE = "http://localhost:8000";

let authToken = localStorage.getItem("h2s_token") || null;

async function request(method, path, body = null) {
  const headers = { "Content-Type": "application/json", Accept: "application/json" };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const opts = { method, headers };
  if (body && method !== "GET") {
    if (body instanceof URLSearchParams) {
      opts.body = body.toString();
      headers["Content-Type"] = "application/x-www-form-urlencoded";
    } else {
      opts.body = JSON.stringify(body);
    }
  }

  const res = await fetch(`${API_BASE}${path}`, opts);
  if (res.status === 401) {
    authToken = null;
    localStorage.removeItem("h2s_token");
    window.location.hash = "#/login";
    throw new Error("Unauthorized");
  }
  const data = res.headers.get("content-type")?.includes("json")
    ? await res.json()
    : await res.text();
  if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
  return data;
}

export const api = {
  // Auth
  login: async (username, password) => {
    const body = new URLSearchParams({ username, password });
    const data = await request("POST", "/auth/login", body);
    authToken = data.access_token;
    localStorage.setItem("h2s_token", authToken);
    return data;
  },
  logout: () => {
    authToken = null;
    localStorage.removeItem("h2s_token");
  },
  me: () => request("GET", "/auth/me"),
  isLoggedIn: () => !!authToken,

  // Dashboard
  dashboardSummary: () => request("GET", "/dashboard/summary"),

  // Workers
  listWorkers: (params = "") => request("GET", `/workers/${params}`),
  getWorker: (id) => request("GET", `/workers/${id}`),
  createWorker: (data) => request("POST", "/workers/", data),
  updateWorker: (id, data) => request("PUT", `/workers/${id}`, data),

  // Readings
  submitReading: (data) => request("POST", "/readings/", data),
  getWorkerReadings: (id, date) =>
    request("GET", `/readings/worker/${id}${date ? `?shift_date=${date}` : ""}`),
  getTodayReadings: () => request("GET", "/readings/today"),

  // Alerts
  listAlerts: (unacked = false) =>
    request("GET", `/alerts/?unacknowledged_only=${unacked}`),
  getWorkerAlerts: (id) => request("GET", `/alerts/worker/${id}`),
  acknowledgeAlert: (id, by) =>
    request("POST", `/alerts/${id}/acknowledge`, { acknowledged_by: by }),
  alertCounts: () => request("GET", "/alerts/summary/counts"),

  // Reports
  getWorkerReport: (id, date) =>
    request("GET", `/reports/worker/${id}/json${date ? `?shift_date=${date}` : ""}`),
  downloadPdf: (id, date) => {
    const url = `${API_BASE}/reports/worker/${id}/pdf${date ? `?shift_date=${date}` : ""}`;
    window.open(url, "_blank");
  },

  // Health
  health: () => request("GET", "/health"),
};
