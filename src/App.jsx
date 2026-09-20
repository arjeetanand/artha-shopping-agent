import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from './components/Icon';
import {
  DEFAULT_INTENT,
  DEFAULT_RESULT,
  SUGGESTED_SEARCHES,
  formatDate,
  formatPrice,
  productTotal,
  sanitizeSnippet,
  sanitizeTitle,
} from './data';
import {
  beginGoogleSignIn,
  advanceOrder,
  cancelOrder,
  completeRefund,
  createOrder,
  createPlan,
  getHealth,
  getOrders,
  getPlans,
  getSession,
  getUsage,
  getVoiceStatus,
  requestReturn,
  refineAgentSearch,
  createPaymentOrder,
  runAgentSearch,
  signOut,
  speakText,
  verifyPayment,
  warmVoice,
} from './lib/api';

const SAVED_KEY = 'artha:saved:v1';
const LEGACY_SAVED_KEY = 'saathi:saved:v2';
const PENDING_SEARCH_KEY = 'artha:pending-search:v1';
const MAX_REFERENCE_IMAGE_BYTES = 4 * 1024 * 1024;
const ALLOWED_REFERENCE_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp', 'image/gif']);
const NAV_ITEMS = [
  { id: 'discover', label: 'Discover', icon: 'search' },
  { id: 'saved', label: 'Saved', icon: 'bookmark' },
  { id: 'plans', label: 'Purchase plans', icon: 'box' },
  { id: 'orders', label: 'Orders', icon: 'truck' },
  { id: 'usage', label: 'Usage', icon: 'chart' },
];
const SECTION_TITLES = { discover: 'Discover', saved: 'Saved picks', plans: 'Purchase plans', orders: 'Orders & tracking', usage: 'Usage & runtime' };
let razorpayLoader;

function loadRazorpayCheckout() {
  if (window.Razorpay) return Promise.resolve(window.Razorpay);
  if (razorpayLoader) return razorpayLoader;
  razorpayLoader = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.async = true;
    script.onload = () => (window.Razorpay ? resolve(window.Razorpay) : reject(new Error('Razorpay Checkout did not load.')));
    script.onerror = () => reject(new Error('Razorpay Checkout could not load. Check the network and try again.'));
    document.head.appendChild(script);
  });
  return razorpayLoader;
}

function readSavedIds() {
  try {
    const raw = window.localStorage.getItem(SAVED_KEY) || window.localStorage.getItem(LEGACY_SAVED_KEY) || '[]';
    const value = JSON.parse(raw);
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function readPendingSearch() {
  try {
    const raw = window.sessionStorage.getItem(PENDING_SEARCH_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw);
    if (!value || Date.now() - Number(value.saved_at || 0) > 30 * 60 * 1000) {
      window.sessionStorage.removeItem(PENDING_SEARCH_KEY);
      return null;
    }
    if (!value.result || !Array.isArray(value.result.products)) return null;
    return value;
  } catch {
    return null;
  }
}

function preservePendingSearch({ query, postUrl, result, selectedIds, location }) {
  try {
    window.sessionStorage.setItem(
      PENDING_SEARCH_KEY,
      JSON.stringify({ saved_at: Date.now(), query, postUrl, result, selectedIds, location }),
    );
  } catch {
    /* Private browsing can deny session storage; sign-in still works. */
  }
}

function viewFromPath(pathname = '/') {
  const path = String(pathname).replace(/\/+$/, '') || '/';
  return ({ '/saved': 'saved', '/plans': 'plans', '/orders': 'orders', '/usage': 'usage' })[path] || 'discover';
}

function initials(name = '') {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join('')
      .toUpperCase() || 'S'
  );
}

function readReferenceImage(file) {
  if (!ALLOWED_REFERENCE_IMAGE_TYPES.has(file.type)) {
    return Promise.reject(new Error('Choose a PNG, JPEG, WebP, or GIF reference image.'));
  }
  if (file.size > MAX_REFERENCE_IMAGE_BYTES) {
    return Promise.reject(new Error('Reference images must be 4 MB or smaller.'));
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('That reference image could not be read.'));
    reader.onload = () =>
      resolve({
        name: file.name.slice(0, 160),
        type: file.type,
        size: file.size,
        dataUrl: String(reader.result || ''),
      });
    reader.readAsDataURL(file);
  });
}

function referencePayload(reference) {
  if (!reference?.dataUrl || !reference.type) return null;
  const encoded = reference.dataUrl.split(',', 2)[1];
  if (!encoded) return null;
  return { name: reference.name, mime_type: reference.type, data_base64: encoded };
}

function Logo({ onClick }) {
  return (
    <button type="button" className="brand-mark" onClick={onClick} aria-label="Go to Artha discover">
      <span className="brand-mark__text">Artha</span>
    </button>
  );
}

function NavRail({ activeView, onNavigate, onReset, health, planCount }) {
  const live = health?.anakin_configured;
  const production = health?.environment === 'production';
  return (
    <aside className="nav-rail">
      <div className="nav-rail__top">
        <Logo onClick={onReset} />
      </div>
      <nav className="nav-links" aria-label="Primary navigation">
        {NAV_ITEMS.map((item) => (
          <button
            type="button"
            key={item.id}
            className={`nav-link ${activeView === item.id ? 'is-active' : ''}`}
            onClick={() => onNavigate(item.id)}
            aria-current={activeView === item.id ? 'page' : undefined}
          >
            <Icon name={item.icon} size={19} />
            <span>{item.label}</span>
            {item.id === 'plans' && planCount > 0 ? <em>{planCount}</em> : null}
          </button>
        ))}
      </nav>
      <div className="nav-rail__bottom">
        <div className="connection-status">
          <span className={`connection-dot ${live ? 'is-live' : ''}`} />
          <div className="connection-status__text">
            <strong>{production ? 'Production API' : 'Local API'}</strong>
            <small>{live ? 'Anakin live search' : 'Search provider not ready'} · {health?.ai?.provider === 'gemini' ? 'Gemini' : 'Ollama'}</small>
          </div>
        </div>
        <div className="nav-rail__rule" />
        <p className="nav-rail__motto">
          Source-linked choices
          <br />
          for deliberate buyers.
        </p>
      </div>
    </aside>
  );
}

function MobileNav({ activeView, onNavigate, planCount }) {
  return (
    <nav className="mobile-nav" aria-label="Mobile navigation">
      {NAV_ITEMS.map((item) => (
        <button
          type="button"
          key={item.id}
          className={activeView === item.id ? 'is-active' : ''}
          onClick={() => onNavigate(item.id)}
        >
          <Icon name={item.icon} size={20} />
          <span>{item.label}</span>
          {item.id === 'plans' && planCount > 0 ? <em>{planCount}</em> : null}
        </button>
      ))}
    </nav>
  );
}

function AccountAvatar({ user }) {
  if (user?.picture) return <img className="account-avatar" src={user.picture} alt="" referrerPolicy="no-referrer" />;
  return <span className="account-avatar account-avatar--initials">{initials(user?.name)}</span>;
}

function TopHeader({ activeView, user, onSignIn, onSignOut }) {
  return (
    <header className="top-header">
      <div className="top-header__breadcrumb">
        <span className="top-header__crumb-app">Artha</span>
        <span className="top-header__separator">/</span>
        <span className="top-header__section">{SECTION_TITLES[activeView]}</span>
      </div>
      {user ? (
        <div className="account-cluster">
          <div className="account-identity">
            <AccountAvatar user={user} />
            <span className="account-identity__name">{user.name}</span>
          </div>
          <button type="button" className="quiet-action account-logout" onClick={onSignOut}>
            <Icon name="logout" size={15} /> Sign out
          </button>
        </div>
      ) : (
        <button type="button" className="quiet-action sign-in-btn" onClick={onSignIn}>
          <Icon name="user" size={15} /> Sign in
        </button>
      )}
    </header>
  );
}

function ProductThumb({ product, small = false }) {
  const position = `${Math.max(0, Math.min(2, Number(product.crop_index || 0))) * 50}% center`;
  const image = String(product.image || '').trim();
  return (
    <span
      className={`product-thumb ${small ? 'product-thumb--small' : ''} ${image ? '' : 'product-thumb--placeholder'}`}
      role="img"
      aria-label={`${product.name} thumbnail`}
      style={{
        backgroundImage: image ? `url(${image})` : 'none',
        backgroundPosition: position,
      }}
    />
  );
}

function SourceMark({ product }) {
  const live = product.source_kind === 'live_web';
  const seller = product.seller || 'Retailer';
  return (
    <span className="source-mark" aria-label={`${live ? 'Live retailer source' : 'Source evidence'} ${seller}`}>
      <b className="source-mark__monogram">{seller.slice(0, 2).toUpperCase()}</b>
      <span className="source-mark__name">{seller}</span>
    </span>
  );
}

function VoiceInputButton({ onTranscript, onError }) {
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef(null);

  const begin = useCallback(() => {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      onError('Voice input is not supported in this browser. You can still type your brief.');
      return;
    }
    if (isListening) {
      recognitionRef.current?.stop();
      return;
    }
    const recognition = new Recognition();
    recognition.lang = 'en-IN';
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onstart = () => setIsListening(true);
    recognition.onend = () => setIsListening(false);
    recognition.onerror = () => onError('I could not hear that clearly. Please try again or type your brief.');
    recognition.onresult = (event) => onTranscript(event.results?.[0]?.[0]?.transcript || '');
    recognitionRef.current = recognition;
    recognition.start();
  }, [isListening, onError, onTranscript]);

  return (
    <button
      type="button"
      className={`secondary-control ${isListening ? 'is-selected' : ''}`}
      onClick={begin}
      aria-pressed={isListening}
    >
      <Icon name="mic" size={17} />
      <span>{isListening ? 'Listening…' : 'Speak brief'}</span>
    </button>
  );
}

