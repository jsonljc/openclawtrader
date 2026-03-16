import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api",
});

export const fetchPortfolio = () => api.get("/portfolio").then((r) => r.data);
export const fetchSignals = () => api.get("/signals").then((r) => r.data);
export const fetchAlerts = (limit = 20) => api.get(`/alerts?limit=${limit}`).then((r) => r.data);
export const fetchTrades = (limit = 50) => api.get(`/trades?limit=${limit}`).then((r) => r.data);
export const fetchEquityCurve = (days = 30) => api.get(`/equity-curve?days=${days}`).then((r) => r.data);
export const fetchHealth = () => api.get("/health").then((r) => r.data);
export const fetchRegime = () => api.get("/regime").then((r) => r.data);
