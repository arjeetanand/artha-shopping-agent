const today = new Date('2026-09-20T09:00:00+05:30');

const outfitParts = [
  {
    id: 'shirt-sand-01',
    title: 'Relaxed linen-look shirt',
    category: 'shirt',
    brand: 'Morrow / Demo',
    price: 1790,
    stock: 18,
    deliveryDays: 3,
    rating: 4.7,
    sellerReliability: 96,
    tags: ['oat', 'relaxed fit', 'linen-look', 'breathable'],
  },
  {
    id: 'shirt-clay-02',
    title: 'Clay camp-collar shirt',
    category: 'shirt',
    brand: 'Morrow / Demo',
    price: 1690,
    stock: 11,
    deliveryDays: 4,
    rating: 4.6,
    sellerReliability: 94,
    tags: ['clay', 'relaxed fit', 'textured', 'breathable'],
  },
  {
    id: 'shirt-cloud-03',
    title: 'Cloud cotton overshirt',
    category: 'shirt',
    brand: 'Common Thread / Demo',
    price: 1590,
    stock: 24,
    deliveryDays: 5,
    rating: 4.5,
    sellerReliability: 91,
    tags: ['cream', 'oversized', 'cotton', 'lightweight'],
  },
  {
    id: 'trouser-sand-01',
    title: 'Pleated relaxed trousers',
    category: 'trousers',
    brand: 'Morrow / Demo',
    price: 1890,
    stock: 9,
    deliveryDays: 3,
    rating: 4.8,
    sellerReliability: 96,
    tags: ['sand', 'relaxed fit', 'pleated', 'linen-blend'],
  },
  {
    id: 'trouser-clay-02',
    title: 'Easy drape drawstring trouser',
    category: 'trousers',
    brand: 'Coastline / Demo',
    price: 1990,
    stock: 14,
    deliveryDays: 4,
    rating: 4.6,
    sellerReliability: 93,
    tags: ['stone', 'relaxed fit', 'drape', 'travel-ready'],
  },
  {
    id: 'trouser-cloud-03',
    title: 'Soft cotton travel trouser',
    category: 'trousers',
    brand: 'Common Thread / Demo',
    price: 1790,
    stock: 21,
    deliveryDays: 5,
    rating: 4.4,
    sellerReliability: 90,
    tags: ['cream', 'straight fit', 'cotton', 'easy-care'],
  },
  {
    id: 'shoe-cloud-01',
    title: 'Cloud court sneaker',
    category: 'shoes',
    brand: 'Northstar / Demo',
    price: 1390,
    stock: 16,
    deliveryDays: 3,
    rating: 4.7,
    sellerReliability: 95,
    tags: ['cream', 'minimal', 'cushioned', 'leather-look'],
  },
  {
    id: 'shoe-canvas-02',
    title: 'Canvas low-top sneaker',
    category: 'shoes',
    brand: 'Common Thread / Demo',
    price: 1490,
    stock: 8,
    deliveryDays: 4,
    rating: 4.6,
    sellerReliability: 93,
    tags: ['ivory', 'minimal', 'canvas', 'lightweight'],
  },
  {
    id: 'shoe-caramel-03',
    title: 'Caramel leather court shoe',
    category: 'shoes',
    brand: 'Heritage / Demo',
    price: 1390,
    stock: 5,
    deliveryDays: 5,
    rating: 4.3,
    sellerReliability: 89,
    tags: ['cream', 'retro', 'cushioned', 'textured'],
  },
];