function LocationButton({ location, onLocation, onError }) {
  const [isRequesting, setIsRequesting] = useState(false);

  const requestLocation = useCallback(() => {
    if (!navigator.geolocation) {
      onError('This browser does not expose location permission. Type your delivery city instead.');
      return;
    }
    setIsRequesting(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setIsRequesting(false);
        onLocation({ latitude: position.coords.latitude, longitude: position.coords.longitude });
      },
      () => {
        setIsRequesting(false);
        onError('Location permission was not granted. Type your delivery city instead.');
      },
      { enableHighAccuracy: false, maximumAge: 300000, timeout: 8000 },
    );
  }, [onError, onLocation]);

  return (
    <button
      type="button"
      className={`secondary-control ${location ? 'is-selected' : ''}`}
      onClick={requestLocation}
      disabled={isRequesting}
      title="Share your approximate location for delivery-aware research"
    >
      <Icon name="truck" size={16} />
      <span>{isRequesting ? 'Locating…' : location ? 'Location ready' : 'Use my location'}</span>
    </button>
  );
}

function ReferenceChip({ reference, onRemove }) {
  return reference ? (
    <span className="reference-chip">
      <img src={reference.dataUrl} alt="" />
      <span>{reference.name}</span>
      <button type="button" onClick={onRemove} aria-label="Remove reference image">
        <Icon name="close" size={14} />
      </button>
    </span>
  ) : null;
}

