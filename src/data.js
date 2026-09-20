export const OUTFIT_IMAGE = '/assets/editorial-outfit-triptych.png';

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

export const DEFAULT_PRODUCTS = [
  {
    id: 'linen-overshirt', name: 'Linen blend overshirt', category: 'Top', description: 'Relaxed fit • Breathable linen blend • Sand', seller: 'Myntra', price: 3499, rating: 4.6, delivery_days: 3, delivery_label: 'Arrives Thu', stock: 12, features: ['breathable', 'linen', 'office-ready', 'neutral'], crop_index: 0, image: OUTFIT_IMAGE, url: 'https://www.myntra.com/', source_kind: 'local_catalog', source_label: 'Local development catalog', evidence: ['Local development catalog', 'Delivery is estimated'], match_score: 96, reason_tags: ['AI match', 'Local development data'],
  },
  {
    id: 'cotton-trousers', name: 'Straight-fit cotton trousers', category: 'Bottom', description: 'Mid rise • 100% cotton • Beige', seller: 'AJIO', price: 2699, rating: 4.5, delivery_days: 4, delivery_label: 'Arrives Fri', stock: 18, features: ['cotton', 'straight-fit', 'office-ready', 'neutral'], crop_index: 1, image: OUTFIT_IMAGE, url: 'https://www.ajio.com/', source_kind: 'local_catalog', source_label: 'Local development catalog', evidence: ['Local development catalog', 'Delivery is estimated'], match_score: 94, reason_tags: ['AI match', 'Local development data'],
  },
  {
    id: 'leather-loafers', name: 'Leather penny loafers', category: 'Shoes', description: 'Genuine leather • Classic fit • Dark brown', seller: 'Tata CLiQ', price: 4999, rating: 4.4, delivery_days: 2, delivery_label: 'Arrives Wed', stock: 7, features: ['leather', 'classic', 'office-ready', 'durable'], crop_index: 2, image: OUTFIT_IMAGE, url: 'https://www.tatacliq.com/', source_kind: 'local_catalog', source_label: 'Local development catalog', evidence: ['Local development catalog', 'Delivery is estimated'], match_score: 91, reason_tags: ['AI match', 'Local development data'],
  },
];

export const DEFAULT_RESULT = {
  search_id: 'local-seed', intent: DEFAULT_INTENT, products: DEFAULT_PRODUCTS, selected_product_ids: DEFAULT_PRODUCTS.map((product) => product.id), summary: { total: DEFAULT_PRODUCTS.reduce((total, product) => total + product.price, 0), item_count: DEFAULT_PRODUCTS.length, delivery_label: 'All known deliveries arrive by Fri' }, workflow: [
    { agent: 'Brief agent', status: 'local', detail: 'Local rules prepared the starting brief' },
    { agent: 'Search agent', status: 'local', detail: 'Local development catalog is ready until a live search runs' },
    { agent: 'Evidence agent', status: 'local', detail: 'Local records label estimated information' },
    { agent: 'Decision agent', status: 'complete', detail: 'Ranked by fit, budget, delivery, and source evidence' },
  ], source: { mode: 'local', scrape: false },
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

export function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

