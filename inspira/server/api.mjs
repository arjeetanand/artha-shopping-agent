import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  advanceOrder,
  analyzeRequest,
  buildUnderstanding,
  createApproval,
  createOrder,
  getRejected,
  makeSessionId,
  searchAndRank,
  trackingSteps,
} from '../src/lib/demoEngine.js';

const here = dirname(fileURLToPath(import.meta.url));
const stateFile = resolve(here, 'data/state.json');
const corsHeaders = {
  'access-control-allow-origin': '*',
  'access-control-allow-headers': 'content-type',
  'access-control-allow-methods': 'POST, OPTIONS',
};

let statePromise;

function emptyState() {
  return { sessions: {}, requirements: {}, pendingPurchases: {}, orders: {}, orderEvents: [] };
}

async function loadState() {
  if (!statePromise) {
    statePromise = readFile(stateFile, 'utf8')
      .then((raw) => ({ ...emptyState(), ...JSON.parse(raw) }))
      .catch(() => emptyState());
  }
  return statePromise;
}

async function saveState(next) {
  statePromise = Promise.resolve(next);
  await mkdir(dirname(stateFile), { recursive: true });
  await writeFile(stateFile, JSON.stringify(next, null, 2));
}

function send(res, status, payload) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', ...corsHeaders });
  res.end(JSON.stringify(payload));
}

function envelope({ success = true, sessionId, state, responseType, message, data = {} }) {
  return { success, session_id: sessionId, state, response_type: responseType, message, data };
}

function readJson(req) {
  return new Promise((resolveBody, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 3_000_000) reject(new Error('Payload too large'));
    });
    req.on('end', () => {
      try { resolveBody(raw ? JSON.parse(raw) : {}); } catch { reject(new Error('Invalid JSON payload')); }
    });
    req.on('error', reject);
  });
}

function addEvent(state, orderId, previousStatus, newStatus, message) {
  state.orderEvents.push({
    event_id: `evt_${Math.random().toString(36).slice(2, 10)}`,
    order_id: orderId,
    previous_status: previousStatus,
    new_status: newStatus,
    event_timestamp: new Date().toISOString(),
    message,
    notification_sent: true,
  });
}

function timelineFor(state, orderId) {
  return state.orderEvents.filter((event) => event.order_id === orderId).map((event) => ({
    status: event.new_status,
    timestamp: event.event_timestamp,
    message: event.message,
  }));
}

function normalizeOrder(order) {
  return {
    ...order,
    orderStatus: order.orderStatus || order.order_status || 'CONFIRMED',
    trackingStatus: order.trackingStatus || order.tracking_status || 'CONFIRMED',
    itemCount: order.itemCount || order.items?.length || 1,
  };
}

