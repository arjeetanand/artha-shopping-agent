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

export function beginGmailConnect(next = '/taste-graph') {
  window.location.assign(`${API_BASE}/auth/gmail/start?next=${encodeURIComponent(next)}`);
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

export async function transcribeAudio(blob, signal) {
  const audio = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('Could not read the microphone recording.'));
    reader.readAsDataURL(blob);
  });
  const deadline = new AbortController();
  const timer = setTimeout(() => deadline.abort(new Error('Transcription timed out. Please record again or type your request.')), 40_000);
  try {
    return await request('/voice/transcribe', {
      method: 'POST', signal: AbortSignal.any([signal, deadline.signal].filter(Boolean)),
      body: JSON.stringify({ audio, content_type: blob.type }),
    });
  } finally {
    clearTimeout(timer);
  }
}

export function getTasteProfile() {
  return request('/profile/taste');
}

export function updateTasteProfile(preferences, stats = null) {
  return request('/profile/taste', { method: 'POST', body: JSON.stringify({ preferences, stats }) });
}

export function syncRetailerAccount(provider) {
  if (['amazon', 'flipkart', 'myntra', 'ajio'].includes(provider)) return startRetailerExtensionSync(provider);
  throw new Error('Instagram personal-account history is not available through Meta’s API. Paste a public video URL in Discover to save its style.');
}

function extensionMessage(type, responseType, details = {}, timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => finish(new Error('The Artha retailer Chrome connector did not respond.')), timeoutMs);
    const onMessage = (event) => {
      if (event.source !== window || event.origin !== window.location.origin || event.data?.source !== 'artha-extension' || event.data?.type !== responseType) return;
      finish(null, event.data);
    };
    const finish = (error, value) => {
      window.clearTimeout(timeout);
      window.removeEventListener('message', onMessage);
      if (error) reject(error);
      else resolve(value);
    };
    window.addEventListener('message', onMessage);
    window.postMessage({ source: 'artha-portal', type, ...details }, window.location.origin);
  });
}

function retailerCutoff() {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date()).map((part) => [part.type, part.value]));
  const year = Number(parts.year), month = Number(parts.month), day = Number(parts.day);
  const index = year * 12 + month - 1 - 6;
  const targetYear = Math.floor(index / 12), targetMonth = index % 12 + 1;
  const targetDay = Math.min(day, new Date(Date.UTC(targetYear, targetMonth, 0)).getUTCDate());
  return `${targetYear}-${String(targetMonth).padStart(2, '0')}-${String(targetDay).padStart(2, '0')}`;
}

async function startRetailerExtensionSync(provider) {
  try {
    const ready = await extensionMessage('PING', 'READY');
    if (!ready) throw new Error('Install the Artha retailer Chrome connector, then reload this portal.');
    const jobId = `sync-${crypto.randomUUID().replaceAll('-', '')}`;
    const result = await extensionMessage('START', 'START_RESULT', { job_id: jobId, provider, cutoff: retailerCutoff() }, 8000);
    if (!result.ok || !result.started) throw new Error(result.error || 'Chrome could not open the retailer.');
    return { job_id: jobId, provider, status: 'syncing', connector: 'extension-local' };
  } catch (error) {
    if (error.message.includes('did not respond')) throw new Error('Install the Artha retailer Chrome connector, then reload this portal.');
    throw error;
  }
}

export const submitRetailerExtensionBatch = (provider, pages, stop_reason) => request('/profile/retailer-extension/submit', {
  method: 'POST', body: JSON.stringify({ provider, pages, stop_reason }),
});

export const cancelRetailerExtensionTab = (job_id) => extensionMessage('CANCEL', 'CANCEL_RESULT', { job_id });
export const finishRetailerExtensionTab = (job_id) => extensionMessage('FINISH', 'FINISH_RESULT', { job_id });
export const cancelRetailerExtensionSync = (provider) => request('/profile/retailer-extension/cancel', { method: 'POST', body: JSON.stringify({ provider }) });
export const disconnectRetailerExtension = (provider) => request('/profile/retailer-extension/disconnect', { method: 'POST', body: JSON.stringify({ provider }) });

export const syncGmail = () => request('/profile/gmail/sync', { method: 'POST', body: JSON.stringify({}) });
export const cancelGmailSync = () => request('/profile/gmail/cancel', { method: 'POST', body: JSON.stringify({}) });
export const disconnectGmail = () => request('/profile/gmail/disconnect', { method: 'POST', body: JSON.stringify({}) });

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

export function getAssistantSession({ sessionId = '', reset = false } = {}) {
  const params = new URLSearchParams();
  if (sessionId) params.set('session_id', sessionId);
  if (reset) params.set('reset', '1');
  const qs = params.toString();
  return request(`/assistant/session${qs ? `?${qs}` : ''}`);
}

export function sendAssistantTurn(payload) {
  return request('/assistant/converse', { method: 'POST', body: JSON.stringify(payload) });
}

export function confirmInstagramReference(payload) {
  return request('/assistant/confirm-reference', { method: 'POST', body: JSON.stringify(payload) });
}

export function resolveInstagramReference(payload) {
  return request('/social/instagram/resolve', { method: 'POST', body: JSON.stringify(payload) });
}

export function uploadInstagramReference(payload) {
  return request('/social/instagram/upload', { method: 'POST', body: JSON.stringify(payload) });
}
