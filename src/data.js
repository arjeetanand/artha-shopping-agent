export const DEFAULT_INTENT = {
  category: 'Shopping',
  occasion: null,
  budget: null,
  location: null,
  arrive_by: null,
  arrive_by_days: null,
  must_have: [],
  nice_to_have: [],
  style: null,
  description: '',
  raw_text: '',
  extraction_source: null,
};

export const DEFAULT_RESULT = {
  search_id: null,
  intent: DEFAULT_INTENT,
  products: [],
  selected_product_ids: [],
  summary: { total: 0, item_count: 0, delivery_label: 'Run a live search to confirm delivery timing' },
  workflow: [
    { agent: 'Brief agent', status: 'idle', detail: 'Waiting for your shopping brief' },
    { agent: 'Location agent', status: 'idle', detail: 'Using your typed delivery location or optional permission' },
    { agent: 'Search agent', status: 'idle', detail: 'Waiting to query live retailer sources' },
    { agent: 'Evidence agent', status: 'idle', detail: 'Source evidence will appear after search' },
    { agent: 'Research agent', status: 'idle', detail: 'Parallel product-page checks will validate seller and review signals' },
    { agent: 'Analysis agent', status: 'idle', detail: 'Review and price signals will appear after search' },
    { agent: 'Decision agent', status: 'idle', detail: 'Ranked recommendations will appear after search' },
  ],
  conversation: [],
  source: { mode: 'idle', scrape: false },
};

export const SUGGESTED_SEARCHES = [
  'Linen shirt under ₹2,500',
  'Weekend outfit for Bengaluru',
  'Find something like this photo',
];

export const SHOPPING_THEMES = [
  {
    id: 'everyday',
    label: 'Everyday',
    kicker: 'THEME 01 // DAILY ROTATION',
    title: 'BREATHABLE STAPLES THAT HOLD UP ALL DAY',
    subtitle: 'Natural fabrics, honest stitching, and verified INR pricing across Indian retailers.',
    bg: '#034102',
    text: '#F4F3EF',
    accent: '#B6FE00',
    badgeBg: '#B6FE00',
    badgeText: '#034102',
    brief: 'Linen shirt under ₹2,500',
    occasion: 'Everyday casual',
    budget: '₹2,500',
    location: 'Bengaluru',
    image: '/assets/editorial-outfit-triptych.png',
    cutoutImage: '/assets/premium-white-sneaker.png',
    imageAlt: 'Breathable linen shirt, relaxed trousers, and everyday leather sneakers',
    priceTag: '₹2,190 · 3 retailers',
    verdictLabel: 'Evidence checked',
    annotation: 'Cool in traffic, sharp at coffee.',
    highlights: [
      '100% linen & cotton-linen weaves compared',
      'Checked delivery to Bengaluru 560001',
      'Direct links to Myntra, Uniqlo & FabIndia',
    ],
  },
  {
    id: 'work',
    label: 'Work',
    kicker: 'THEME 02 // DESK TO STUDIO',
    title: 'STRUCTURED WORKWEAR & STUDIO ESSENTIALS',
    subtitle: 'Tailored silhouettes and ergonomic workspace upgrades vetted for long hours and clear value.',
    bg: '#2E3EAC',
    text: '#F4F3EF',
    accent: '#B6FE00',
    badgeBg: '#B6FE00',
    badgeText: '#034102',
    brief: 'Office-ready neutral outfit under ₹8,000 for Bengaluru',
    occasion: 'Work & office',
    budget: '₹8,000',
    location: 'Bengaluru',
    image: '/assets/neutral-office-chair-fallback.png',
    cutoutImage: '/assets/editorial-outfit-triptych.png',
    imageAlt: 'Structured neutral workwear and ergonomic studio chair',
    priceTag: '₹6,490 · 4 retailers',
    verdictLabel: 'Evidence checked',
    annotation: 'Zero guesswork before Monday.',
    highlights: [
      'Size availability & return window verified',
      'Price history tracked across 4 stores',
      'Missing fabric composition flagged upfront',
    ],
  },
  {
    id: 'occasion',
    label: 'Occasion',
    kicker: 'THEME 03 // EVENING & FESTIVE',
    title: 'DRESSED FOR THE MOMENT, ON YOUR TIMELINE',
    subtitle: 'Festive kurtas, dinner layers, and statement footwear filtered by arrival deadline.',
    bg: '#FF7B5F',
    text: '#034102',
    accent: '#F4F3EF',
    badgeBg: '#034102',
    badgeText: '#B6FE00',
    brief: 'Festive silk-blend kurta set under ₹5,500 delivered to Bengaluru within 4 days',
    occasion: 'Wedding & dinner',
    budget: '₹5,500',
    location: 'Bengaluru',
    image: '/assets/editorial-outfit-triptych.png',
    cutoutImage: '/assets/premium-white-sneaker.png',
    imageAlt: 'Evening occasion outfit curation with footwear and fabric notes',
    priceTag: '₹4,850 · Arrives in 3d',
    verdictLabel: 'Verify first',
    annotation: 'Checks dispatch cutoffs before you commit.',
    highlights: [
      'Strict arrival-date filtering for events',
      'Highlights exact vs. visual-match alternatives',
      'Flags unconfirmed express shipping claims',
    ],
  },
  {
    id: 'travel',
    label: 'Travel',
    kicker: 'THEME 04 // WEEKEND & TRANSIT',
    title: 'PACKABLE LAYERS FOR BENGALURU WEEKENDS',
    subtitle: 'Wrinkle-resistant overshirts, versatile sneakers, and light carryalls built for quick getaways.',
    bg: '#50CBFF',
    text: '#034102',
    accent: '#FA8005',
    badgeBg: '#FA8005',
    badgeText: '#F4F3EF',
    brief: 'Weekend outfit for Bengaluru',
    occasion: 'Weekend trip',
    budget: '₹4,500',
    location: 'Bengaluru',
    image: '/assets/premium-white-sneaker.png',
    cutoutImage: '/assets/editorial-outfit-triptych.png',
    imageAlt: 'Packable travel sneaker and weekend layers for Bengaluru',
    priceTag: '₹3,290 · 2-day delivery',
    verdictLabel: 'Evidence checked',
    annotation: 'One bag, three outfits, research done.',
    highlights: [
      'Multi-item outfit budget allocation',
      'Cross-retailer lowest offer comparison',
      'One-click handoff to each merchant page',
    ],
  },
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
  if (text.length < 15) return 'Retailer source. Confirm current price and stock on store page.';
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
