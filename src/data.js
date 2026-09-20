export const DEFAULT_INTENT = {
  category: 'Fashion',
  occasion: 'Office',
  budget: 18000,
  location: 'Bengaluru',
  arrive_by: 'within 5 days',
  arrive_by_days: 5,
  must_have: ['breathable fabrics', 'neutral palette', 'office-ready'],
  nice_to_have: ['durable', 'easy to layer'],
  style: 'quietly considered',
  description: 'An office-ready look under ₹18,000',
  raw_text: 'Find an office-ready look under ₹18,000',
  extraction_source: 'local rules',
};

export const DEFAULT_RESULT = {
  search_id: null,
  intent: DEFAULT_INTENT,
  products: [],
  selected_product_ids: [],
  summary: { total: 0, item_count: 0, delivery_label: 'Run a live search to confirm delivery timing' },
  workflow: [
    { agent: 'Brief agent', status: 'idle', detail: 'Waiting for your shopping brief' },
    { agent: 'Search agent', status: 'idle', detail: 'Waiting to query live retailer sources' },
    { agent: 'Evidence agent', status: 'idle', detail: 'Source evidence will appear after search' },
    { agent: 'Analysis agent', status: 'idle', detail: 'Review and price signals will appear after search' },
    { agent: 'Decision agent', status: 'idle', detail: 'Ranked recommendations will appear after search' },
  ],
  source: { mode: 'idle', scrape: false },
};

export const SUGGESTED_SEARCHES = [
  'Office-ready neutral outfit under ₹18,000',
  'Breathable linen overshirts under ₹4,000',
  'Minimalist leather loafers for work',
  'Relaxed weekend cotton wear under ₹8,000',
];

export function sanitizeTitle(rawTitle = '') {
  if (!rawTitle) return 'Retailer Item';
  let title = String(rawTitle).replace(/[\r\n\t]+/g, ' ').replace(/\s{2,}/g, ' ').trim();
  // Strip common noisy prefix patterns
  title = title.replace(/^(?:Buy|Shop\s+for|Shop\s+Best|Shop)\s+/i, '');
  title = title.replace(/\s*\|\s*.*$/i, ''); // Strip | Store Name
  title = title.replace(/\s*[–-]\s*(?:CHAWLA|Laminoor|Grlboss|Saanvari|Gillori|Indelan|Asankhrang|Keerto|Amazon|Myntra|Tata|AJIO|Linen\s*Trail|Linenwear).*$/i, '');
  title = title.replace(/\s*Archives\s*[-–]?\s*.*$/i, '');
  title = title.replace(/^(?:Collection:\s*|Products\s+tagged\s*|All\s*[-–]\s*)/i, '');
  title = title.replace(/\s*Skip\s+to\s+content.*$/i, '');
  title = title.replace(/Active\s+filters:.*$/i, '');
  title = title.replace(/\s*Online\s+(?:in|at)\s+India.*$/i, '');
  title = title.trim().replace(/[-–•|]+$/, '').trim();
  if (!title || title.length < 3) return String(rawTitle).slice(0, 50);
  return title.slice(0, 75);
}

export function sanitizeSnippet(rawSnippet = '') {
  if (!rawSnippet) return 'Verified retailer item with live availability and pricing.';
  let text = String(rawSnippet).replace(/[\r\n\t]+/g, ' ').trim();
  text = text.replace(/Skip\s+to\s+content/gi, '');
  text = text.replace(/Active\s+filters:[^.]*/gi, '');
  text = text.replace(/Launch\s+Offer[^.]*till\s+[\w\s\d]+/gi, '');
  text = text.replace(/Welcome\s+To\s+[^.]*/gi, '');
  text = text.replace(/Loading\s+Skip\s+to\s+content/gi, '');
  text = text.replace(/COD\s+free\s+across\s+India/gi, '');
  text = text.replace(/WE\s+SHIP\s+WORLDWIDE/gi, '');
  text = text.replace(/Shop\s+By\s+Category[^.]*/gi, '');
  text = text.replace(/[「][^」]*[」]/g, '');
  text = text.replace(/\*\s*(?:Home|Clothing|Shirts|Search|Sign in|Favourites|Shopping bag)[^*]*/gi, '');
  text = text.replace(/\s{2,}/g, ' ').trim();
  if (text.length < 15) return 'Verified retailer source. Confirm current price and stock on store page.';
  return text.length > 140 ? `${text.slice(0, 137)}…` : text;
}

export function formatPrice(value) {
  const price = Number(value || 0);
  return price > 0 ? `₹${price.toLocaleString('en-IN')}` : 'Check retailer';
}

export function productTotal(product = {}) {
  const total = Number(product.line_total ?? product.total_price ?? product.price ?? 0);
  return Number.isFinite(total) ? total : 0;
}

export function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}