const officeChairs = [
  {
    id: 'chair-lumbar-01',
    title: 'Aeron-style lumbar task chair',
    category: 'office chair',
    brand: 'Workwell / Demo',
    price: 8990,
    shipping: 299,
    stock: 7,
    deliveryDays: 4,
    rating: 4.8,
    sellerReliability: 97,
    tags: ['adjustable lumbar', 'mesh back', 'ergonomic', 'tilt lock'],
  },
  {
    id: 'chair-foam-02',
    title: 'Contour foam support chair',
    category: 'office chair',
    brand: 'Posture Lab / Demo',
    price: 10490,
    shipping: 199,
    stock: 12,
    deliveryDays: 5,
    rating: 4.6,
    sellerReliability: 94,
    tags: ['back support', 'foam seat', 'height adjustable', 'quiet wheels'],
  },
  {
    id: 'chair-basic-03',
    title: 'Everyday mesh work chair',
    category: 'office chair',
    brand: 'Deskday / Demo',
    price: 6990,
    shipping: 249,
    stock: 16,
    deliveryDays: 6,
    rating: 4.2,
    sellerReliability: 88,
    tags: ['mesh back', 'basic lumbar', 'height adjustable'],
  },
];

const headphones = [
  {
    id: 'headphones-wave-01',
    title: 'Wave ANC wireless headphones',
    category: 'headphones',
    brand: 'Sonicraft / Demo',
    price: 6990,
    shipping: 149,
    stock: 9,
    deliveryDays: 10,
    rating: 4.7,
    sellerReliability: 95,
    tags: ['noise cancelling', 'wireless', 'fast charge'],
  },
  {
    id: 'headphones-studio-02',
    title: 'Studio fold wireless headphones',
    category: 'headphones',
    brand: 'Sonicraft / Demo',
    price: 5490,
    shipping: 99,
    stock: 13,
    deliveryDays: 2,
    rating: 4.5,
    sellerReliability: 93,
    tags: ['wireless', 'foldable', 'fast charge'],
  },
];

const INR = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });

export const formatINR = (value) => INR.format(value);

const addDays = (date, days) => {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
};

const formatDate = (date) => new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }).format(date);

export const makeSessionId = () => `sess_${Math.random().toString(36).slice(2, 8)}_${Date.now().toString(36).slice(-4)}`;

export function analyzeRequest({ message = '', hasImage = false }) {
  const text = message.toLowerCase();
  const isChair = text.includes('chair') || text.includes('back support');
  const isHeadphones = text.includes('headphone');
  const isOutfit = hasImage || text.includes('outfit') || text.includes('shirt') || text.includes('trouser');
  const budgetMatch = message.match(/(?:under|below|max(?:imum)?|within)\s*(?:₹|rs\.?\s*)?([\d,]+)/i);
  const daysMatch = message.match(/(?:within|in|under)\s*(\d+)\s*days?/i);
  const budget = budgetMatch ? Number(budgetMatch[1].replace(/,/g, '')) : isOutfit ? 6000 : isChair ? 12000 : isHeadphones ? 10000 : null;
  const maxDeliveryDays = daysMatch ? Number(daysMatch[1]) : isOutfit ? 5 : isChair ? 5 : isHeadphones ? 3 : null;

  if (isChair) {
    return {
      productCategory: 'office chair', purchaseMode: 'single_product', budget, maxDeliveryDays,
      style: ['ergonomic', 'supportive'], colors: ['black', 'graphite'], occasion: 'work from home',
      visualAttributes: [], mustHave: ['good back support'], queryLabel: 'ergonomic office chairs',
    };
  }
  if (isHeadphones) {
    return {
      productCategory: 'headphones', purchaseMode: 'single_product', budget, maxDeliveryDays,
      style: ['everyday tech'], colors: [], occasion: 'daily listening', visualAttributes: [],
      mustHave: [], queryLabel: 'wireless headphones',
    };
  }
  return {
    productCategory: 'travel outfit', purchaseMode: 'outfit_bundle', budget, maxDeliveryDays,
    style: ['relaxed', 'minimal', 'linen-like'], colors: ['oat', 'sand', 'cream'], occasion: 'Goa trip',
    visualAttributes: ['oversized shirt', 'pleated relaxed trousers', 'low-profile sneaker'],
    mustHave: ['coordinated look', 'breathable feel'], queryLabel: 'relaxed neutral travel outfit',
  };
}