async function handleGateway(body) {
  const state = await loadState();
  const action = body.action;
  const sessionId = body.session_id || makeSessionId();

  if (!action) {
    return { status: 400, body: envelope({ success: false, sessionId, state: 'NEW', responseType: 'error', message: 'Missing action.' }) };
  }

  if (action === 'shop') {
    const message = String(body.message || '').trim();
    const hasImage = Boolean(body.image_url || body.image_data);
    if (!message && !hasImage) {
      return { status: 400, body: envelope({ success: false, sessionId, state: 'NEW', responseType: 'error', message: 'Add a request or an inspiration image to begin.' }) };
    }
    const analysis = analyzeRequest({ message, hasImage });
    const understanding = buildUnderstanding({ analysis, message, hasImage });
    understanding.clarification_needed = hasImage && !message;
    understanding.clarification_question = understanding.clarification_needed ? 'Are you shopping for the whole look or one piece from it?' : null;
    state.sessions[sessionId] = {
      session_id: sessionId,
      conversation_id: body.conversation_id || sessionId,
      created_at: state.sessions[sessionId]?.created_at || new Date().toISOString(),
      updated_at: new Date().toISOString(),
      last_user_message: message,
      current_state: understanding.clarification_needed ? 'CLARIFYING' : 'SEARCHING',
    };
    state.requirements[sessionId] = understanding;

    if (understanding.clarification_needed) {
      state.sessions[sessionId].current_state = 'CLARIFYING';
      await saveState(state);
      return { status: 200, body: envelope({ sessionId, state: 'CLARIFYING', responseType: 'clarification', message: understanding.clarification_question, data: { requirements: understanding, clarification_question: understanding.clarification_question } }) };
    }

    const rawRecommendations = searchAndRank(analysis);
    const recommendations = rawRecommendations.map((recommendation) => {
      const approval = createApproval(recommendation, sessionId);
      const expiresAt = new Date(Date.now() + 20 * 60 * 1000).toISOString();
      state.pendingPurchases[approval.approvalToken] = { ...approval, expiresAt, status: 'PENDING_CONFIRMATION' };
      return { ...recommendation, approval_token: approval.approvalToken };
    });
    const rejected = getRejected(analysis);
    state.sessions[sessionId].current_state = recommendations.length ? 'AWAITING_CONFIRMATION' : 'RECOMMENDED';
    await saveState(state);
    return { status: 200, body: envelope({ sessionId, state: state.sessions[sessionId].current_state, responseType: 'recommendations', message: recommendations.length ? `I found ${recommendations.length} valid options.` : 'I could not find a valid match for every requirement.', data: { requirements: understanding, recommendations, rejected } }) };
  }

  if (action === 'confirm_purchase') {
    const existing = Object.values(state.orders).find((candidate) => candidate.approval_token === body.approval_token);
    if (existing) {
      return { status: 200, body: envelope({ sessionId, state: 'ORDER_CREATED', responseType: 'order_confirmation', message: `This approval already created ${existing.orderId}. No second order was created.`, data: { order: existing, timeline: timelineFor(state, existing.orderId) } }) };
    }
    const pending = state.pendingPurchases[body.approval_token];
    if (!body.confirmed || !pending || pending.sessionId !== sessionId || pending.status !== 'PENDING_CONFIRMATION' || Date.now() > Date.parse(pending.expiresAt)) {
      return { status: 409, body: envelope({ success: false, sessionId, state: 'AWAITING_CONFIRMATION', responseType: 'error', message: 'The approval is missing, expired, or already used. No order was created.' }) };
    }
    const order = normalizeOrder({ ...createOrder(pending), approval_token: body.approval_token, session_id: sessionId, data_source: 'LOCAL_MOCK_COMMERCE' });
    state.orders[order.orderId] = order;
    pending.status = 'PURCHASED';
    addEvent(state, order.orderId, '', 'CONFIRMED', 'Simulated order created after explicit approval.');
    state.sessions[sessionId] = { ...(state.sessions[sessionId] || {}), current_state: 'TRACKING', updated_at: new Date().toISOString() };
    await saveState(state);
    return { status: 200, body: envelope({ sessionId, state: 'TRACKING', responseType: 'order_confirmation', message: 'Your simulated hackathon order has been created successfully.', data: { order, timeline: timelineFor(state, order.orderId) } }) };
  }

  if (action === 'track_order') {
    const order = state.orders[body.order_id];
    if (!order) return { status: 404, body: envelope({ success: false, sessionId, state: 'TRACKING', responseType: 'error', message: 'Order not found.' }) };
    return { status: 200, body: envelope({ sessionId, state: 'TRACKING', responseType: 'tracking', message: 'Tracking loaded.', data: { order: normalizeOrder(order), timeline: timelineFor(state, body.order_id) } }) };
  }

  if (action === 'advance_order') {
    const order = state.orders[body.order_id];
    if (!order) return { status: 404, body: envelope({ success: false, sessionId, state: 'TRACKING', responseType: 'error', message: 'Order not found.' }) };
    const previous = order.trackingStatus;
    const next = normalizeOrder(advanceOrder(order));
    next.orderStatus = next.trackingStatus;
    next.updatedAt = new Date().toISOString();
    state.orders[body.order_id] = next;
    if (previous !== next.trackingStatus) addEvent(state, body.order_id, previous, next.trackingStatus, `Order status changed to ${next.trackingStatus.replaceAll('_', ' ').toLowerCase()}.`);
    await saveState(state);
    return { status: 200, body: envelope({ sessionId, state: 'TRACKING', responseType: 'tracking', message: `Order status advanced to ${next.trackingStatus}.`, data: { order: next, timeline: timelineFor(state, body.order_id) } }) };
  }

  if (action === 'cancel_order') {
    const order = state.orders[body.order_id];
    if (!order) return { status: 404, body: envelope({ success: false, sessionId, state: 'TRACKING', responseType: 'error', message: 'Order not found.' }) };
    if (['DELIVERED', 'CANCELLED', 'RETURNED', 'REFUNDED'].includes(order.orderStatus)) return { status: 409, body: envelope({ success: false, sessionId, state: 'TRACKING', responseType: 'error', message: 'This order cannot be cancelled in its current state.' }) };
    const previous = order.orderStatus;
    order.orderStatus = 'CANCELLED'; order.trackingStatus = 'CANCELLED'; order.updatedAt = new Date().toISOString();
    addEvent(state, body.order_id, previous, 'CANCELLED', 'Simulated order cancelled.');
    await saveState(state);
    return { status: 200, body: envelope({ sessionId, state: 'CANCELLED', responseType: 'tracking', message: 'The simulated order has been cancelled.', data: { order, timeline: timelineFor(state, body.order_id) } }) };
  }

  return { status: 400, body: envelope({ success: false, sessionId, state: 'NEW', responseType: 'error', message: `Unsupported action: ${action}` }) };
}

export function createApiHandler() {
  return async (req, res, next) => {
    if (req.method === 'OPTIONS') { res.writeHead(204, corsHeaders); res.end(); return; }
    const requestPath = (req.url || '').split('?')[0];
    if (req.method !== 'POST' || !requestPath.endsWith('/gateway')) { next?.(); return; }
    try {
      const body = await readJson(req);
      const result = await handleGateway(body);
      send(res, result.status, result.body);
    } catch (error) {
      send(res, 500, envelope({ success: false, state: 'NEW', responseType: 'error', message: error.message || 'Unexpected gateway error.' }));
    }
  };
}
