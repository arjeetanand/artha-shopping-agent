import React, { useState, useMemo } from 'react';
import { Icon } from './Icon';
import { Card3D } from './Card3D';

export const DEMO_BAGS = [
  {
    id: 'bag-japan-2026',
    title: 'Japan Trip 2026',
    subtitle: 'Track travel purchases, organize trip essentials, and manage everything you need',
    briefQuery: 'Japan travel essentials: lightweight linen daypack, vintage 35mm rangefinder camera, custom leather passport case under ₹2,00,000',
    color: '#F8D148',
    colorLight: '#FFF8D6',
    textColor: '#8C6C00',
    itemCount: '8 of 12 items',
    totalPrice: '₹1,87,300',
    numericTotal: 187300,
    stickers: ['⛩️', '👒', '📷', '🌸'],
    status: 'active',
    items: [
      { id: 'j1', name: 'Handcrafted Linen Tokyo Daypack', seller: 'Etsy', price: 8200, delivery: 'Arrives in 4 days', iconColor: '#F16521' },
      { id: 'j2', name: 'Vintage 35mm Rangefinder Camera', seller: 'eBay', price: 14900, delivery: 'Arrives in 6 days', iconColor: '#0064D2' },
      { id: 'j3', name: 'Custom Travel Leather Passport Case', seller: 'Zazzle', price: 2490, delivery: 'Express dispatch', iconColor: '#111111' },
    ],
  },
  {
    id: 'bag-school-desk',
    title: 'Workstation & Desk 2026',
    subtitle: 'Organize workstation essentials, track ergonomic gear, and stay ready for work',
    briefQuery: 'Ergonomic workstation gear: high-back mesh chair, dual monitor arm, mechanical wireless keyboard under ₹35,000',
    color: '#1EA7FD',
    colorLight: '#E5F5FF',
    textColor: '#026AA7',
    itemCount: '5 of 7 items',
    totalPrice: '₹34,800',
    numericTotal: 34800,
    stickers: ['⚽', '💻', '🎧', '⚡'],
    status: 'active',
    items: [
      { id: 'd1', name: 'Featherlite Liberate High-Back Mesh', seller: 'Flipkart', price: 12490, delivery: 'Arrives in 2 days', iconColor: '#2874F0' },
      { id: 'd2', name: 'Dual-Monitor Ergonomic Gas Spring Arm', seller: 'Amazon', price: 4899, delivery: 'Prime Next-day', iconColor: '#FF9900' },
      { id: 'd3', name: 'Keychron K2 Wireless Mechanical Keyboard', seller: 'Amazon', price: 8199, delivery: 'Prime in 2 days', iconColor: '#FF9900' },
    ],
  },
  {
    id: 'bag-emmas-party',
    title: "Emma's Celebration",
    subtitle: "Plan everything for Emma's big day and keep all outfits, gifts, & decor organized",
    briefQuery: "Celebration event outfit and essentials: vintage silk slip midi dress, instax mini camera, balloon garland under ₹55,000",
    color: '#F04D99',
    colorLight: '#FFE8F3',
    textColor: '#9E165A',
    itemCount: '5 of 11 items',
    totalPrice: '₹54,200',
    numericTotal: 54200,
    stickers: ['🧸', '🕶️', '🎂', '✨'],
    status: 'active',
    items: [
      { id: 'p1', name: 'Pastel Vintage Silk Slip Midi Dress', seller: 'Poshmark', price: 6900, delivery: 'Standard 3 days', iconColor: '#79242F' },
      { id: 'p2', name: 'Fujifilm Instax Mini 12 Camera Kit', seller: 'Amazon', price: 7499, delivery: 'Arrives tomorrow', iconColor: '#FF9900' },
      { id: 'p3', name: 'Custom Foil Balloon Arch & Garland', seller: 'Zazzle', price: 3850, delivery: 'Made to order', iconColor: '#111111' },
    ],
  },
];

