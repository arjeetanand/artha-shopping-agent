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

export async function runAgentSearchAsync(payload, onProgress) {
  let job = await request('/agent/search/jobs', { method: 'POST', body: JSON.stringify(payload) });
  for (let attempt = 0; attempt < 600; attempt += 1) {
    if (typeof onProgress === 'function') onProgress(job);
    if (job.status === 'complete' && job.result) return job.result;
    if (job.status === 'failed') throw new Error(job.error || 'The research job could not complete.');
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    job = await request(`/agent/search/jobs/${encodeURIComponent(job.job_id)}`);
  }
  throw new Error('Research is taking longer than expected. The current job can be retried from the brief.');
}

export function refineAgentSearch(payload) {
  return request('/agent/refine', { method: 'POST', body: JSON.stringify(payload) });
}

export function extractSocialTheme(url) {
  return request('/social/theme', { method: 'POST', body: JSON.stringify({ url }) });
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

export function createPaymentOrder(payload) {
  return request('/payments/order', { method: 'POST', body: JSON.stringify(payload) });
}

export function verifyPayment(payload) {
  return request('/payments/verify', { method: 'POST', body: JSON.stringify(payload) });
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

export function getTasteProfile() {
  return request('/profile/taste');
}

export function updateTasteProfile(preferences, stats = null) {
  return request('/profile/taste', { method: 'POST', body: JSON.stringify({ preferences, stats }) });
}

export function syncRetailerAccount(provider) {
  return request('/profile/sync-account', {
    method: 'POST',
    body: JSON.stringify({ provider }),
  });
}

export function getTasteGraph(searchId = '') {
  const query = searchId ? `?search_id=${encodeURIComponent(searchId)}` : '';
  return request(`/profile/graph${query}`);
}

export function getProfileOrders() {
  return request('/profile/orders');
}

export const getProfileConnections = () => request('/profile/connections');
export const getTasteMemories = () => request('/profile/memories');
export const getProfileInvoices = () => request('/profile/invoices');
export const invoiceDownloadUrl = (id) => `${API_BASE}/profile/invoices/${encodeURIComponent(id)}`;
export const cancelRetailerSync = (provider) => request('/profile/connections/cancel', {method:'POST',body:JSON.stringify({provider})});
export const disconnectRetailer = (provider) => request('/profile/connections/disconnect', {method:'POST',body:JSON.stringify({provider})});
export const rememberProduct = (product) => request('/profile/memories', {method:'POST',body:JSON.stringify({product})});
export const removeTasteMemory = (id) => request('/profile/memories/remove', {method:'POST',body:JSON.stringify({id})});
export const reindexTasteMemories = () => request('/profile/memories/reindex', {method:'POST',body:JSON.stringify({})});