export function buildUnderstanding({ analysis, message, hasImage }) {
  return {
    ...analysis,
    description: message || 'A neutral, relaxed travel outfit inspired by the uploaded image.',
    provenance: {
      userProvided: message ? ['Goa trip', 'Bangalore delivery'] : ['Uploaded inspiration image'],
      aiInferred: hasImage ? ['relaxed silhouette', 'oat / sand palette', 'linen-like texture', 'minimal sneakers'] : analysis.style,
      verified: [], simulated: [],
    },
  };
}

function productTotal(item) {
  return item.price + (item.shipping ?? 0);
}

function scoreSingle(item, analysis) {
  const fit = item.tags.some((tag) => analysis.mustHave.some((need) => tag.includes(need.split(' ')[0]))) ? 34 : 27;
  const delivery = analysis.maxDeliveryDays && item.deliveryDays <= analysis.maxDeliveryDays ? 20 : 0;
  const seller = Math.round((item.rating / 5) * 7 + (item.sellerReliability / 100) * 8);
  const budget = analysis.budget ? Math.max(0, Math.round(15 * (1 - productTotal(item) / analysis.budget))) : 10;
  const preference = item.tags.some((tag) => analysis.style.some((style) => tag.includes(style.split('-')[0]))) ? 9 : 5;
  const total = Math.min(99, fit + delivery + seller + budget + preference + 5);
  return { score: total, scoreBreakdown: { specificationFit: fit, delivery, sellerQuality: seller, budgetValue: budget, preferences: preference, returnPolicy: 5 } };
}

export function searchAndRank(analysis) {
  if (analysis.purchaseMode === 'outfit_bundle') {
    const bundles = [
      { id: 'bundle-sandstone', title: 'The Sandstone Set', partIds: ['shirt-sand-01', 'trouser-sand-01', 'shoe-cloud-01'], deliveryDays: 3, score: 94, badge: 'BEST STYLE MATCH', badgeTone: 'accent', why: ['The oatmeal shirt and pleated trouser echo the image’s relaxed silhouette.', 'All three pieces arrive within your 5-day Bangalore window.', 'The set stays ₹781 below the demo budget.'] },
      { id: 'bundle-coast', title: 'The Coastline Set', partIds: ['shirt-clay-02', 'trouser-clay-02', 'shoe-canvas-02'], deliveryDays: 4, score: 90, badge: 'BEST VALUE', badgeTone: 'sage', why: ['Warm clay and stone tones keep the same sun-washed palette.', 'The seller reliability score is 94%+ across every item.', 'Comfortable, travel-ready fabrics keep this as the lighter pack.'] },
      { id: 'bundle-everyday', title: 'The Everyday Set', partIds: ['shirt-cloud-03', 'trouser-cloud-03', 'shoe-caramel-03'], deliveryDays: 5, score: 86, badge: 'FASTEST DELIVERY', badgeTone: 'blue', why: ['The cleanest low-contrast match for a minimal travel wardrobe.', 'Every item is in stock and the bundle remains under budget.', 'Estimated delivery lands on September 25 in Bangalore.'] },
    ];
    return bundles.map((bundle) => {
      const items = bundle.partIds.map((id) => outfitParts.find((item) => item.id === id));
      const subtotal = items.reduce((sum, item) => sum + item.price, 0);
      const shipping = 149;
      const totalCost = subtotal + shipping;
      const eligible = (!analysis.budget || totalCost <= analysis.budget) && (!analysis.maxDeliveryDays || bundle.deliveryDays <= analysis.maxDeliveryDays) && items.every((item) => item.stock > 0);
      return { ...bundle, items, subtotal, shipping, totalCost, eligible, currency: 'INR', deliveryDate: formatDate(addDays(today, bundle.deliveryDays)), provenance: { verified: ['Stock', 'Rating', 'Seller reliability'], simulated: ['INR demo price', 'Shipping', 'Delivery estimate'], aiInferred: ['Style similarity', 'Palette match'] } };
    }).filter((bundle) => bundle.eligible);
  }

  const catalog = analysis.productCategory === 'office chair' ? officeChairs : headphones;
  return catalog.map((item) => {
    const shipping = item.shipping ?? 199;
    const candidate = { ...item, shipping };
    const totalCost = productTotal(candidate);
    const deliveryPass = !analysis.maxDeliveryDays || item.deliveryDays <= analysis.maxDeliveryDays;
    const budgetPass = !analysis.budget || totalCost <= analysis.budget;
    const stockPass = item.stock > 0;
    const { score, scoreBreakdown } = scoreSingle(candidate, analysis);
    return { ...candidate, totalCost, eligible: deliveryPass && budgetPass && stockPass, deliveryPass, budgetPass, stockPass, score, scoreBreakdown, deliveryDate: formatDate(addDays(today, item.deliveryDays)), provenance: { verified: ['Stock', 'Rating', 'Seller reliability'], simulated: ['Shipping', 'Delivery estimate'], aiInferred: ['Specification fit'] } };
  }).filter((item) => item.eligible).sort((a, b) => b.score - a.score).slice(0, 3);
}