export const COLOR_PALETTE = [
  { color: '#F8D148', colorLight: '#FFF8D6', textColor: '#8C6C00' },
  { color: '#1EA7FD', colorLight: '#E5F5FF', textColor: '#026AA7' },
  { color: '#F04D99', colorLight: '#FFE8F3', textColor: '#9E165A' },
  { color: '#8B5CF6', colorLight: '#F3E8FF', textColor: '#5B21B6' },
  { color: '#10B981', colorLight: '#ECFDF5', textColor: '#065F46' },
];

export function BagsPurchaseTracker({ plans = [], onDiscover, onOpenPlan, onToast }) {
  const [activeTab, setActiveTab] = useState('active'); // 'active' | 'archived' | 'all'
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'list'
  const [sortBy, setSortBy] = useState('recent'); // 'recent' | 'price-high' | 'price-low'
  const [inspectBag, setInspectBag] = useState(null);

  // Convert user plans to the Bags format
  const userBags = useMemo(() => {
    return plans.map((plan, index) => {
      const palette = COLOR_PALETTE[index % COLOR_PALETTE.length];
      const items = (plan.items || []).map((it) => ({
        id: it.id,
        name: it.name,
        seller: it.seller || 'Verified Retailer',
        price: it.price || 0,
        delivery: it.delivery_label || 'Confirmed shipping',
        url: it.url,
        iconColor: '#0694D6',
      }));
      return {
        id: plan.id,
        isUserPlan: true,
        title: plan.name || `Private Plan #${plan.id.slice(-4).toUpperCase()}`,
        subtitle: plan.notice || 'Verified research plan ready for retailer handoff',
        color: palette.color,
        colorLight: palette.colorLight,
        textColor: palette.textColor,
        itemCount: `${items.length} of ${items.length} items verified`,
        totalPrice: `₹${Number(plan.total || 0).toLocaleString('en-IN')}`,
        numericTotal: Number(plan.total || 0),
        stickers: ['🛒', '🏷️', '📦', '✨'],
        status: 'active',
        items,
        rawPlan: plan,
      };
    });
  }, [plans]);

  // Combine user bags with demo showcase bags
  const allBags = useMemo(() => {
    return [...userBags, ...DEMO_BAGS];
  }, [userBags]);

  // Filter & sort
  const filteredBags = useMemo(() => {
    return allBags.filter((bag) => {
      if (activeTab === 'active' && bag.status !== 'active') return false;
      if (activeTab === 'archived' && bag.status !== 'archived') return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesTitle = bag.title.toLowerCase().includes(q);
        const matchesItems = bag.items.some((it) => it.name.toLowerCase().includes(q) || it.seller.toLowerCase().includes(q));
        if (!matchesTitle && !matchesItems) return false;
      }
      return true;
    }).sort((a, b) => {
      if (sortBy === 'price-high') return b.numericTotal - a.numericTotal;
      if (sortBy === 'price-low') return a.numericTotal - b.numericTotal;
      return 0;
    });
  }, [allBags, activeTab, searchQuery, sortBy]);

  return (
    <div className="bags-tracker">
      {/* ── Top Header inspired by Dribbble ── */}
      <div className="bags-tracker__header">
        <div className="bags-tracker__brand-row">
          <div className="bags-tracker__logo">
            <span className="bags-tracker__logo-dot" />
            <span className="bags-tracker__logo-text">Artha BagSync</span>
          </div>
          <div className="bags-tracker__view-controls">
            <button
              type="button"
              className={`bags-tracker__view-btn ${viewMode === 'grid' ? 'is-active' : ''}`}
              onClick={() => setViewMode('grid')}
              aria-label="Grid view"
              title="Grid view"
            >
              <Icon name="grid" size={16} />
            </button>
            <button
              type="button"
              className={`bags-tracker__view-btn ${viewMode === 'list' ? 'is-active' : ''}`}
              onClick={() => setViewMode('list')}
              aria-label="List view"
              title="List view"
            >
              <Icon name="list" size={16} />
            </button>
          </div>
        </div>

        <div className="bags-tracker__hero-text">
          <h1 className="bags-tracker__title">My Bags</h1>
          <p className="bags-tracker__subtitle">Manage your shopping lists and track your purchases across retailers</p>
        </div>

        {/* ── Filter / Search Bar ── */}
        <div className="bags-tracker__controls-row">
          <div className="bags-tracker__filter-pill">
            <select
              value={activeTab}
              onChange={(e) => setActiveTab(e.target.value)}
              className="bags-tracker__select"
              aria-label="Filter bags"
            >
              <option value="active">Active</option>
              <option value="archived">Archived</option>
              <option value="all">All Bags</option>
            </select>
            <Icon name="chevron" size={13} className="bags-tracker__select-chevron" />
          </div>

          <div className="bags-tracker__search-container">
            <Icon name="search" size={16} className="bags-tracker__search-icon" />
            <input
              type="text"
              placeholder="Search bag or item…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bags-tracker__search-input"
            />
            <button
              type="button"
              className="bags-tracker__filter-icon-btn"
              onClick={() => setSortBy(sortBy === 'price-high' ? 'price-low' : 'price-high')}
              title={`Sort by price: ${sortBy}`}
              aria-label="Toggle sort"
            >
              <Icon name="filter" size={15} />
            </button>
          </div>

          <div className="bags-tracker__sort-pill">
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              className="bags-tracker__select"
              aria-label="Sort by"
            >
              <option value="recent">Sort By: Recent</option>
              <option value="price-high">Price: High to Low</option>
              <option value="price-low">Price: Low to High</option>
            </select>
            <Icon name="chevron" size={13} className="bags-tracker__select-chevron" />
          </div>
        </div>
      </div>

      {/* ── Bags Grid / List ── */}
      <div className={`bags-tracker__shelf bags-tracker__shelf--${viewMode}`}>
        {filteredBags.map((bag) => (
          <BagFolderCard
            key={bag.id}
            bag={bag}
            onInspect={(b) => setInspectBag(b)}
            onOpenPlan={onOpenPlan}
          />
        ))}
      </div>

      {/* ── Empty state fallback ── */}
      {filteredBags.length === 0 && (
        <div className="bags-tracker__empty">
          <span className="bags-tracker__empty-icon">🎒</span>
          <h3>No matching bags found</h3>
          <p>Try clearing your search query or create a new research brief with Artha's 7 agents.</p>
          <button type="button" className="primary-button" onClick={onDiscover}>
            <span>New Research Brief</span>
            <Icon name="arrow" size={16} />
          </button>
        </div>
      )}

      {/* ── Modal for Inspecting Bag Details ── */}
      {inspectBag && (
        <BagDetailModal
          bag={inspectBag}
          onClose={() => setInspectBag(null)}
          onToast={onToast}
        />
      )}
    </div>
  );
}

