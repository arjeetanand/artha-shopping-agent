import { createHash } from 'node:crypto';

export const RETAILERS = {
  amazon: {
    orders: 'https://www.amazon.in/gp/your-account/order-history?orderFilter=months-6',
    domain: 'amazon.in', cards: '.order-card, .js-order-card',
    details: 'a[href*="order-details"], a[href*="order-summary"], a[href*="orderID="]',
    items: '[data-component="item"], .shipment, .order-card, .js-order-card',
    products: 'a[href*="/dp/"], a[href*="/gp/product/"]',
    next: 'li.a-last:not(.a-disabled) a, a[aria-label="Next page"]',
  },
  flipkart: {
    orders: 'https://www.flipkart.com/account/orders', domain: 'flipkart.com',
    cards: '[data-testid="order-card"], [data-id^="OD"]',
    details: 'a[href*="order_details"], a[href*="orderId="]',
    items: '[data-testid="order-details"], [data-testid="order-card"], main',
    products: 'a[href*="/p/itm"]', next: 'a[rel="next"], button:has-text("Load More")',
  },
  myntra: {
    orders: 'https://www.myntra.com/my/orders', domain: 'myntra.com',
    cards: '[class*="order-card"], [class*="orderCard"], [data-testid="order-card"]',
    details: 'a[href*="/my/orders/"], a[href*="order-details"]',
    items: '[class*="order-details"], [class*="orderDetails"], [class*="order-card"], main',
    products: 'a[href*="/buy"]', next: 'a[rel="next"], button:has-text("Load More")',
  },
  ajio: {
    orders: 'https://www.ajio.com/my-account/orders', domain: 'ajio.com',
    cards: '[class*="order-card"], [class*="orderCard"], [class*="order-list"]',
    details: 'a[href*="order-details"], a[href*="orderDetails"]',
    items: '[class*="order-detail"], [class*="orderDetail"], [class*="order-item"], main',
    products: 'a[href*="/p/"]', next: 'a[rel="next"], button:has-text("Load More")',
  },
};

export function retailerUrl(value, provider) {
  try {
    const url = new URL(value);
    const domain = RETAILERS[provider]?.domain;
    return url.protocol === 'https:' && !url.username && !url.password && !url.port && domain
      && (url.hostname === domain || url.hostname.endsWith(`.${domain}`));
  } catch { return false; }
}

export function historyUrls(provider, cutoff, until) {
  if (provider !== 'amazon') return [RETAILERS[provider].orders];
  const years = [];
  for (let year=Number(until.slice(0,4));year>=Number(cutoff.slice(0,4));year--) years.push(year);
  return years.map(year=>`https://www.amazon.in/gp/your-account/order-history?orderFilter=year-${year}`);
}

export function parseMoney(value) {
  const match = String(value || '').match(/(?:₹|INR|Rs\.?)[ \t]*([\d,]+(?:\.\d{1,2})?)/i);
  if (!match) return null;
  const number = Number(match[1].replaceAll(',', ''));
  return Number.isFinite(number) && number >= 0 ? number : null;
}

export function parseOrderDate(value) {
  const text = String(value || '').trim().replace(/\b(\d+)(?:st|nd|rd|th)\b/gi,'$1');
  let match = text.match(/\b(20\d{2})-(\d{2})-(\d{2})\b/);
  if (match) return validDate(+match[1], +match[2], +match[3]);
  match = text.match(/\b(\d{1,2})[\/.-](\d{1,2})[\/.-](20\d{2})\b/);
  if (match) return validDate(+match[3], +match[2], +match[1]);
  const months = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
  match = text.match(/\b(\d{1,2})\s+([A-Za-z]+)[,\s]+(20\d{2})\b/);
  if (match) return validDate(+match[3], months.indexOf(match[2].slice(0,3).toLowerCase()) + 1, +match[1]);
  match = text.match(/\b([A-Za-z]+)\s+(\d{1,2})[,\s]+(20\d{2})\b/);
  return match ? validDate(+match[3], months.indexOf(match[1].slice(0,3).toLowerCase()) + 1, +match[2]) : null;
}

function validDate(year, month, day) {
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
    ? date.toISOString().slice(0,10) : null;
}

function category(name) {
  if (/\b(shoes?|sneakers?|sandals?|boots?|footwear)\b/i.test(name)) return 'Footwear';
  if (/\b(shirts?|t-?shirts?|tops?|dresses?|kurtas?|jackets?|hoodies?)\b/i.test(name)) return 'Clothing';
  if (/\b(jeans|trousers?|pants?|shorts?)\b/i.test(name)) return 'Bottoms';
  return '';
}

