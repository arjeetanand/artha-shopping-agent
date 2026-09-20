const gatewayUrl = import.meta.env.VITE_MAKE_GATEWAY_URL || '/api/gateway';

export const isGatewayConfigured = import.meta.env.VITE_GATEWAY_MODE !== 'demo' && !gatewayUrl.includes('{{');

export async function callMakeGateway(payload) {
  if (!isGatewayConfigured) return null;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(gatewayUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const raw = await response.text();
    let data;
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      if (response.ok && /^(accepted|ok)$/i.test(raw.trim())) {
        throw new Error('Make accepted the request but returned no JSON. Add a Webhook Response module or keep VITE_GATEWAY_MODE=demo for the local demo flow.');
      }
      throw new Error(`Make gateway returned a non-JSON response (${response.status}).`);
    }
    if (!response.ok || data.success === false) throw new Error(data.message || `Make gateway returned ${response.status}`);
    return data;
  } finally {
    window.clearTimeout(timeout);
  }
}