export function BagFolderCard({
  bag,
  onInspect,
  onOpenPlan,
  onResearch,
}) {
  return (
    <Card3D maxTilt={9} scale={1.02} className="bags-tracker__card-wrapper">
      <article
        className="bag-folder"
        style={{
          '--folder-color': bag.color,
          '--folder-light': bag.colorLight,
          '--folder-text': bag.textColor,
        }}
      >
        {/* Folder Silhouette Tab */}
        <div className="bag-folder__tab">
          <span className="bag-folder__tab-inner" />
        </div>

        {/* Pop-out Cutout Stickers Header */}
        <div className="bag-folder__stickers" aria-hidden="true">
          {bag.stickers.map((stk, i) => (
            <span key={i} className={`bag-folder__sticker bag-folder__sticker--${i + 1}`}>
              {stk}
            </span>
          ))}
        </div>

        {/* Stacked Retailer Tier Cards peeking out */}
        <div className="bag-folder__tiers">
          {bag.items.slice(0, 3).map((item, idx) => (
            <div
              key={item.id}
              className="bag-folder__tier-item"
              style={{ transform: `translateY(${idx * 7}px) scale(${1 - idx * 0.03})` }}
            >
              <div className="bag-folder__retailer-badge" style={{ backgroundColor: item.iconColor }}>
                {item.seller.charAt(0)}
              </div>
              <span className="bag-folder__tier-seller">{item.seller}</span>
              <span className="bag-folder__tier-dot">⋮</span>
            </div>
          ))}
        </div>

        {/* Front White Overlay Pocket */}
        <div className="bag-folder__pocket">
          <div className="bag-folder__pocket-header">
            <h3 className="bag-folder__pocket-title">{bag.title}</h3>
            <p className="bag-folder__pocket-subtitle">{bag.subtitle}</p>
          </div>

          <div className="bag-folder__pocket-footer">
            <span className="bag-folder__item-count">{bag.itemCount}</span>
            <span className="bag-folder__price">{bag.totalPrice}</span>
          </div>

          <div className="bag-folder__pocket-actions">
            <button
              type="button"
              className="bag-folder__view-btn"
              onClick={() => onInspect?.(bag)}
            >
              <span>View Bag</span>
              <Icon name="arrow" size={14} />
            </button>
            {onResearch && bag.briefQuery ? (
              <button
                type="button"
                className="bag-folder__research-btn"
                onClick={() => onResearch?.(bag)}
                title="Research this collection with Artha"
              >
                <Icon name="spark" size={13} />
                <span>Research</span>
              </button>
            ) : null}
            {bag.isUserPlan && onOpenPlan ? (
              <button
                type="button"
                className="bag-folder__handoff-btn"
                onClick={() => onOpenPlan(bag.rawPlan)}
              >
                <span>Retailer Links</span>
                <Icon name="external" size={13} />
              </button>
            ) : null}
          </div>
        </div>
      </article>
    </Card3D>
  );
}

