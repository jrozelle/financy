import { _alertsCache, setAlertsCache } from './state.js';
import { api } from './api.js';

export async function loadUserAlertsAsync() {
  if (_alertsCache !== null) return _alertsCache;
  try {
    let data = await api('GET', '/api/alerts');
    if (!Array.isArray(data)) data = [];
    setAlertsCache(data);
  } catch {
    try { setAlertsCache(JSON.parse(localStorage.getItem('patrimoine_alerts')) || []); } catch { setAlertsCache([]); }
  }
  return _alertsCache;
}

export function loadUserAlerts() {
  return _alertsCache || [];
}

export async function saveUserAlerts(a) {
  setAlertsCache(a);
  try {
    await api('PUT', '/api/alerts', a);
    localStorage.removeItem('patrimoine_alerts');
  } catch {
    localStorage.setItem('patrimoine_alerts', JSON.stringify(a));
  }
}
