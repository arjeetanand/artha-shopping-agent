const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'include',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

export function getHealth() {
  return request('/health');
}

export function getSession() {
  return request('/auth/session');
}

export function beginGoogleSignIn(next = '/') {
  window.location.assign(`${API_BASE}/auth/google/start?next=${encodeURIComponent(next)}`);
}

export function signOut() {
  return request('/auth/logout', { method: 'POST', body: JSON.stringify({}) });
}

export function runAgentSearch(payload) {
  return request('/agent/search', { method: 'POST', body: JSON.stringify(payload) });
}

export function getPlans() {
  return request('/plans');
}

export function getUsage({ days = 30, runtime = 'all' } = {}) {
  const params = new URLSearchParams({ days: String(days), runtime });
  return request(`/usage?${params.toString()}`);
}

export function createPlan(payload) {
  return request('/plans', { method: 'POST', body: JSON.stringify(payload) });
}

export function getOrders() {
  return request('/orders');
}

export function createOrder(payload) {
  return request('/orders', { method: 'POST', body: JSON.stringify(payload) });
}

export function getOrder(orderId) {
  return request(`/orders/${encodeURIComponent(orderId)}`);
}

export function cancelOrder(orderId) {
  return request(`/orders/${encodeURIComponent(orderId)}/cancel`, { method: 'POST', body: JSON.stringify({}) });
}

export function advanceOrder(orderId) {
  return request(`/orders/${encodeURIComponent(orderId)}/advance`, { method: 'POST', body: JSON.stringify({}) });
}

export function requestReturn(orderId) {
  return request(`/orders/${encodeURIComponent(orderId)}/return`, { method: 'POST', body: JSON.stringify({}) });
}

export function completeRefund(orderId) {
  return request(`/orders/${encodeURIComponent(orderId)}/refund`, { method: 'POST', body: JSON.stringify({}) });
}

export function getVoiceStatus() {
  return request('/voice/status');
}

export function warmVoice() {
  return request('/voice/warm', { method: 'POST', body: JSON.stringify({}) });
}

export async function speakText(text) {
  const response = await fetch(`${API_BASE}/voice/speak`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  const contentType = response.headers.get('content-type') || '';
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || `Voice request failed (${response.status})`);
  }
  if (contentType.startsWith('audio/')) return { provider: 'server', blob: await response.blob() };
  return response.json();
}