export function parseOrderEvidence(snapshot, provider) {
  if (!retailerUrl(snapshot.url, provider)) throw new Error('Order page is outside the selected retailer');
  const text = String(snapshot.text || '');
  const url = new URL(snapshot.url);
  const id = snapshot.orderId || url.searchParams.get('orderID') || url.searchParams.get('order_id')
    || url.searchParams.get('orderId') || text.match(/\b\d{3}-\d{7}-\d{7}\b/)?.[0]
    || url.searchParams.get('orderCode') || url.pathname.match(/\/(?:my\/orders|order-details)\/([A-Z0-9-]{6,50})\/?$/i)?.[1]
    || text.match(/\bOD\d{10,30}\b/)?.[0]
    || text.match(/Order\s*(?:ID|Number|No\.?|#)\s*[:#-]?\s*([A-Z0-9-]{6,40})/i)?.[1];
  const dateText = snapshot.orderDate || text.match(/(?:order\s*(?:placed|date)|placed\s*on|ordered\s*on)\s*[:\n]?\s*([^\n]{4,45})/i)?.[1];
  const orderDate = parseOrderDate(dateText);
  if (!id || !orderDate) return {error: !id ? 'order_id_missing' : 'order_date_missing'};
  const items = [];
  const seen = new Set();
  for (const product of snapshot.products || []) {
    const name = String(product.name || '').replace(/\s+/g,' ').trim();
    if (name.length < 4 || !retailerUrl(product.url, provider) || seen.has(product.url)) continue;
    seen.add(product.url);
    const itemText = String(product.text || '');
    items.push({name, url: product.url, brand: product.brand || '', category: category(name),
      size: itemText.match(/\bSize\s*[:=-]\s*([^\n,|]{1,20})/i)?.[1]?.trim() || '',
      color: itemText.match(/\bColou?r\s*[:=-]\s*([^\n,|]{1,30})/i)?.[1]?.trim() || '',
      price: parseMoney(product.price || ''), quantity: Number(product.quantity) > 0 ? Number(product.quantity) : null});
  }
  if (!items.length) return {error:'order_items_missing', id, order_date:orderDate};
  const totalText = text.match(/(?:grand\s*total|order\s*total|total\s*amount|total\s*paid)\s*[:\n]?\s*((?:₹|INR|Rs\.?)[\s\d,.]+)/i)?.[1];
  return {id, order_date:orderDate, total:parseMoney(totalText), currency:'INR', items,
    status:text.match(/(?:^|\n)\s*(delivered|cancelled|canceled|returned|refunded|shipped|dispatched)\b/i)?.[1]?.toLowerCase() || 'unknown',
    location:snapshot.deliveryLocation || '', source_url:snapshot.url, evidence_hash:createHash('sha256').update(text).digest('hex')};
}

function inrAmount(money) {
  const entry = (money?.amountValueMultiCurrency || []).find(value => value?.currency === 'INR');
  const amount = Number(entry?.inrValue ?? money?.amount ?? money?.totalPayable);
  return Number.isFinite(amount) && amount >= 0 ? amount : null;
}

function flipkartProductUrl(product) {
  const path = product?.productAttribute?.storePath || product?.productBasicData?.url;
  if (typeof path !== 'string' || !path.trim()) return '';
  try {
    const url = new URL(path, 'https://www.flipkart.com');
    return retailerUrl(url.href, 'flipkart') ? url.href : '';
  } catch { return ''; }
}

export function parseFlipkartOrder(record) {
  const meta = record?.orderMetaData || {};
  const id = String(meta.orderId || '').trim();
  if (!/^[A-Za-z0-9-]{8,160}$/.test(id)) return {error:'order_id_missing'};
  const rawTimestamp = Number(meta.orderDate);
  const timestamp = rawTimestamp > 1e12 ? rawTimestamp : rawTimestamp * 1000;
  const date = new Date(timestamp);
  if (!Number.isFinite(timestamp) || Number.isNaN(date.getTime())) return {error:'order_date_missing', id};
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone:'Asia/Kolkata', year:'numeric', month:'2-digit', day:'2-digit',
  }).formatToParts(date).map(part => [part.type, part.value]));
  const orderDate = validDate(+parts.year, +parts.month, +parts.day);
  if (!orderDate) return {error:'order_date_missing', id};

  const products = record.productDataBag || {};
  const items = [];
  for (const unit of Object.values(record.units || {})) {
    const product = products[unit?.metaData?.fsn];
    const basic = product?.productBasicData || {};
    const attributes = product?.productAttribute || {};
    const name = String(basic.title || '').replace(/\s+/g, ' ').trim();
    const url = flipkartProductUrl(product);
    if (name.length < 4 || !url) continue;
    const quantity = Number(unit?.metaData?.quantity);
    items.push({name, url, brand:String(attributes.brand || ''), category:category(name),
      size:String(attributes.size || ''), color:String(attributes.color || ''),
      price:inrAmount(unit?.moneyDataBag), quantity:Number.isFinite(quantity) && quantity > 0 ? quantity : null});
  }
  if (!items.length) return {error:'order_items_missing', id, order_date:orderDate};

  const statuses = [...new Set(Object.values(record.units || {})
    .map(unit => String(unit?.metaData?.status?.key || '').toLowerCase()).filter(Boolean))];
  const status = statuses.length === 1
    ? ({delivered:'delivered', cancelled:'cancelled', canceled:'cancelled', shipped:'shipped', purchased:'purchased', ofd:'out_for_delivery'}[statuses[0]] || 'unknown')
    : 'unknown';
  const total = inrAmount(record.orderMoneyDataBag);
  const evidence = {id, order_date:orderDate, total, items, status};
  return {...evidence, currency:'INR', source_url:RETAILERS.flipkart.orders,
    evidence_hash:createHash('sha256').update(JSON.stringify(evidence)).digest('hex')};
}

export function parseFlipkartOrderPage(payload) {
  const view = payload?.RESPONSE?.multipleOrderDetailsView;
  if (!Array.isArray(view?.orders)) return {error:'orders_payload_missing'};
  const orders = [], errors = [];
  for (const record of view.orders) {
    const order = parseFlipkartOrder(record);
    if (order.error) errors.push(order.error);
    else orders.push(order);
  }
  return {orders, orderCount:view.orders.length, moreOrder:Boolean(view.moreOrder), errors};
}
