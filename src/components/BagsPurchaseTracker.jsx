import React, { useState, useMemo } from 'react';
import { Icon } from './Icon';
import { Card3D } from './Card3D';
import { formatPrice, productTotal } from '../data';

const COLOR_PALETTE = [
  { color: '#F8D148', colorLight: '#FFF8D6', textColor: '#8C6C00' },
  { color: '#1EA7FD', colorLight: '#E5F5FF', textColor: '#026AA7' },
  { color: '#F04D99', colorLight: '#FFE8F3', textColor: '#9E165A' },
  { color: '#8B5CF6', colorLight: '#F3E8FF', textColor: '#5B21B6' },
  { color: '#10B981', colorLight: '#ECFDF5', textColor: '#065F46' },
];

export function planToBag(plan, index = 0) {
  const palette = COLOR_PALETTE[index % COLOR_PALETTE.length];
  const items = (Array.isArray(plan?.items) ? plan.items : []).map((item) => ({
    id: item.id,
    name: item.name || 'Retailer item',
    seller: item.seller || 'Retailer',
    price: productTotal(item),
    delivery: item.delivery_label || 'Confirm at retailer',
    url: item.url,
    iconColor: '#0694D6',
  }));
  const sellers = [...new Set(items.map((item) => item.seller))];
  const savedTotal = Number(plan?.total);
  const numericTotal = Number.isFinite(savedTotal) && savedTotal > 0
    ? savedTotal
    : items.reduce((sum, item) => sum + item.price, 0);
  const name = String(plan?.name || '').trim();

  return {
    id: plan?.id,
    isUserPlan: true,
    title: name || items[0]?.name || 'Saved purchase plan',
    subtitle: `${items.length} saved ${items.length === 1 ? 'item' : 'items'}${sellers.length ? ` across ${sellers.join(', ')}` : ''}`,
    briefQuery: name || items.map((item) => item.name).slice(0, 3).join(', '),
    color: palette.color,
    colorLight: palette.colorLight,
    textColor: palette.textColor,
    itemCount: `${items.length} saved ${items.length === 1 ? 'item' : 'items'}`,
    totalPrice: formatPrice(numericTotal),
    numericTotal,
    stickers: ['🛍️', '📦', '🔎', '✨'],
    status: 'active',
    items,
    rawPlan: plan,
  };
}

export function BagsPurchaseTracker({ plans = [], onDiscover, onOpenPlan, onToast }) {
  const [activeTab, setActiveTab] = useState('active'); // 'active' | 'archived' | 'all'
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'list'
  const [sortBy, setSortBy] = useState('recent'); // 'recent' | 'price-high' | 'price-low'
  const [inspectBag, setInspectBag] = useState(null);

  const allBags = useMemo(() => plans.map(planToBag), [plans]);

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
            <span className="bags-tracker__logo-text">ARTHA PURCHASE PLANS</span>
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
          <div className="bags-tracker__kicker-tab">
            <span className="bags-tracker__folder-badge">FOLDER // PURCHASE PLANS</span>
            <span className="bags-tracker__count-tag">{allBags.length} {allBags.length === 1 ? 'plan' : 'plans'}</span>
          </div>
          <h1 className="bags-tracker__title">YOUR SHORTLIST, ORGANIZED TO BUY.</h1>
          <p className="bags-tracker__subtitle">Consolidate verified retailer finds into clear purchase shortlists before buying. Real purchases happen with the merchant.</p>
          <span className="bags-tracker__annotation">“One clean plan, ready for retailer checkout.”</span>
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
          <h3>{plans.length ? 'No matching bags found' : 'No saved bags yet'}</h3>
          <p>{plans.length ? 'Try clearing your search query or create a new research brief with Artha.' : 'Research a brief, choose retailer items, and save your first purchase plan.'}</p>
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
            <span>Known subtotal:</span>
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