function Composer({
  query,
  setQuery,
  postUrl,
  setPostUrl,
  showPostUrl,
  setShowPostUrl,
  reference,
  location,
  onLocation,
  onReferenceChange,
  onRemoveReference,
  onSearch,
  isSearching,
  hasResults,
  onToast,
  onPickPrompt,
}) {
  const fileInputRef = useRef(null);
  const onFileChange = useCallback(
    async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        onReferenceChange(await readReferenceImage(file));
      } catch (error) {
        onToast(error.message || 'That reference image could not be added.');
      } finally {
        event.target.value = '';
      }
    },
    [onReferenceChange, onToast],
  );

  const canSearch = Boolean(query.trim() || postUrl.trim() || reference?.dataUrl);

  return (
    <div className="composer-container">
      <form className="composer" onSubmit={onSearch}>
        <label className="sr-only" htmlFor="shopping-brief">
          {hasResults ? 'Follow-up preference' : 'Shopping brief'}
        </label>
        <textarea
          id="shopping-brief"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={hasResults ? 'Ask a follow-up (e.g., show me options under ₹11,000 or make the delivery window tighter)…' : 'Describe what you want (e.g., Office-ready neutral look under ₹15,000, breathable linen shirts, leather loafers)…'}
          rows={2}
        />
        <div className="composer__footer">
          <div className="composer__inputs">
            <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={onFileChange} />
            <button type="button" className="secondary-control" onClick={() => fileInputRef.current?.click()}>
              <Icon name="image" size={16} />
              <span>Reference photo</span>
            </button>
            <button
              type="button"
              className={`secondary-control ${showPostUrl ? 'is-selected' : ''}`}
              onClick={() => setShowPostUrl((current) => !current)}
              aria-expanded={showPostUrl}
            >
              <Icon name="link" size={16} />
              <span>Paste URL</span>
            </button>
            <VoiceInputButton onTranscript={setQuery} onError={onToast} />
            <LocationButton location={location} onLocation={onLocation} onError={onToast} />
            <ReferenceChip reference={reference} onRemove={onRemoveReference} />
          </div>
          <button type="submit" className="primary-button composer__submit" disabled={isSearching || !canSearch}>
            {isSearching ? (
              <>
                <span className="spinner" />
                <span>Searching sources…</span>
              </>
            ) : (
              <>
                <span>{hasResults ? 'Refine shortlist' : 'Find sources'}</span>
                <Icon name="arrow" size={17} />
              </>
            )}
          </button>
        </div>
        {showPostUrl ? (
          <div className="url-field-wrap">
            <label className="url-field">
              <Icon name="link" size={15} />
              <span className="sr-only">Product or post URL</span>
              <input
                value={postUrl}
                onChange={(event) => setPostUrl(event.target.value)}
                placeholder="Paste an Instagram, Pinterest, or product page link to scrape"
                inputMode="url"
              />
            </label>
          </div>
        ) : null}
      </form>

      <div className="composer-suggestions">
        <span className="composer-suggestions__label">Try:</span>
        <div className="composer-suggestions__list">
          {SUGGESTED_SEARCHES.map((prompt) => (
            <button
              type="button"
              key={prompt}
              className="suggestion-chip"
              onClick={() => onPickPrompt(prompt)}
            >
              <Icon name="spark" size={12} />
              <span>{prompt}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentStrip({ workflow, isSearching, searchStage, hasResults }) {
  const lastStage = Math.max((workflow?.length || 6) - 1, 0);
  return (
    <section className="agent-strip" aria-label="Agent workflow">
      <div className="agent-strip__heading">
        <div className="agent-strip__title">
          <Icon name="shield" size={15} />
          <span>Multi-Agent Verification Pipeline</span>
        </div>
        <small className="agent-strip__status">
          {isSearching ? 'Live agents verifying sources…' : hasResults ? 'Every recommendation verified with source evidence' : 'Ready for a live search'}
        </small>
      </div>
      <div className="agent-strip__steps">
        {(workflow || []).map((step, index) => {
          const working = isSearching && index === Math.min(searchStage, lastStage);
          const complete = !working && step.status === 'complete';
          return (
            <div
              className={`agent-step ${working ? 'is-working' : complete ? 'is-complete' : ''}`}
              key={`${step.agent}-${index}`}
            >
              <span className="agent-step__node">
                {working ? <span className="pulse-dot" /> : complete ? <Icon name="check" size={13} /> : index + 1}
              </span>
              <div className="agent-step__content">
                <strong>{step.agent.replace(' agent', '')}</strong>
                <small title={step.detail}>{working ? 'Processing…' : step.detail}</small>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ConversationTrail({ conversation }) {
  if (!Array.isArray(conversation) || conversation.length < 2) return null;
  const latest = conversation[conversation.length - 1];
  return (
    <div className="conversation-trail" aria-live="polite">
      <span className="conversation-trail__label">Follow-up kept research</span>
      <p>{latest?.text || 'The shortlist was refined from the existing evidence.'}</p>
    </div>
  );
}

function BriefSummary({ intent }) {
  const fields = [
    intent?.occasion ? `Occasion: ${intent.occasion}` : null,
    ...(intent?.must_have || []).slice(0, 2),
    intent?.budget ? `Budget ₹${Number(intent.budget).toLocaleString('en-IN')}` : null,
    intent?.quantity > 1 ? `Quantity ${intent.quantity}` : null,
    intent?.brand ? `Preferred brand: ${intent.brand}` : null,
    intent?.location ? `Delivering to ${intent.location}` : null,
  ].filter(Boolean);
  return <p className="brief-summary">{fields.join(' • ')}</p>;
}

function ProductCard({ product, selected, focused, onToggle, onFocus, onOpenProduct, onInspect, onSave, saved }) {
  const live = product.source_kind === 'live_web';
  const cleanTitle = sanitizeTitle(product.name);
  const cleanDesc = sanitizeSnippet(product.description);

  return (
    <article
      className={`product-card ${selected ? 'is-selected' : ''} ${focused ? 'is-focused' : ''}`}
      onMouseEnter={() => onFocus(product.id)}
    >
      <div className="product-card__media">
        <ProductThumb product={product} />
        <div className="product-card__badges">
          <SourceMark product={product} />
          <span className={`match-badge ${product.eligible === false ? 'is-invalid' : ''}`} title={product.eligible === false ? product.reason_tags?.join(' · ') : `Match Score: ${product.match_score || 90}%`}>
            <Icon name="spark" size={12} />
            <span>{product.eligible === false ? 'Not a fit' : `${product.match_score || 92}% Match`}</span>
          </span>
        </div>
      </div>

      <div className="product-card__body">
        <div className="product-card__header">
          <h3 className="product-card__title" title={product.name}>
            {cleanTitle}
          </h3>
          <p className="product-card__desc" title={product.description}>
            {cleanDesc}
          </p>
        </div>

        <div className="product-card__meta">
          <div className="product-card__pricing">
            <strong className="product-card__price">{formatPrice(productTotal(product))}</strong>
            <span className="product-card__rating">
              {product.rating ? (
                <>
                  <Icon name="star" size={12} /> {product.rating}
                </>
              ) : live ? (
                'Live source'
              ) : (
                'Catalog pick'
              )}
            </span>
          </div>
          {product.quantity > 1 ? <small className="product-card__quantity-note">{product.quantity} units · {formatPrice(product.unit_total || product.total_price)} each</small> : null}
          <div className="product-card__delivery">
            <Icon name="truck" size={14} />
            <span>{product.delivery_label || 'Confirm at store'}</span>
          </div>
          <small className={`constraint-note ${product.eligible === false ? 'is-invalid' : ''}`}>{(product.reason_tags || []).join(' · ')}</small>
        </div>

        <div className="product-card__actions">
          <button
            type="button"
            className={`plan-toggle-btn ${selected ? 'is-active' : ''}`}
            onClick={() => onToggle(product.id)}
            aria-pressed={selected}
          >
            <Icon name={selected ? 'checkCircle' : 'plus'} size={15} />
            <span>{selected ? 'In purchase plan' : 'Add to plan'}</span>
          </button>

          <div className="product-card__secondary-actions">
            <button
              type="button"
              className="icon-action-btn"
              onClick={() => onInspect(product)}
              aria-label={`View evidence for ${cleanTitle}`}
              title="View evidence"
            >
              <Icon name="shield" size={16} />
            </button>
            <button
              type="button"
              className={`icon-action-btn ${saved ? 'is-saved' : ''}`}
              onClick={() => onSave(product.id)}
              aria-label={saved ? `Remove ${cleanTitle} from saved` : `Save ${cleanTitle}`}
              title={saved ? 'Remove from saved' : 'Save for later'}
            >
              <Icon name="bookmark" size={16} />
            </button>
            <button
              type="button"
              className="icon-action-btn"
              onClick={() => onOpenProduct(product)}
              disabled={!product.url}
              aria-label={`Open ${cleanTitle} at retailer`}
              title="Open product retailer page"
            >
              <Icon name="external" size={16} />
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}

function ProductRow({ product, selected, focused, onToggle, onFocus, onOpenProduct, onInspect, onSave, saved }) {
  const live = product.source_kind === 'live_web';
  const cleanTitle = sanitizeTitle(product.name);
  const cleanDesc = sanitizeSnippet(product.description);

  return (
    <tr
      className={`${selected ? 'is-selected' : ''} ${focused ? 'is-focused' : ''}`}
      onMouseEnter={() => onFocus(product.id)}
    >
      <td className="col-select">
        <label className="check-control">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggle(product.id)}
            aria-label={`Select ${cleanTitle}`}
          />
          <span>
            <Icon name="check" size={13} />
          </span>
        </label>
      </td>
      <td className="col-product">
        <div className="product-cell">
          <ProductThumb product={product} small />
          <div className="product-cell__copy">
            <strong title={product.name}>{cleanTitle}</strong>
            <span title={product.description}>{cleanDesc}</span>
            <div className="product-cell__links">
              <button type="button" onClick={() => onOpenProduct(product)} disabled={!product.url}>
                <span>Visit retailer</span>
                <Icon name="external" size={12} />
              </button>
              <button type="button" onClick={() => onInspect(product)}>
                <Icon name="shield" size={12} />
                <span>Evidence</span>
              </button>
              <button type="button" className={saved ? 'is-saved' : ''} onClick={() => onSave(product.id)}>
                <Icon name="bookmark" size={12} />
                <span>{saved ? 'Saved' : 'Save'}</span>
              </button>
            </div>
          </div>
        </div>
      </td>
      <td className="col-store">
        <SourceMark product={product} />
      </td>
      <td className="col-price">
        <strong className="price-val">{formatPrice(productTotal(product))}</strong>
        <small className="price-sub">{product.quantity > 1 ? `${product.quantity} units · ${product.rating ? `★ ${product.rating}` : live ? 'Live price' : 'Estimated'}` : product.rating ? `★ ${product.rating}` : live ? 'Live price' : 'Estimated'}</small>
      </td>
      <td className="col-delivery">
        <div className="delivery-val">
          <Icon name="truck" size={13} />
          <span>{product.delivery_label || 'Confirm at retailer'}</span>
        </div>
        <small className="stock-sub">{product.stock !== null && product.stock !== undefined && product.stock !== '' ? `${product.stock} available · qty ${product.quantity || 1}` : 'Check store'}</small>
      </td>
      <td className="col-evidence">
        <div className="evidence-cluster">
          <span className="evidence-tag evidence-tag--match">
            <Icon name="spark" size={12} />
            <span>{product.match_score || 90}% Match</span>
          </span>
          <span className="evidence-tag evidence-tag--source">
            <Icon name="shield" size={12} />
            <span>{live ? 'Live web' : 'Catalog'}</span>
          </span>
        </div>
      </td>
    </tr>
  );
}

function ResultsTable({ products, selectedIds, focusedId, onToggle, onFocus, onOpenProduct, onInspect, onSave, savedIds }) {
  return (
    <div className="results-table-wrap">
      <table className="results-table">
        <thead>
          <tr>
            <th className="col-select">Select</th>
            <th className="col-product">Product & Spec</th>
            <th className="col-store">Retailer</th>
            <th className="col-price">Price</th>
            <th className="col-delivery">Delivery</th>
            <th className="col-evidence">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => (
            <ProductRow
              key={product.id}
              product={product}
              selected={selectedIds.includes(product.id)}
              focused={focusedId === product.id}
              onToggle={onToggle}
              onFocus={onFocus}
              onOpenProduct={onOpenProduct}
              onInspect={onInspect}
              onSave={onSave}
              saved={savedIds.includes(product.id)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function VoiceControl({ voice, isSpeaking, onSpeak, disabled = false }) {
  return (
    <section className="voice-control" aria-label="Voice summary">
      <div className="voice-control__head">
        <div className="voice-control__title">
          <Icon name="waveform" size={16} />
          <span>Audio Summary</span>
        </div>
        <small>{voice?.ready === false ? 'Preparing local voice…' : voice?.label || 'Local voice'}</small>
      </div>
      <div className={`voice-wave ${isSpeaking ? 'is-playing' : ''}`} aria-hidden="true">
        {Array.from({ length: 22 }, (_, index) => (
          <span
            key={index}
            style={{
              '--wave-height': `${24 + ((index * 19) % 65)}%`,
              animationDelay: `${(index % 5) * 110}ms`,
            }}
          />
        ))}
      </div>
      <button
        type="button"
        className={`secondary-button voice-control__button ${isSpeaking ? 'is-active' : ''}`}
        onClick={onSpeak}
        disabled={disabled}
      >
        <Icon name={isSpeaking ? 'pause' : 'play'} size={15} />
        <span>{isSpeaking ? 'Stop listening' : 'Play audio summary'}</span>
      </button>
    </section>
  );
}

function SummaryPanel({
  selectedProducts,
  intent,
  sourceMode,
  voice,
  isSpeaking,
  onSpeak,
  user,
  onSavePlan,
  isSavingPlan,
  onStartCheckout,
  onRemoveItem,
}) {
  const total = selectedProducts.reduce((sum, product) => sum + productTotal(product), 0);
  const live = sourceMode === 'live';
  const awaitingSearch = sourceMode === 'idle';

  return (
    <aside className="summary-panel" aria-label="Purchase plan summary">
      <div className="summary-panel__header">
        <div className="summary-panel__title-wrap">
          <h2>Purchase Plan</h2>
          <span className="item-count-badge">
            {selectedProducts.length} {selectedProducts.length === 1 ? 'item' : 'items'}
          </span>
        </div>
        <small className="summary-panel__sub">Deliberate shortlist ready for checkout</small>
      </div>

      <div className="summary-items">
        {selectedProducts.length ? (
          selectedProducts.map((product) => (
            <div className="summary-item" key={product.id}>
              <ProductThumb product={product} small />
              <div className="summary-item__info">
                <strong title={product.name}>{sanitizeTitle(product.name)}</strong>
                <small>{product.seller}{product.quantity > 1 ? ` · ${product.quantity} units` : ''}</small>
              </div>
              <div className="summary-item__right">
                <b>{formatPrice(productTotal(product))}</b>
                <button
                  type="button"
                  className="summary-item__remove"
                  onClick={() => onRemoveItem(product.id)}
                  aria-label={`Remove ${product.name} from plan`}
                  title="Remove from plan"
                >
                  <Icon name="close" size={13} />
                </button>
              </div>
            </div>
          ))
        ) : (
          <div className="summary-empty">
            <span className="summary-empty__icon">
              <Icon name="box" size={24} />
            </span>
            <p>No items selected yet. Check sources to build your purchase plan.</p>
          </div>
        )}
      </div>

      <div className="summary-calc">
        <div className="summary-calc__row">
          <span>Items subtotal</span>
          <strong className="summary-calc__amount">{formatPrice(total)}</strong>
        </div>
        <div className="summary-delivery">
          <Icon name="truck" size={16} />
          <div className="summary-delivery__copy">
            <strong>{intent?.arrive_by || 'Delivery timing'}</strong>
            <small>{intent?.location ? `Arrives in ${intent.location}` : 'Confirm on store checkout'}</small>
          </div>
        </div>
      </div>

      <VoiceControl voice={voice} isSpeaking={isSpeaking} onSpeak={onSpeak} disabled={!selectedProducts.length} />

      <button
        type="button"
        className="primary-button summary-button"
        onClick={onSavePlan}
        disabled={!selectedProducts.length || isSavingPlan}
      >
        <span>{isSavingPlan ? 'Saving plan…' : user ? 'Save purchase plan' : 'Sign in to save plan'}</span>
        <Icon name="arrow" size={17} />
      </button>

      {sourceMode === 'sandbox' && selectedProducts.length ? (
        <button type="button" className="secondary-button summary-checkout-button" onClick={onStartCheckout}>
          <span>Review sandbox order</span>
          <Icon name="arrow" size={15} />
        </button>
      ) : null}

      <div className="checkout-trust">
        <p className="checkout-note">
          <Icon name="shield" size={14} />
          <span>Checkout occurs directly on official retailer sites. Artha never requests payment info.</span>
        </p>
      </div>

      <div className="summary-legend">
        <LegendRow
          icon="shield"
          title={awaitingSearch ? 'Awaiting live search' : live ? 'Live retailer verified' : 'Live source unavailable'}
          detail={awaitingSearch ? 'Run a brief to query active web retailers.' : live ? 'Click retailer links to confirm live availability.' : 'Run the search again after the provider recovers.'}
        />
        <LegendRow
          icon="spark"
          title="Evidence-linked"
          detail="Every shortlist choice is ranked against your brief."
        />
      </div>
    </aside>
  );
}

function LegendRow({ icon, title, detail }) {
  return (
    <div className="legend-row">
      <span className="legend-row__icon">
        <Icon name={icon} size={15} />
      </span>
      <div className="legend-row__copy">
        <strong>{title}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function DiscoverView({
  result,
  query,
  setQuery,
  postUrl,
  setPostUrl,
  showPostUrl,
  setShowPostUrl,
  reference,
  location,
  onLocation,
  onReferenceChange,
  onRemoveReference,
  onSearch,
  isSearching,
  searchStage,
  selectedIds,
  focusedId,
  onToggle,
  onFocus,
  onOpenProduct,
  onInspect,
  onSave,
  savedIds,
  voice,
  isSpeaking,
  onSpeak,
  user,
  onSavePlan,
  isSavingPlan,
  onStartCheckout,
  onToast,
  onPickPrompt,
  onSelectAll,
  onClearSelection,
  onRemoveSelectedItem,
}) {
  const [viewMode, setViewMode] = useState('cards'); // 'cards' | 'table'
  const selectedProducts = result.products.filter((product) => selectedIds.includes(product.id));
  const allSelected = result.products.length > 0 && selectedIds.length === result.products.length;

  return (
    <div className="discover-layout">
      <section className="main-column">
        <div className="hero-copy">
          <h1>
            Find the right
            <br />
            things.
          </h1>
          <p>
            Describe your style. Artha finds the strongest retailer options and makes comparison feel simple.
          </p>
        </div>

        <Composer
          query={query}
          setQuery={setQuery}
          postUrl={postUrl}
          setPostUrl={setPostUrl}
          showPostUrl={showPostUrl}
          setShowPostUrl={setShowPostUrl}
          reference={reference}
          location={location}
          onLocation={onLocation}
          onReferenceChange={onReferenceChange}
          onRemoveReference={onRemoveReference}
          onSearch={onSearch}
          isSearching={isSearching}
          hasResults={result.products.length > 0}
          onToast={onToast}
          onPickPrompt={onPickPrompt}
        />

        <AgentStrip
          workflow={result.workflow}
          isSearching={isSearching}
          searchStage={searchStage}
          hasResults={result.products.length > 0}
        />
        <ConversationTrail conversation={result.conversation} />

        <section className="results-section" aria-labelledby="results-heading">
          <div className="results-toolbar">
            <div className="results-heading">
            <h2 id="results-heading">{result.products.length ? 'A considered edit for you' : 'Build your live shortlist'}</h2>
              <BriefSummary intent={result.intent} />
            </div>

            <div className="results-controls">
              <span className="results-count-pill">{result.products.length} sources found</span>
              <button
                type="button"
                className="select-all-btn"
                onClick={allSelected ? onClearSelection : onSelectAll}
              >
                {allSelected ? 'Deselect all' : 'Select all'}
              </button>
              <div className="view-mode-toggle" role="group" aria-label="View layout">
                <button
                  type="button"
                  className={viewMode === 'cards' ? 'is-active' : ''}
                  onClick={() => setViewMode('cards')}
                  aria-label="Grid card view"
                  title="Card view"
                >
                  <Icon name="grid" size={16} />
                </button>
                <button
                  type="button"
                  className={viewMode === 'table' ? 'is-active' : ''}
                  onClick={() => setViewMode('table')}
                  aria-label="Detailed comparison table"
                  title="Table view"
                >
                  <Icon name="list" size={16} />
                </button>
              </div>
            </div>
          </div>

          {!result.products.length ? (
            <div className="empty-state results-empty-state">
              <span className="empty-state__icon">
                <Icon name="search" size={24} />
              </span>
              <h2>Live sources will appear here.</h2>
              <p>Describe what you want, add a reference image, or paste a public product or post URL to start a verified search.</p>
            </div>
          ) : viewMode === 'cards' ? (
            <div className="products-grid">
              {result.products.map((product) => (
                <ProductCard
                  key={product.id}
                  product={product}
                  selected={selectedIds.includes(product.id)}
                  focused={focusedId === product.id}
                  onToggle={onToggle}
                  onFocus={onFocus}
                  onOpenProduct={onOpenProduct}
                  onInspect={onInspect}
                  onSave={onSave}
                  saved={savedIds.includes(product.id)}
                />
              ))}
            </div>
          ) : (
            <ResultsTable
              products={result.products}
              selectedIds={selectedIds}
              focusedId={focusedId}
              onToggle={onToggle}
              onFocus={onFocus}
              onOpenProduct={onOpenProduct}
              onInspect={onInspect}
              onSave={onSave}
              savedIds={savedIds}
            />
          )}
        </section>
      </section>

      <SummaryPanel
        selectedProducts={selectedProducts}
        intent={result.intent}
        sourceMode={result.source?.mode}
        voice={voice}
        isSpeaking={isSpeaking}
        onSpeak={onSpeak}
        user={user}
        onSavePlan={onSavePlan}
        isSavingPlan={isSavingPlan}
        onStartCheckout={onStartCheckout}
        onRemoveItem={onRemoveSelectedItem}
      />

      {/* Floating mobile action bar */}
      {selectedProducts.length > 0 ? (
        <div className="mobile-plan-bar">
          <div className="mobile-plan-bar__info">
            <span className="mobile-plan-bar__count">{selectedProducts.length} items in plan</span>
            <strong className="mobile-plan-bar__total">
              ₹{selectedProducts.reduce((sum, p) => sum + productTotal(p), 0).toLocaleString('en-IN')}
            </strong>
          </div>
          <button
            type="button"
            className="primary-button mobile-plan-bar__cta"
            onClick={onSavePlan}
            disabled={isSavingPlan}
          >
            {isSavingPlan ? 'Saving…' : user ? 'Save Plan' : 'Sign in to Save'}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function AuthSheet({ onClose, onSignIn }) {
  const closeButtonRef = useRef(null);

  useEffect(() => {
    closeButtonRef.current?.focus();
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div
      className="modal-layer"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="auth-sheet" role="dialog" aria-modal="true" aria-labelledby="auth-title" aria-describedby="auth-copy">
        <button ref={closeButtonRef} type="button" className="icon-button auth-sheet__close" onClick={onClose} aria-label="Close sign in">
          <Icon name="close" size={19} />
        </button>
        <div className="auth-sheet__icon">
          <Icon name="shield" size={32} />
        </div>
        <h2 id="auth-title">Make your shortlist yours.</h2>
        <p id="auth-copy">Sign in with Google to save private purchase plans and revisit your source-linked retailer handoffs.</p>
        <button type="button" className="google-button" onClick={onSignIn}>
          <span className="google-mark">G</span>
          <span>Continue with Google</span>
        </button>
        <div className="auth-sheet__guarantee">
          <Icon name="shield" size={13} />
          <span>We never ask for payment card information. Checkout happens directly with retailers.</span>
        </div>
      </section>
    </div>
  );
}

function CheckoutSheet({ products, intent, paymentProvider, isSubmitting, onClose, onConfirm }) {
  const [confirmed, setConfirmed] = useState(false);
  const total = products.reduce((sum, product) => sum + productTotal(product), 0);
  const livePayment = paymentProvider === 'razorpay';

  return (
    <div className="modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="auth-sheet checkout-sheet" role="dialog" aria-modal="true" aria-labelledby="checkout-title">
        <button type="button" className="icon-button auth-sheet__close" onClick={onClose} aria-label="Close checkout">
          <Icon name="close" size={19} />
        </button>
        <span className="section-kicker">{livePayment ? 'Secure hosted checkout' : 'Local sandbox checkout'}</span>
        <h2 id="checkout-title">{livePayment ? 'Ready to pay securely?' : 'Ready to place this order?'}</h2>
        <p>
          {livePayment
            ? `Razorpay will securely handle payment for ${products.length} selected ${products.length === 1 ? 'item' : 'items'}. Artha records the order only after the signed payment callback is verified.`
            : `Artha will record a purchase order for ${products.length} selected ${products.length === 1 ? 'item' : 'items'} and start its tracking timeline. No card details are collected in this development checkout.`}
        </p>
        <div className="checkout-sheet__facts">
          <span>Total</span>
          <strong>{formatPrice(total)}</strong>
          <span>Delivery</span>
          <strong>{intent?.arrive_by || 'Confirm with retailer'}</strong>
          <span>Location</span>
          <strong>{intent?.location || 'Your delivery location'}</strong>
        </div>
        <label className="checkout-sheet__confirm">
          <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
          <span>I reviewed the items, total, and delivery estimate.</span>
        </label>
        <button type="button" className="primary-button" disabled={!confirmed || isSubmitting} onClick={onConfirm}>
          {isSubmitting ? (livePayment ? 'Opening secure checkout…' : 'Creating order…') : livePayment ? 'Continue to payment' : 'Confirm order'}
          <Icon name="arrow" size={16} />
        </button>
        <small className="checkout-sheet__notice">{livePayment ? 'Razorpay handles card and UPI details. Artha never sees payment credentials.' : 'Development order only. Live payment requires a configured production gateway.'}</small>
      </section>
    </div>
  );
}

function ProductEvidenceSheet({ product, onClose, onOpenProduct }) {
  if (!product) return null;
  const reviewScore = Number(product.review_reliability);
  const reviewAnalysis = product.review_analysis || {};
  const priceHistory = product.price_history || {};
  const reviewSources = Array.isArray(product.review_sources) ? product.review_sources : [];
  const researchSources = Array.isArray(product.research_sources) ? product.research_sources : [];
  const evidence = Array.isArray(product.evidence) ? product.evidence : [];
  const reviewLabel = reviewAnalysis.label || (Number.isFinite(reviewScore) ? `${Math.round(reviewScore * 100)}% reliability signal` : 'Not available');
  const historyLabel = priceHistory.trend_label || 'Price history not returned by this source';

  return (
    <div className="modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="auth-sheet evidence-sheet" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
        <button type="button" className="icon-button auth-sheet__close" onClick={onClose} aria-label="Close evidence">
          <Icon name="close" size={19} />
        </button>
        <span className="section-kicker">Evidence ledger</span>
        <h2 id="evidence-title">Why this made the edit.</h2>
        <p className="evidence-sheet__product">{sanitizeTitle(product.name)} · {product.seller || 'Retailer'}</p>

        <div className="evidence-sheet__facts">
          <div><span>Total today</span><strong>{formatPrice(productTotal(product))}</strong></div>
          <div><span>Delivery</span><strong>{product.delivery_label || 'Confirm at retailer'}</strong></div>
          <div><span>Review signal</span><strong>{reviewLabel}</strong></div>
          <div><span>Price history</span><strong>{historyLabel}</strong></div>
        </div>

        <div className="evidence-sheet__section">
          <div className="evidence-sheet__section-head">
            <span className="section-kicker">Review cross-check</span>
            {Number.isFinite(reviewScore) ? <strong>{Math.round(reviewScore * 100)}%</strong> : null}
          </div>
          <p>{product.review_summary || 'Review data needs retailer confirmation.'}</p>
          {reviewAnalysis.detail ? <small>{reviewAnalysis.detail}</small> : null}
          {reviewSources.length ? (
            <ul className="evidence-sheet__list">
              {reviewSources.map((source, index) => (
                <li key={`${source.name || 'source'}-${index}`}>
                  <span>{source.name || 'Review source'}</span>
                  <small>{source.count ? `${source.count} reviews` : 'Sample size unknown'}{source.rating ? ` · ★ ${source.rating}` : ''} · {source.signal || 'Signal requires confirmation'}</small>
                </li>
              ))}
            </ul>
          ) : (
            <small>Independent review sources were not returned. Treat the rating as unverified.</small>
          )}
        </div>

        <div className="evidence-sheet__section">
          <div className="evidence-sheet__section-head">
            <span className="section-kicker">Price context</span>
            {priceHistory.median_90d ? <strong>90 days</strong> : null}
          </div>
          <div className="evidence-sheet__price-row">
            <span>Low</span><b>{priceHistory.low_90d ? formatPrice(priceHistory.low_90d) : '—'}</b>
            <span>Median</span><b>{priceHistory.median_90d ? formatPrice(priceHistory.median_90d) : '—'}</b>
            <span>High</span><b>{priceHistory.high_90d ? formatPrice(priceHistory.high_90d) : '—'}</b>
          </div>
        </div>

        <div className="evidence-sheet__section">
          <div className="evidence-sheet__section-head">
            <span className="section-kicker">Research trail</span>
            <strong>{researchSources.length ? `${researchSources.length} check${researchSources.length === 1 ? '' : 's'}` : 'Not available'}</strong>
          </div>
          {researchSources.length ? (
            <ul className="evidence-sheet__list">
              {researchSources.map((source, index) => (
                <li key={`${source.name || 'research'}-${index}`}>
                  <span>{source.name || 'Research source'}</span>
                  <small>{source.status || 'unknown'} · {source.detail || 'Research detail unavailable'}</small>
                </li>
              ))}
            </ul>
          ) : (
            <small>Direct product-page research was not returned. Treat seller and review signals as unverified.</small>
          )}
        </div>

        <div className="evidence-sheet__section">
          <span className="section-kicker">Source checks</span>
          <ul className="evidence-sheet__checks">
            {(evidence.length ? evidence : ['Source-linked product data', 'Confirm seller checkout details']).map((item) => (
              <li key={item}><Icon name="check" size={13} /> {item}</li>
            ))}
          </ul>
        </div>

        <div className="evidence-sheet__actions">
          <button type="button" className="primary-button" onClick={() => onOpenProduct(product)} disabled={!product.url}>
            Open retailer page <Icon name="external" size={15} />
          </button>
          <button type="button" className="secondary-button" onClick={onClose}>Close evidence</button>
        </div>
      </section>
    </div>
  );
}

function SignInPrompt({ onSignIn }) {
  return (
    <div className="empty-state sign-in-prompt">
      <span className="empty-state__icon">
        <Icon name="user" size={26} />
      </span>
      <h2>Make your shortlist yours.</h2>
      <p>Sign in with Google to save private purchase plans, revisit retailer handoffs, and keep your finds synced.</p>
      <button type="button" className="google-button" onClick={onSignIn}>
        <span className="google-mark">G</span>
        <span>Continue with Google</span>
      </button>
    </div>
  );
}

function PlanCard({ plan }) {
  return (
    <article className="plan-card">
      <div className="plan-card__header">
        <div>
          <span className="section-kicker">Plan Ref: {plan.id}</span>
          <h2>Retailer Checkout Edit</h2>
          <p>
            Saved {formatDate(plan.created_at)} • {plan.items?.length || 0} linked products
          </p>
        </div>
        <span className="plan-status">
          <Icon name="checkCircle" size={13} />
          <span>Private Plan</span>
        </span>
      </div>
      <div className="plan-items">
        {(plan.items || []).map((item) => (
          <div className="plan-item" key={`${plan.id}-${item.id}`}>
            <ProductThumb product={item} small />
            <div className="plan-item__info">
              <strong>{sanitizeTitle(item.name)}</strong>
              <small>
                {item.seller} • {item.delivery_label || 'Arrives soon'}
              </small>
            </div>
            <b className="plan-item__price">{formatPrice(item.price)}</b>
            {item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer" className="text-button plan-item__link">
                <span>Go to retailer</span>
                <Icon name="external" size={13} />
              </a>
            ) : null}
          </div>
        ))}
      </div>
      <div className="plan-total">
        <div className="plan-total__label">
          <span>Known subtotal</span>
          <small>Subject to retailer checkout tax & delivery</small>
        </div>
        <strong>{formatPrice(plan.total)}</strong>
      </div>
      <p className="checkout-note">{plan.notice}</p>
    </article>
  );
}

function PlansView({ user, plans, onDiscover, onSignIn }) {
  if (!user) {
    return (
      <div className="page-stack">
        <SignInPrompt onSignIn={onSignIn} />
      </div>
    );
  }

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <span className="section-kicker">Saved Shortcuts</span>
          <h1>
            Purchase plans,
            <br />
            kept private.
          </h1>
          <p>Review your shortlist, compare final tallies, and click retailer links when you’re ready to order.</p>
        </div>
        <button type="button" className="primary-button" onClick={onDiscover}>
          <Icon name="plus" size={16} />
          <span>New search</span>
        </button>
      </div>
      {plans.length ? (
        <div className="plans-list">
          {plans.map((plan) => (
            <PlanCard key={plan.id} plan={plan} />
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <span className="empty-state__icon">
            <Icon name="box" size={26} />
          </span>
          <h2>No purchase plans yet.</h2>
          <p>Select verified products from your search results, then save your first deliberate plan.</p>
          <button type="button" className="primary-button empty-state__btn" onClick={onDiscover}>
            <span>Start discovering</span>
            <Icon name="arrow" size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

function SavedView({ products, savedIds, onSave, onDiscover, onOpenProduct, onTogglePlan, selectedIds }) {
  const saved = products.filter((product) => savedIds.includes(product.id));

  return (
    <div className="page-stack">
      <div className="page-heading">
        <div>
          <span className="section-kicker">Bookmarks</span>
          <h1>
            Keep the good finds
            <br />
            close at hand.
          </h1>
          <p>Bookmarked retailer discoveries from your searches. Add them into your plan or open them directly.</p>
        </div>
        <button type="button" className="primary-button" onClick={onDiscover}>
          <span>Discover more</span>
          <Icon name="arrow" size={16} />
        </button>
      </div>

      {saved.length ? (
        <div className="saved-grid">
          {saved.map((product) => {
            const isSelectedInPlan = selectedIds.includes(product.id);
            return (
              <article className="saved-card" key={product.id}>
                <div className="saved-card__media">
                  <ProductThumb product={product} />
                  <SourceMark product={product} />
                </div>
                <div className="saved-card__body">
                  <h3>{sanitizeTitle(product.name)}</h3>
                  <p className="saved-card__price">{formatPrice(productTotal(product))}</p>
                  <p className="saved-card__delivery">
                    <Icon name="truck" size={13} />
                    <span>{product.delivery_label || 'Check store'}</span>
                  </p>
                  <div className="saved-card__actions">
                    <button
                      type="button"
                      className={`plan-toggle-btn ${isSelectedInPlan ? 'is-active' : ''}`}
                      onClick={() => onTogglePlan(product.id)}
                    >
                      <Icon name={isSelectedInPlan ? 'check' : 'plus'} size={14} />
                      <span>{isSelectedInPlan ? 'In plan' : 'Add to plan'}</span>
                    </button>
                    <button
                      type="button"
                      className="quiet-action"
                      onClick={() => onOpenProduct(product)}
                      disabled={!product.url}
                    >
                      <Icon name="external" size={13} />
                    </button>
                    <button
                      type="button"
                      className="icon-button saved-remove-btn"
                      onClick={() => onSave(product.id)}
                      aria-label={`Remove ${product.name} from saved`}
                      title="Remove bookmark"
                    >
                      <Icon name="trash" size={15} />
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">
          <span className="empty-state__icon">
            <Icon name="bookmark" size={26} />
          </span>
          <h2>No saved picks yet.</h2>
          <p>Click the bookmark icon on any product to save it while you compare retailer sources.</p>
          <button type="button" className="primary-button empty-state__btn" onClick={onDiscover}>
            <span>Find items now</span>
            <Icon name="arrow" size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

function OrderTracker({ order }) {
  return (
    <div className="order-tracker" aria-label={`Order ${order.id} tracking timeline`}>
      {(order.timeline || []).map((step) => (
        <div className={`order-step ${step.complete ? 'is-complete' : ''}`} key={step.key}>
          <span className="order-step__node">{step.complete ? <Icon name="check" size={12} /> : null}</span>
          <div>
            <strong>{step.label}</strong>
            <small>{step.detail}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

function OrdersView({ user, orders, onDiscover, onCancel, onAdvance, onRequestReturn, onRefund, onSignIn }) {
  if (!user) {
    return (
      <div className="page-stack">
        <SignInPrompt onSignIn={onSignIn} />
      </div>
    );
  }

  return (
    <div className="page-stack orders-page">
      <div className="page-heading">
        <div>
          <span className="section-kicker">Purchase tracker</span>
          <h1>Know what happens next.</h1>
          <p>Every confirmed order keeps its total, seller handoff, delivery estimate, and next status in one place.</p>
        </div>
        <button type="button" className="primary-button" onClick={onDiscover}>
          <span>Find something else</span>
          <Icon name="arrow" size={16} />
        </button>
      </div>
      {orders.length ? (
        <div className="orders-list">
          {orders.map((order) => (
            <article className="order-card" key={order.id}>
              <header className="order-card__header">
                <div>
                  <span className="section-kicker">{order.payment_provider === 'sandbox' ? 'Sandbox order' : 'Confirmed order'}</span>
                  <h2>{order.id}</h2>
                  <p>Created {formatDate(order.created_at)} · Delivering to {order.location}</p>
                </div>
                <span className={`order-status order-status--${order.status}`}>{order.status.replace(/_/g, ' ')}</span>
              </header>
              <div className="order-card__summary">
                <div>
                  <strong>{formatPrice(order.total)}</strong>
                  <small>{order.items?.length || 0} {order.items?.length === 1 ? 'item' : 'items'} · {order.notice}</small>
                </div>
                <div className="order-actions">
                  {order.payment_provider === 'sandbox' && !['cancelled', 'delivered', 'return_requested', 'refunded'].includes(order.status) ? (
                    <button type="button" className="quiet-action" onClick={() => onAdvance(order.id)}>Advance sandbox status</button>
                  ) : null}
                  {order.status !== 'cancelled' && !['delivered', 'return_requested', 'refunded'].includes(order.status) ? (
                    <button type="button" className="quiet-action" onClick={() => onCancel(order.id)}>Cancel order</button>
                  ) : null}
                  {order.status === 'delivered' ? (
                    <button type="button" className="quiet-action" onClick={() => onRequestReturn(order.id)}>Request return</button>
                  ) : null}
                  {order.status === 'return_requested' ? (
                    <button type="button" className="quiet-action" onClick={() => onRefund(order.id)}>Record sandbox refund</button>
                  ) : null}
                </div>
              </div>
              <OrderTracker order={order} />
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <span className="empty-state__icon"><Icon name="truck" size={26} /></span>
          <h2>No orders yet.</h2>
          <p>Run a local catalog search, review the total, and confirm an order to see its tracker here.</p>
          <button type="button" className="primary-button empty-state__btn" onClick={onDiscover}>Start discovering <Icon name="arrow" size={16} /></button>
        </div>
      )}
    </div>
  );
}

function formatUsageCount(value) {
  if (value === null || value === undefined || value === '') return '—';
  const numeric = Number(value);
  return Number.isFinite(numeric) ? new Intl.NumberFormat('en-IN').format(numeric) : '—';
}

function usageProviderName(provider) {
  return {
    anakin: 'Anakin',
    ollama: 'Ollama',
    gemini: 'Gemini',
    kokoro: 'Kokoro',
    elevenlabs: 'ElevenLabs',
  }[provider] || provider || 'Unknown provider';
}

function usageOperationName(operation) {
  return String(operation || 'activity')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function usageRuntimeName(runtime) {
  return runtime === 'production' ? 'Production' : 'Local';
}

function usageRequestLabel(value) {
  const count = formatUsageCount(value);
  return `${count} ${Number(value) === 1 ? 'request' : 'requests'}`;
}

function usageTimestamp(value) {
  const parsed = new Date(value || '');
  if (Number.isNaN(parsed.getTime())) return 'Time unavailable';
  return new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed);
}

function UsageView({ usage, usageWindow, usageRuntime, onWindowChange, onRuntimeChange, onRefresh, isLoading, error, onSignIn }) {
  const totals = usage?.totals || {};
  const providerRows = usage?.by_provider || [];
  const recent = usage?.recent || [];
  const activeAi = usage?.active_ai || {};
  const activeVoice = usage?.active_voice || {};
  const activeRuntime = usageRuntimeName(usage?.active_runtime);
  const maxTokens = Math.max(...providerRows.map((row) => Number(row.total_tokens || 0)), 1);
  const maxRequests = Math.max(...providerRows.map((row) => Number(row.requests || 0)), 1);
  const hasUsage = providerRows.length > 0 || recent.length > 0;

  return (
    <div className="page-stack usage-page">
      <div className="page-heading usage-heading">
        <div>
          <span className="section-kicker">Operations</span>
          <h1>
            Usage you can see.
            <br />
            Runtime, without guesswork.
          </h1>
          <p>Track metered AI tokens and unmetered source and voice activity from the same Artha workspace.</p>
        </div>
        <button type="button" className="quiet-action usage-refresh" onClick={onRefresh} disabled={isLoading}>
          <Icon name="waveform" size={15} />
          <span>{isLoading ? 'Refreshing…' : 'Refresh ledger'}</span>
        </button>
      </div>

      <section className="usage-toolbar" aria-label="Usage filters">
        <div className="usage-toolbar__runtime">
          <span className={`usage-status-dot ${usage?.environment === 'production' ? 'is-production' : ''}`} />
          <div>
            <strong>Active server: {activeRuntime}</strong>
            <small>Filters change the ledger view; they do not switch the running deployment.</small>
          </div>
        </div>
        <div className="usage-toolbar__controls">
          <fieldset className="usage-toggle-group">
            <legend>View runtime</legend>
            <div className="usage-toggle-group__buttons">
              {['all', 'local', 'production'].map((option) => (
                <button
                  type="button"
                  key={option}
                  aria-pressed={usageRuntime === option}
                  className={usageRuntime === option ? 'is-selected' : ''}
                  onClick={() => onRuntimeChange(option)}
                >
                  {option === 'all' ? 'All' : usageRuntimeName(option)}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="usage-toggle-group">
            <legend>Window</legend>
            <div className="usage-toggle-group__buttons">
              {[7, 30, 90].map((days) => (
                <button
                  type="button"
                  key={days}
                  aria-pressed={usageWindow === days}
                  className={usageWindow === days ? 'is-selected' : ''}
                  onClick={() => onWindowChange(days)}
                >
                  {days}d
                </button>
              ))}
            </div>
          </fieldset>
        </div>
      </section>

      {error ? (
        <div className="usage-error" role="alert">
          <div>
            <strong>Usage ledger unavailable.</strong>
            <p>{error}</p>
          </div>
          <div className="usage-error__actions">
            {onSignIn && /sign in/i.test(error) ? (
              <button type="button" className="primary-button" onClick={onSignIn}>Sign in</button>
            ) : null}
            <button type="button" className="quiet-action" onClick={onRefresh}>Retry</button>
          </div>
        </div>
      ) : null}

      <section className="usage-runtime-grid" aria-label="Runtime status">
        <article className="usage-runtime-card">
          <span className="usage-card__label">Server runtime</span>
          <strong>{activeRuntime}</strong>
          <small>{usage?.environment || 'development'} environment</small>
        </article>
        <article className="usage-runtime-card">
          <span className="usage-card__label">AI route</span>
          <strong>{usageProviderName(activeAi.provider)}</strong>
          <small>{activeAi.model || (activeAi.configured ? 'Configured' : 'Not configured')}</small>
        </article>
        <article className="usage-runtime-card">
          <span className="usage-card__label">Live sources</span>
          <strong>{usage?.anakin_configured ? 'Anakin ready' : 'Not configured'}</strong>
          <small>Search requests are tracked as unmetered activity.</small>
        </article>
        <article className="usage-runtime-card">
          <span className="usage-card__label">Voice route</span>
          <strong>{activeVoice.label || usageProviderName(activeVoice.provider)}</strong>
          <small>{activeVoice.model || 'Browser speech'}</small>
        </article>
      </section>

      <section className="usage-metrics" aria-label="Usage totals" aria-live="polite">
        {[
          ['Total tokens', totals.total_tokens, 'input + output, when the provider reports it'],
          ['Input tokens', totals.input_tokens, 'prompt tokens reported by the AI provider'],
          ['Output tokens', totals.output_tokens, 'generated tokens reported by the AI provider'],
          ['Cached tokens', totals.cached_tokens, 'provider-reported cached prompt tokens'],
          ['Requests', totals.requests ?? 0, `${formatUsageCount(totals.metered_requests ?? 0)} metered · ${formatUsageCount(totals.unmetered_requests ?? 0)} activity`],
        ].map(([label, value, meta]) => (
          <article className="usage-metric-card" key={label}>
            <span className="usage-card__label">{label}</span>
            <strong>{formatUsageCount(value)}</strong>
            <small>{meta}</small>
          </article>
        ))}
      </section>

      <div className="usage-content-grid">
        <section className="usage-panel">
          <div className="usage-panel__header">
            <div>
              <span className="section-kicker">Provider view</span>
              <h2>Where activity is going</h2>
            </div>
            <span className="usage-panel__caption">{usage?.window_days || usageWindow} day window</span>
          </div>
          {providerRows.length ? (
            <div className="usage-provider-list">
              {providerRows.map((row) => {
                const tokenCount = Number(row.total_tokens || 0);
                const requestCount = Number(row.requests || 0);
                const width = tokenCount ? Math.max(8, (tokenCount / maxTokens) * 100) : Math.max(8, (requestCount / maxRequests) * 100);
                return (
                  <div className="usage-provider-row" key={`${row.provider}-${row.operation}-${row.runtime}`}>
                    <div className="usage-provider-row__topline">
                      <div>
                        <strong>{usageProviderName(row.provider)}</strong>
                        <span>{usageOperationName(row.operation)} · {usageRuntimeName(row.runtime)}</span>
                      </div>
                      <b>{row.total_tokens === null ? usageRequestLabel(row.requests) : `${formatUsageCount(row.total_tokens)} tokens`}</b>
                    </div>
                    <div className="usage-provider-bar" aria-hidden="true">
                      <span style={{ width: `${width}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="usage-empty">
              <Icon name="chart" size={22} />
              <strong>No activity in this window.</strong>
              <p>Run a search or play a server voice summary and the ledger will appear here.</p>
            </div>
          )}
        </section>

        <section className="usage-panel usage-panel--activity">
          <div className="usage-panel__header">
            <div>
              <span className="section-kicker">Recent events</span>
              <h2>Latest activity</h2>
            </div>
            <span className="usage-panel__caption">No secrets stored</span>
          </div>
          {recent.length ? (
            <ul className="usage-event-list">
              {recent.slice(0, 8).map((event) => (
                <li className="usage-event" key={event.id}>
                  <div>
                    <strong>{usageProviderName(event.provider)}</strong>
                    <small>{usageOperationName(event.operation)} · {usageRuntimeName(event.runtime)} · {usageTimestamp(event.created_at)}</small>
                  </div>
                  <span>{event.total_tokens === null ? `${formatUsageCount(event.input_characters || event.output_bytes || event.requests || 0)} ${event.input_characters ? 'chars' : event.output_bytes ? 'bytes' : 'events'}` : `${formatUsageCount(event.total_tokens)} tokens`}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="usage-empty usage-empty--compact">
              <p>No recent provider events yet.</p>
            </div>
          )}
        </section>
      </div>

      <section className="usage-panel usage-panel--table">
        <div className="usage-panel__header">
          <div>
            <span className="section-kicker">Inspect</span>
            <h2>Token and activity breakdown</h2>
          </div>
          <span className="usage-panel__caption">Raw counts from the persistent ledger</span>
        </div>
        {hasUsage ? (
          <div className="usage-table-wrap">
            <table className="usage-table">
              <caption className="sr-only">Provider token and activity breakdown</caption>
              <thead>
                <tr>
                  <th scope="col">Provider</th>
                  <th scope="col">Operation</th>
                  <th scope="col">Runtime</th>
                  <th scope="col">Input</th>
                  <th scope="col">Output</th>
                  <th scope="col">Cached</th>
                  <th scope="col">Total</th>
                  <th scope="col">Requests</th>
                </tr>
              </thead>
              <tbody>
                {providerRows.map((row) => (
                  <tr key={`table-${row.provider}-${row.operation}-${row.runtime}`}>
                    <td>{usageProviderName(row.provider)}</td>
                    <td>{usageOperationName(row.operation)}</td>
                    <td>{usageRuntimeName(row.runtime)}</td>
                    <td>{formatUsageCount(row.input_tokens)}</td>
                    <td>{formatUsageCount(row.output_tokens)}</td>
                    <td>{formatUsageCount(row.cached_tokens)}</td>
                    <td>{formatUsageCount(row.total_tokens)}</td>
                    <td>{formatUsageCount(row.requests)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="usage-empty usage-empty--table">
            <p>There are no events to break down for this runtime and window.</p>
          </div>
        )}
      </section>
    </div>
  );
}

function Toast({ message }) {
  return message ? (
    <div className="toast" role="status">
      <Icon name="checkCircle" size={16} />
      <span>{message}</span>
    </div>
  ) : null;
}

export default function App() {
  const [pendingSearch] = useState(readPendingSearch);
  const [activeView, setActiveView] = useState(() => viewFromPath(window.location.pathname));
  const [query, setQuery] = useState(() => pendingSearch?.query || DEFAULT_INTENT.raw_text);
  const [postUrl, setPostUrl] = useState(() => pendingSearch?.postUrl || '');
  const [location, setLocation] = useState(() => pendingSearch?.location || null);
  const [showPostUrl, setShowPostUrl] = useState(false);
  const [reference, setReference] = useState(null);
  const [result, setResult] = useState(() => pendingSearch?.result || DEFAULT_RESULT);
  const [selectedIds, setSelectedIds] = useState(() => pendingSearch?.selectedIds || pendingSearch?.result?.selected_product_ids || DEFAULT_RESULT.selected_product_ids);
  const [focusedId, setFocusedId] = useState(() => pendingSearch?.result?.products?.[0]?.id || DEFAULT_RESULT.products[0]?.id || '');
  const [isSearching, setIsSearching] = useState(false);
  const [searchStage, setSearchStage] = useState(0);
  const [savedIds, setSavedIds] = useState(readSavedIds);
  const [plans, setPlans] = useState([]);
  const [orders, setOrders] = useState([]);
  const [health, setHealth] = useState({ anakin_configured: false, ai: { provider: 'ollama' }, payment_provider: 'sandbox', payment_configured: true });
  const [voice, setVoice] = useState({ provider: 'browser', label: 'Local browser voice' });
  const [usage, setUsage] = useState(null);
  const [usageWindow, setUsageWindow] = useState(30);
  const [usageRuntime, setUsageRuntime] = useState('all');
  const [isUsageLoading, setIsUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState('');
  const [user, setUser] = useState(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [isSavingPlan, setIsSavingPlan] = useState(false);
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [evidenceProduct, setEvidenceProduct] = useState(null);
  const [isCreatingOrder, setIsCreatingOrder] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [toast, setToast] = useState('');
  const audioRef = useRef(null);

  const selectedProducts = useMemo(
    () => result.products.filter((product) => selectedIds.includes(product.id)),
    [result.products, selectedIds],
  );

  const refreshPlans = useCallback(async () => {
    if (!user?.id) return;
    const body = await getPlans();
    setPlans(body.plans || []);
  }, [user?.id]);

  const refreshOrders = useCallback(async () => {
    if (!user?.id) return;
    const body = await getOrders();
    setOrders(body.orders || []);
  }, [user?.id]);

  const refreshUsage = useCallback(async () => {
    setIsUsageLoading(true);
    setUsageError('');
    try {
      const body = await getUsage({ days: usageWindow, runtime: usageRuntime });
      setUsage(body);
    } catch (error) {
      setUsageError(error.message || 'Could not load usage right now.');
    } finally {
      setIsUsageLoading(false);
    }
  }, [usageRuntime, usageWindow]);

  useEffect(() => {
    let active = true;
    Promise.all([
      getHealth().catch(() => null),
      getSession().catch(() => null),
      getVoiceStatus().catch(() => null),
    ]).then(([nextHealth, session, nextVoice]) => {
      if (!active) return;
      if (nextHealth) setHealth(nextHealth);
      if (session?.user) setUser(session.user);
      if (nextVoice) {
        setVoice(nextVoice);
        if (nextVoice.provider === 'kokoro') {
          warmVoice()
            .then((warmState) => setVoice((current) => ({ ...current, ...warmState })))
            .catch(() => {
              /* The first playback still reports a precise provider error if warm-up fails. */
            });
        }
      }
    });
    const params = new URLSearchParams(window.location.search);
    if (params.get('auth') === 'success') {
      setToast('You are signed in. Your purchase plans are private to this account.');
      try {
        window.sessionStorage.removeItem(PENDING_SEARCH_KEY);
      } catch {
        /* Private browsing can deny session storage. */
      }
    }
    if (params.get('auth_error')) {
      setToast('Google sign-in did not finish. Please try again.');
    }
    if (params.has('auth') || params.has('auth_error')) {
      window.history.replaceState({}, '', window.location.pathname);
    }
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(SAVED_KEY, JSON.stringify(savedIds));
    } catch {
      /* Private browsing can deny storage. */
    }
  }, [savedIds]);

  useEffect(() => {
    if (activeView === 'plans') refreshPlans().catch((error) => setToast(error.message));
  }, [activeView, refreshPlans]);

  useEffect(() => {
    if (activeView !== 'orders') return undefined;
    const loadOrders = () => refreshOrders().catch((error) => setToast(error.message));
    loadOrders();
    const timer = window.setInterval(loadOrders, 30_000);
    return () => window.clearInterval(timer);
  }, [activeView, refreshOrders]);

  useEffect(() => {
    if (activeView === 'usage') refreshUsage();
  }, [activeView, refreshUsage]);

  useEffect(() => {
    if (!isSearching) return undefined;
    const maxStage = Math.max((result.workflow?.length || 6) - 1, 0);
    const timer = window.setInterval(() => setSearchStage((current) => Math.min(current + 1, maxStage)), 620);
    return () => window.clearInterval(timer);
  }, [isSearching, result.workflow?.length]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(''), 4200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(
    () => () => {
      audioRef.current?.pause();
      window.speechSynthesis?.cancel();
    },
    [],
  );

  const startNewSearch = useCallback(() => {
    setActiveView('discover');
    setQuery(DEFAULT_INTENT.raw_text);
    setPostUrl('');
    setLocation(null);
    setShowPostUrl(false);
    setReference(null);
    setResult(DEFAULT_RESULT);
    setSelectedIds([]);
    setFocusedId('');
  }, []);

  const handleSearchWithPayload = useCallback(
    async (text, url, ref) => {
      if ((!text?.trim() && !url?.trim() && !ref?.dataUrl) || isSearching) return;
      setIsSearching(true);
      setSearchStage(0);
      const shouldRefine = Boolean(result.search_id && result.products.length && text?.trim() && !url?.trim() && !ref?.dataUrl);
      try {
        const body = shouldRefine
          ? await refineAgentSearch({
              text: text.trim(),
              intent: result.intent,
              products: result.products,
              source: result.source,
            })
          : await runAgentSearch({
              text: text?.trim() || 'Find products that match this reference.',
              post_url: url?.trim() || null,
              image_name: ref?.name || null,
              reference_image: referencePayload(ref),
              location_coordinates: location,
            });
        if (!body.products?.length) throw new Error('No retailer sources were found for that brief.');
        setResult(body);
        setSelectedIds(
          body.selected_product_ids?.length
            ? body.selected_product_ids
            : body.products.slice(0, 3).map((product) => product.id),
        );
        setFocusedId(body.products[0]?.id || '');
        setToast(shouldRefine ? 'Shortlist refined from the existing research.' : 'Live retailer sources checked and ranked.');
      } catch (error) {
        setToast(error.message || 'The search could not complete. Please try again.');
      } finally {
        setIsSearching(false);
      }
    },
    [isSearching, location, result],
  );

  const handleSearch = useCallback(
    (event) => {
      if (event) event.preventDefault();
      handleSearchWithPayload(query, postUrl, reference);
    },
    [handleSearchWithPayload, postUrl, query, reference],
  );

  const handlePickPrompt = useCallback(
    (prompt) => {
      setQuery(prompt);
      handleSearchWithPayload(prompt, postUrl, reference);
    },
    [handleSearchWithPayload, postUrl, reference],
  );

  const toggleProduct = useCallback((id) => {
    setSelectedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }, []);

  const toggleSaved = useCallback(
    (id) => {
      const wasSaved = savedIds.includes(id);
      setSavedIds((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
      setToast(wasSaved ? 'Removed from saved picks.' : 'Saved for later.');
    },
    [savedIds],
  );

  const handleSelectAll = useCallback(() => {
    setSelectedIds(result.products.map((p) => p.id));
  }, [result.products]);

  const handleClearSelection = useCallback(() => {
    setSelectedIds([]);
  }, []);

  const handleRemoveSelectedItem = useCallback((id) => {
    setSelectedIds((current) => current.filter((item) => item !== id));
  }, []);

  const handleSavePlan = useCallback(async () => {
    if (!selectedProducts.length || isSavingPlan) return;
    if (!user) {
      setAuthOpen(true);
      return;
    }
    setIsSavingPlan(true);
    try {
      const body = await createPlan({ search_id: result.search_id, products: selectedProducts });
      setPlans((current) => [body.plan, ...current.filter((plan) => plan.id !== body.plan.id)]);
      setActiveView('plans');
      setToast('Purchase plan saved. Open retailer links when you are ready.');
    } catch (error) {
      if (/sign in/i.test(error.message)) setAuthOpen(true);
      else setToast(error.message || 'Could not save this purchase plan.');
    } finally {
      setIsSavingPlan(false);
    }
  }, [isSavingPlan, result.search_id, selectedProducts, user]);

  const handleStartCheckout = useCallback(() => {
    if (!selectedProducts.length) {
      setToast('Select at least one product before checkout.');
      return;
    }
    if (!user) {
      setAuthOpen(true);
      return;
    }
    if (health.payment_configured === false) {
      setToast('Checkout is not configured on this deployment yet. No order was created.');
      return;
    }
    setCheckoutOpen(true);
  }, [health.payment_configured, selectedProducts.length, user]);

  const handleConfirmOrder = useCallback(async () => {
    if (!selectedProducts.length || !user || isCreatingOrder) return;
    setIsCreatingOrder(true);
    const hostedPayment = health.payment_provider === 'razorpay';
    let checkoutOpened = false;
    const purchasePayload = {
      confirmed: true,
      search_id: result.search_id,
      products: selectedProducts,
      intent: result.intent,
      location: result.intent?.location,
    };
    try {
      if (hostedPayment) {
        const paymentBody = await createPaymentOrder(purchasePayload);
        const Razorpay = await loadRazorpayCheckout();
        const checkout = new Razorpay({
          key: paymentBody.payment.key_id,
          amount: paymentBody.payment.amount,
          currency: paymentBody.payment.currency,
          name: paymentBody.payment.name,
          description: paymentBody.payment.description,
          order_id: paymentBody.payment.order_id,
          prefill: paymentBody.payment.prefill,
          theme: { color: '#ef3d78' },
          handler: async (response) => {
            try {
              const verified = await verifyPayment(response);
              setOrders((current) => [verified.order, ...current.filter((order) => order.id !== verified.order.id)]);
              setCheckoutOpen(false);
              setActiveView('orders');
              setToast(`Payment verified. Order ${verified.order.id} is confirmed.`);
            } catch (error) {
              setToast(error.message || 'Payment verification failed. No order was recorded.');
            } finally {
              setIsCreatingOrder(false);
            }
          },
          modal: { ondismiss: () => { setIsCreatingOrder(false); setToast('Payment was cancelled. No order was recorded.'); } },
        });
        checkout.on('payment.failed', () => {
          setIsCreatingOrder(false);
          setToast('Payment failed. No order was recorded.');
        });
        checkout.open();
        checkoutOpened = true;
        return;
      }
      const body = await createOrder(purchasePayload);
      setOrders((current) => [body.order, ...current.filter((order) => order.id !== body.order.id)]);
      setCheckoutOpen(false);
      setActiveView('orders');
      setToast(`Order ${body.order.id} confirmed in the local tracker.`);
    } catch (error) {
      setToast(error.message || 'The order could not be created.');
    } finally {
      if (!checkoutOpened) setIsCreatingOrder(false);
    }
  }, [health.payment_provider, isCreatingOrder, result.intent, result.search_id, selectedProducts, user]);

  const handleCancelOrder = useCallback(async (orderId) => {
    try {
      const response = await cancelOrder(orderId);
      setOrders((current) => current.map((order) => (order.id === orderId ? response.order : order)));
      setToast('Order cancelled in the tracker.');
    } catch (error) {
      setToast(error.message || 'The order could not be cancelled.');
    }
  }, []);

  const updateOrderFromAction = useCallback(async (action, orderId, successMessage) => {
    try {
      const response = await action(orderId);
      setOrders((current) => current.map((order) => (order.id === orderId ? response.order : order)));
      setToast(successMessage(response.order));
    } catch (error) {
      setToast(error.message || 'The order could not be updated.');
    }
  }, []);

  const handleAdvanceOrder = useCallback(
    (orderId) => updateOrderFromAction(advanceOrder, orderId, (order) => `Sandbox tracker moved to ${order.status.replace(/_/g, ' ')}.`),
    [updateOrderFromAction],
  );

  const handleRequestReturn = useCallback(
    (orderId) => updateOrderFromAction(requestReturn, orderId, () => 'Sandbox return request recorded.'),
    [updateOrderFromAction],
  );

  const handleRefund = useCallback(
    (orderId) => updateOrderFromAction(completeRefund, orderId, () => 'Sandbox refund recorded locally.'),
    [updateOrderFromAction],
  );

  const stopSpeaking = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    window.speechSynthesis?.cancel();
    setIsSpeaking(false);
  }, []);

  const handleSpeak = useCallback(async () => {
    if (isSpeaking) {
      stopSpeaking();
      return;
    }
    if (!selectedProducts.length) {
      setToast('Select at least one product before listening to an edit.');
      return;
    }
    const text = `Your purchase plan includes ${selectedProducts.map((p) => sanitizeTitle(p.name)).join(', ')}. The current subtotal is ${formatPrice(selectedProducts.reduce((sum, p) => sum + productTotal(p), 0))}. ${result.summary?.delivery_label || 'Confirm delivery with each retailer.'}`;
    try {
      setIsSpeaking(true);
      if (voice?.provider === 'browser') {
        if (!window.speechSynthesis) throw new Error('Local browser voice is unavailable in this browser.');
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'en-IN';
        utterance.rate = 1;
        utterance.onend = () => setIsSpeaking(false);
        utterance.onerror = () => {
          setIsSpeaking(false);
          setToast('Local browser voice could not play this summary.');
        };
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(utterance);
        return;
      }
      const response = await speakText(text);
      if (!response.blob) throw new Error('Voice service did not return audio.');
      const audio = new Audio(URL.createObjectURL(response.blob));
      audioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(audio.src);
        setIsSpeaking(false);
      };
      await audio.play();
    } catch (error) {
      setIsSpeaking(false);
      setToast(error.message || 'Voice playback could not start.');
    }
  }, [isSpeaking, result.summary, selectedProducts, stopSpeaking, voice?.provider]);

  const handleSignOut = useCallback(async () => {
    try {
      await signOut();
      setUser(null);
      setPlans([]);
      setOrders([]);
      setActiveView('discover');
      setToast('Signed out. Your saved local picks remain in this browser.');
    } catch (error) {
      setToast(error.message || 'Could not sign out right now.');
    }
  }, []);

  const openProduct = useCallback((product) => {
    if (product?.url) window.open(product.url, '_blank', 'noopener,noreferrer');
  }, []);

  const inspectProduct = useCallback((product) => {
    setEvidenceProduct(product || null);
  }, []);

  const startSignIn = useCallback(
    (next = '/') => {
      preservePendingSearch({ query, postUrl, result, selectedIds, location });
      beginGoogleSignIn(next);
    },
    [location, postUrl, query, result, selectedIds],
  );

  const view =
    activeView === 'discover' ? (
      <DiscoverView
        result={result}
        query={query}
        setQuery={setQuery}
        postUrl={postUrl}
        setPostUrl={setPostUrl}
        showPostUrl={showPostUrl}
        setShowPostUrl={setShowPostUrl}
        reference={reference}
        location={location}
        onLocation={setLocation}
        onReferenceChange={setReference}
        onRemoveReference={() => setReference(null)}
        onSearch={handleSearch}
        isSearching={isSearching}
        searchStage={searchStage}
        selectedIds={selectedIds}
        focusedId={focusedId}
        onToggle={toggleProduct}
        onFocus={setFocusedId}
        onOpenProduct={openProduct}
        onInspect={inspectProduct}
        onSave={toggleSaved}
        savedIds={savedIds}
        voice={voice}
        isSpeaking={isSpeaking}
        onSpeak={handleSpeak}
        user={user}
        onSavePlan={handleSavePlan}
        isSavingPlan={isSavingPlan}
        onStartCheckout={handleStartCheckout}
        onToast={setToast}
        onPickPrompt={handlePickPrompt}
        onSelectAll={handleSelectAll}
        onClearSelection={handleClearSelection}
        onRemoveSelectedItem={handleRemoveSelectedItem}
      />
    ) : activeView === 'saved' ? (
      <SavedView
        products={result.products}
        savedIds={savedIds}
        onSave={toggleSaved}
        onDiscover={startNewSearch}
        onOpenProduct={openProduct}
        onTogglePlan={toggleProduct}
        selectedIds={selectedIds}
      />
    ) : activeView === 'usage' ? (
      <UsageView
        usage={usage}
        usageWindow={usageWindow}
        usageRuntime={usageRuntime}
        onWindowChange={setUsageWindow}
        onRuntimeChange={setUsageRuntime}
        onRefresh={refreshUsage}
        isLoading={isUsageLoading}
        error={usageError}
        onSignIn={() => startSignIn('/usage')}
      />
    ) : activeView === 'orders' ? (
      <OrdersView
        user={user}
        orders={orders}
        onDiscover={startNewSearch}
        onCancel={handleCancelOrder}
        onAdvance={handleAdvanceOrder}
        onRequestReturn={handleRequestReturn}
        onRefund={handleRefund}
        onSignIn={() => startSignIn('/orders')}
      />
    ) : (
      <PlansView
        user={user}
        plans={plans}
        onDiscover={startNewSearch}
        onSignIn={() => startSignIn('/plans')}
      />
    );

  return (
    <div className="app-shell">
      <NavRail
        activeView={activeView}
        onNavigate={setActiveView}
        onReset={startNewSearch}
        health={health}
        planCount={plans.length}
      />
      <main className="main-content" id="main-content">
        <TopHeader
          activeView={activeView}
          user={user}
          onSignIn={() => startSignIn(activeView === 'plans' ? '/plans' : activeView === 'orders' ? '/orders' : activeView === 'usage' ? '/usage' : '/')}
          onSignOut={handleSignOut}
        />
        {view}
      </main>
      <MobileNav activeView={activeView} onNavigate={setActiveView} planCount={plans.length} />
      {authOpen ? <AuthSheet onClose={() => setAuthOpen(false)} onSignIn={() => startSignIn('/')} /> : null}
      {checkoutOpen ? (
        <CheckoutSheet
          products={selectedProducts}
          intent={result.intent}
          paymentProvider={health.payment_provider}
          isSubmitting={isCreatingOrder}
          onClose={() => setCheckoutOpen(false)}
          onConfirm={handleConfirmOrder}
        />
      ) : null}
      {evidenceProduct ? (
        <ProductEvidenceSheet
          product={evidenceProduct}
          onClose={() => setEvidenceProduct(null)}
          onOpenProduct={openProduct}
        />
      ) : null}
      <Toast message={toast} />
    </div>
  );
}