export function getRejected(analysis) {
  const catalog = analysis.productCategory === 'headphones' ? headphones : analysis.productCategory === 'office chair' ? officeChairs : [];
  return catalog.map((item) => {
    if (analysis.maxDeliveryDays && item.deliveryDays > analysis.maxDeliveryDays) return { ...item, reason: `Rejected — ${item.deliveryDays} day delivery exceeds your ${analysis.maxDeliveryDays}-day limit.` };
    if (analysis.budget && productTotal({ ...item, shipping: item.shipping ?? 199 }) > analysis.budget) return { ...item, reason: `Rejected — total is ${formatINR(productTotal({ ...item, shipping: item.shipping ?? 199 }))}, above your ${formatINR(analysis.budget)} limit.` };
    return null;
  }).filter(Boolean);
}

export function createApproval(recommendation, sessionId) {
  return {
    approvalToken: `appr_${Math.random().toString(36).slice(2, 10)}`,
    recommendationId: recommendation.id,
    sessionId,
    status: 'PENDING_CONFIRMATION',
    expiresAt: '20 minutes',
    selected: recommendation,
  };
}

export function createOrder(approval) {
  const suffix = Math.random().toString(36).slice(2, 8).toUpperCase();
  const itemCount = approval.selected.items?.length ?? 1;
  return {
    orderId: `INSP-20260920-${suffix}`,
    orderStatus: 'CONFIRMED', paymentStatus: 'MOCK_PAID', trackingStatus: 'CONFIRMED',
    total: approval.selected.totalCost, currency: 'INR', estimatedDelivery: approval.selected.deliveryDate,
    items: approval.selected.items ?? [approval.selected], itemCount, createdAt: '20 Sep 2026, 09:42',
    lastNotifiedStatus: 'CONFIRMED',
  };
}

export const trackingSteps = [
  { key: 'CONFIRMED', label: 'Confirmed', note: 'Demo order created' },
  { key: 'PROCESSING', label: 'Processing', note: 'Seller is preparing your items' },
  { key: 'PACKED', label: 'Packed', note: 'Packed and ready to leave the seller' },
  { key: 'SHIPPED', label: 'Shipped', note: 'On the way to Bangalore' },
  { key: 'OUT_FOR_DELIVERY', label: 'Out for delivery', note: 'Arriving today' },
  { key: 'DELIVERED', label: 'Delivered', note: 'Delivered to your address' },
];

export function advanceOrder(order) {
  const index = trackingSteps.findIndex((step) => step.key === order.trackingStatus);
  const next = trackingSteps[Math.min(index + 1, trackingSteps.length - 1)];
  return { ...order, trackingStatus: next.key, lastNotifiedStatus: next.key };
}