export function BagDetailModal({
  bag,
  onClose,
  onToast,
  onResearch,
}) {
  if (!bag) return null;
  return (
    <div className="bags-modal-backdrop" onClick={onClose}>
      <div
        className="bags-modal-content"
        onClick={(e) => e.stopPropagation()}
        style={{ '--modal-accent': bag.color }}
      >
        <div className="bags-modal__header">
          <div className="bags-modal__title-group">
            <span className="bags-modal__badge" style={{ backgroundColor: bag.color }}>
              {bag.itemCount}
            </span>
            <h2>{bag.title}</h2>
          </div>
          <button
            type="button"
            className="bags-modal__close-btn"
            onClick={onClose}
            aria-label="Close"
          >
            <Icon name="close" size={18} />
          </button>
        </div>

        <p className="bags-modal__subtitle">{bag.subtitle}</p>

        <div className="bags-modal__items-list">
          {bag.items.map((item) => (
            <div key={item.id} className="bags-modal__item-row">
              <div className="bags-modal__item-info">
                <strong>{item.name}</strong>
                <div className="bags-modal__item-meta">
                  <span className="bags-modal__seller-tag">{item.seller}</span>
                  <span>•</span>
                  <span>{item.delivery}</span>
                </div>
              </div>
              <div className="bags-modal__item-right">
                <span className="bags-modal__item-price">₹{Number(item.price).toLocaleString('en-IN')}</span>
                {item.url ? (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    className="bags-modal__link-btn"
                  >
                    <Icon name="external" size={14} />
                  </a>
                ) : null}
              </div>
            </div>
          ))}
        </div>

        <div className="bags-modal__footer">
          <div className="bags-modal__total-display">
            <span>Verified subtotal:</span>
            <strong>{bag.totalPrice}</strong>
          </div>
          <div className="bags-modal__footer-btns">
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                if (onToast) onToast(`Copied share link for "${bag.title}"`);
                onClose();
              }}
            >
              <Icon name="link" size={14} />
              <span>Share Bag</span>
            </button>
            {onResearch && bag.briefQuery ? (
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  onResearch(bag);
                  onClose();
                }}
              >
                <Icon name="spark" size={15} />
                <span>Research This Bag</span>
              </button>
            ) : (
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  if (onToast) onToast(`Loaded ${bag.items.length} items to checkout handoff`);
                  onClose();
                }}
              >
                <Icon name="check" size={16} />
                <span>Checkout All</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
