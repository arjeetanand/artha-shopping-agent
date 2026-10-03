import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from './components/Icon';
import { TalkDrawer } from './components/TalkDrawer';
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
  runAgentSearchAsync,
  signOut,
  speakText,
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

function missionFromIntent(intent) {
  const mission = intent?.mission || {};
  return {
    occasion: mission.occasion || intent?.occasion || '',
    budget: mission.budget || intent?.budget || '',
    arrive_by_date: mission.arrive_by_date || '',
    pincode: mission.pincode || intent?.pincode || '',
    size: mission.size || intent?.size || '',
    color: mission.color || intent?.color || '',
    style: mission.style || intent?.style || '',
  };
}

function retailerUrl(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function observedTime(value) {
  const date = new Date(value);
  return value && !Number.isNaN(date.getTime())
    ? date.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' })
    : 'Time not available';
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

function preservePendingSearch({ query, postUrl, result, selectedIds, location, pendingAction }) {
  try {
    window.sessionStorage.setItem(
      PENDING_SEARCH_KEY,
      JSON.stringify({
        saved_at: Date.now(),
        query,
        postUrl,
        result,
        selectedIds,
        location,
        pending_action: pendingAction || null,
      }),
    );
  } catch {
    /* Private browsing can deny session storage; sign-in still works. */
  }
}

function clearPendingSearch() {
  try {
    window.sessionStorage.removeItem(PENDING_SEARCH_KEY);
  } catch {
    /* Private browsing can deny session storage. */
  }
}

function viewFromPath(pathname = '/') {
  const path = String(pathname).replace(/\/+$/, '') || '/';
  return ({ '/saved': 'saved', '/plans': 'plans', '/orders': 'orders', '/usage': 'usage' })[path] || 'discover';
}

function useDialogFocusTrap(open, dialogRef, initialRef, onClose) {
  const previousFocusRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => initialRef.current?.focus());
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = [...dialog.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')]
        .filter((element) => !element.hidden && element.offsetParent !== null);
      if (!focusable.length) {
        event.preventDefault();
        initialRef.current?.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown);
      const restore = previousFocusRef.current;
      if (restore && document.contains(restore)) restore.focus();
      previousFocusRef.current = null;
    };
  }, [dialogRef, initialRef, onClose, open]);
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
          aria-current={activeView === item.id ? 'page' : undefined}
        >
          <Icon name={item.icon} size={20} />
          <span>{item.id === 'plans' ? 'Plans' : item.label}</span>
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

function TopHeader({ activeView, user, isSessionLoading, onSignIn, onSignOut, onOpenTalk }) {
  return (
    <header className="top-header">
      <span className="mobile-brand" aria-label="Artha">ARTHA</span>
      <div className="top-header__breadcrumb">
        <span className="top-header__crumb-app">Artha</span>
        <span className="top-header__separator">/</span>
        <span className="top-header__section">{SECTION_TITLES[activeView]}</span>
      </div>
      <div className="top-header__actions">
        <button type="button" className="talk-button" onClick={onOpenTalk} aria-label="Talk to Artha">
          <Icon name="waveform" size={16} />
          <span>Talk to Artha</span>
        </button>
        {isSessionLoading ? (
          <span className="account-loading" role="status">Checking account…</span>
        ) : user ? (
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
      </div>
    </header>
  );
}

function ProductThumb({ product, small = false }) {
  const position = `${Math.max(0, Math.min(2, Number(product.crop_index || 0))) * 50}% center`;
  const image = String(product.image || '').trim();
  const chairLike = /chair|desk|office|lumbar|ergonomic/i.test(`${product.name || ''} ${product.category || ''}`);
  const fallback = chairLike ? '/assets/neutral-office-chair-fallback.png' : '/assets/editorial-outfit-triptych.png';
  return (
    <span
      className={`product-thumb ${small ? 'product-thumb--small' : ''} ${image ? '' : 'product-thumb--fallback'}`}
      role="img"
      aria-label={`${product.name} thumbnail`}
      style={{
        backgroundImage: `url(${image || fallback})`,
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
  mission,
  onMissionChange,
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
  searchError,
  onToast,
  onPickPrompt,
  onOpenTalk,
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
  const setMissionField = (field, value) => onMissionChange({ ...mission, [field]: value });

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
        <fieldset className="mission-brief">
            <legend>{hasResults ? 'Adjust your mission, then refine' : 'Mission brief'}</legend>
            <label>
              <span>Occasion</span>
              <input value={mission.occasion} onChange={(event) => setMissionField('occasion', event.target.value)} placeholder="Wedding, work, dinner…" />
            </label>
            <label>
              <span>Budget</span>
              <input value={mission.budget} onChange={(event) => setMissionField('budget', event.target.value.replace(/[^\d]/g, ''))} inputMode="numeric" placeholder="₹4,000" />
            </label>
            <label>
              <span>Arrive by</span>
              <input value={mission.arrive_by_date} onChange={(event) => setMissionField('arrive_by_date', event.target.value)} type="date" min={new Date().toISOString().slice(0, 10)} />
            </label>
            <label>
              <span>Pincode</span>
              <input value={mission.pincode} onChange={(event) => setMissionField('pincode', event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" placeholder="560001" />
            </label>
          </fieldset>
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
            <button type="button" className="secondary-control talk-control" onClick={onOpenTalk}>
              <Icon name="waveform" size={16} />
              <span>Talk to Artha</span>
            </button>
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

      {searchError ? (
        <div className="composer-error" role="alert">
          <Icon name="info" size={15} />
          <span>{searchError}</span>
          <button type="button" onClick={onSearch}>Retry</button>
        </div>
      ) : null}

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

function AgentStrip({ workflow, isSearching, searchStage, hasResults, resultCount = 0, resultStatus = '', searchError = '', onOpenTalk }) {
  const stages = [
    { label: 'Lock mission', copy: 'Reading the deadline and hard constraints', indexes: [0, 1] },
    { label: 'Inspect sources', copy: 'Finding retailer and delivery evidence', indexes: [2, 3] },
    { label: 'Check claims', copy: 'Checking price, stock, and variants', indexes: [4, 5] },
    { label: 'Make decision', copy: 'Applying the evidence gate', indexes: [6] },
  ];
  const workflowLength = Math.max(workflow?.length || 7, 1);
  const activeAgents = Array.isArray(workflow) ? workflow.filter((step) => step?.status === 'working') : [];
  const completedAgents = Array.isArray(workflow) ? workflow.filter((step) => step?.status === 'complete').length : 0;
  const activeStageIndexes = isSearching
    ? stages.flatMap((stage, index) => stage.indexes.some((stepIndex) => workflow?.[stepIndex]?.status === 'working') ? [index] : [])
    : [];
  const currentWorkflowIndex = activeAgents.length
    ? workflow.findIndex((step) => step?.status === 'working')
    : Math.min(searchStage, workflowLength - 1);
  const activeIndex = isSearching
    ? activeStageIndexes[0] ?? stages.findIndex((stage) => stage.indexes.includes(currentWorkflowIndex))
    : -1;
  const progressIndex = activeStageIndexes.length ? Math.max(...activeStageIndexes) : activeIndex;
  const completedStages = stages.filter((stage) => stage.indexes.every((index) => workflow?.[index]?.status === 'complete')).length;
  const finishedEmpty = resultStatus === 'complete' && !hasResults;
  const hasWaitingCheck = hasResults && workflow?.some((step) => step?.status === 'waiting');
  const stageProgress = isSearching
    ? Math.max(8, ((Math.max(progressIndex, 0) + 1) / stages.length) * 100)
    : hasResults || finishedEmpty ? (completedStages / stages.length) * 100 : 0;
  const activeStageLabel = activeIndex >= 0 ? stages[activeIndex]?.label : 'Research';
  const statusText = searchError
    ? searchError
    : isSearching
      ? activeAgents.length > 1
        ? `${activeAgents.slice(0, 2).map((step) => step.agent || 'Shopping agent').join(' + ')}${activeAgents.length > 2 ? ` + ${activeAgents.length - 2} more` : ''} working in parallel`
        : activeAgents[0]
          ? `${activeAgents[0].agent || 'Shopping agent'} · ${activeAgents[0].detail || 'Working now'}`
          : `${activeStageLabel} · Checking retailer pages for price, stock, delivery, and reviews…`
      : hasResults
        ? `Decision ready · ${resultCount} product ${resultCount === 1 ? 'option' : 'options'}${hasWaitingCheck ? ' · some checks still need retailer confirmation' : ''}`
        : finishedEmpty ? 'Research finished · no purchasable product pages found' : resultStatus === 'needs_clarification' ? 'One more detail needed before retailer research' : 'Ready when you are';
  return (
    <section
      className="agent-strip js-reveal"
      aria-label="Research status"
      style={{ '--research-progress': stageProgress / 100 }}
    >
      <div className="agent-strip__heading">
        <div className="agent-strip__title">
          <Icon name="shield" size={15} />
          <span>Research status</span>
        </div>
        <div className="agent-strip__heading-actions">
          <small className="agent-strip__status" role="status" aria-live="polite">
            {statusText}
          </small>
          <button type="button" className="talk-link" onClick={onOpenTalk}>
            <Icon name="waveform" size={14} /> Ask Artha
          </button>
        </div>
      </div>
      <div className="agent-strip__steps">
        {stages.map((stage, index) => {
          const working = isSearching && (activeStageIndexes.length ? activeStageIndexes.includes(index) : activeIndex === index);
          const complete = stage.indexes.every((stepIndex) => workflow?.[stepIndex]?.status === 'complete');
          const unverified = !isSearching && (hasResults || finishedEmpty) && !complete;
          return (
            <div
              className={`agent-step ${working ? 'is-working' : complete ? 'is-complete' : unverified ? 'is-unverified' : ''}`}
              style={{ '--stage-index': index }}
              key={stage.label}
            >
              <span className="agent-step__node">
                {working ? <span className="pulse-dot" /> : complete ? <Icon name="check" size={13} /> : unverified ? <Icon name="info" size={13} /> : index + 1}
              </span>
              <div className="agent-step__content">
                <strong>{stage.label}</strong>
                <small>{working ? 'Working now…' : unverified ? 'Needs retailer confirmation' : stage.copy}</small>
              </div>
            </div>
          );
        })}
      </div>
      {workflow?.length ? (
        <details className="agent-activity">
          <summary>
            <span>Agent activity</span>
            <small>{completedAgents} of {workflow.length} specialists complete{activeAgents.length ? ` · ${activeAgents.length} working` : ''}</small>
            <Icon name="chevron" size={16} />
          </summary>
          <ol className="agent-activity__list">
            {workflow.map((step, index) => {
              const agent = step?.agent || `Specialist ${index + 1}`;
              const status = step?.status || 'queued';
              const statusLabel = ({ complete: 'Complete', working: 'Working', retrying: 'Retrying', waiting: 'Waiting', blocked: 'Blocked', failed: 'Failed', idle: 'Not started', queued: 'Queued' })[status] || status;
              return (
                <li className={`agent-activity__row is-${status}`} style={{ '--stage-index': index }} key={`${agent}-${index}`}>
                  <span className="agent-activity__marker" aria-hidden="true">
                    {status === 'complete' ? <Icon name="check" size={13} /> : status === 'waiting' || status === 'failed' ? <Icon name="info" size={13} /> : null}
                  </span>
                  <div className="agent-activity__copy">
                    <strong>{agent}</strong>
                    <small>{step?.detail || statusLabel}</small>
                  </div>
                  <span className="agent-activity__status">{statusLabel}</span>
                </li>
              );
            })}
          </ol>
        </details>
      ) : null}
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

function BudgetOpportunity({ opportunity, product, onInspect }) {
  if (!opportunity || !product) return null;
  return (
    <aside className="opportunity-note" aria-label="Budget stretch opportunity">
      <div>
        <span className="section-kicker">Worth a small stretch</span>
        <strong>{sanitizeTitle(opportunity.name)} · {formatPrice(opportunity.extra)} over budget</strong>
        <p>{opportunity.reason}. {opportunity.delivery_label}</p>
      </div>
      <button type="button" className="quiet-action" onClick={() => onInspect(product)}>Inspect evidence</button>
    </aside>
  );
}

function BriefSummary({ intent, show = true }) {
  if (!show) return null;
  const mission = intent?.mission || {};
  const fields = [
    (mission.occasion || intent?.occasion) ? `Occasion: ${mission.occasion || intent.occasion}` : null,
    ...(intent?.must_have || []).slice(0, 2),
    (mission.budget || intent?.budget) ? `Budget ${formatPrice(mission.budget || intent.budget)}` : null,
    (mission.arrive_by_date || intent?.arrive_by) ? `Arrival: ${mission.arrive_by_date || intent.arrive_by}` : null,
    (mission.pincode || intent?.pincode) ? `Pincode ${mission.pincode || intent.pincode}` : null,
    (mission.color || intent?.color) ? `Colour: ${mission.color || intent.color}` : null,
    (mission.size || intent?.size) ? `Size: ${mission.size || intent.size}` : null,
    intent?.quantity > 1 ? `Quantity ${intent.quantity}` : null,
    intent?.brand ? `Preferred brand: ${intent.brand}` : null,
    intent?.location ? `Delivering to ${intent.location}` : null,
    intent?.location_context?.nearby_stores?.length ? `${intent.location_context.nearby_stores.length} nearby stores checked` : null,
  ].filter(Boolean);
  return <p className="brief-summary">{fields.join(' • ')}</p>;
}

function LocationContext({ intent }) {
  const stores = Array.isArray(intent?.location_context?.nearby_stores) ? intent.location_context.nearby_stores : [];
  if (!stores.length) return null;
  return (
    <section className="location-context" aria-label="Nearby store context">
      <div className="location-context__heading">
        <span className="section-kicker">Location context</span>
        <strong>{stores.length} nearby {stores.length === 1 ? 'store' : 'stores'} checked</strong>
        <small>Approximate permissioned location; precise coordinates were discarded.</small>
      </div>
      <ul className="location-context__list">
        {stores.slice(0, 3).map((store, index) => (
          <li key={`${store.name || 'store'}-${index}`}>
            <span>{store.name || 'Nearby store'}</span>
            <small>{store.address || 'Address not returned'}{store.rating ? ` · ★ ${store.rating}` : ''}</small>
          </li>
        ))}
      </ul>
    </section>
  );
}

function clarificationSuggestions(question) {
  const key = String(question?.key || '').toLowerCase();
  if (key === 'color') return ['Red', 'Black', 'Blue', 'Neutral'];
  if (key === 'size') return ['S', 'M', 'L', 'XL'];
  if (key === 'delivery') return ['Within 3 days', 'Within 5 days', 'Within 7 days'];
  if (key === 'budget') return ['Under ₹1,000', 'Under ₹2,000', 'Under ₹5,000'];
  if (key === 'location') return ['Bengaluru', 'Mumbai', 'Delhi'];
  if (key === 'pincode') return [];
  return [];
}

function ClarificationNote({ intent, onAnswer, onEdit }) {
  const questions = Array.isArray(intent?.clarifications) ? intent.clarifications : [];
  if (!questions.length) return null;
  return (
    <aside className="clarification-note" aria-label="Details Artha would like to confirm">
      <span className="section-kicker">A few details to sharpen this search</span>
      <strong>{questions.length === 1 ? questions[0].question : `I need ${questions.length} details before I search.`}</strong>
      <div className="clarification-note__questions">
        {questions.map((question) => (
          <div className="clarification-note__question" key={question.key || question.question}>
            <span>{question.question}</span>
            {onAnswer && clarificationSuggestions(question).length ? (
              <div className="clarification-note__chips" aria-label={`Quick answers for ${question.question}`}>
                {clarificationSuggestions(question).map((suggestion) => (
                  <button type="button" key={suggestion} onClick={() => onAnswer(suggestion)}>
                    {suggestion}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
      <small>Artha has paused retailer research until these constraints are clear. Reply in the brief above, or use a quick answer.</small>
      <button type="button" className="quiet-action clarification-note__edit" onClick={onEdit}>Edit shopping brief <Icon name="arrow" size={14} /></button>
    </aside>
  );
}

function HeroVisual() {
  const visualRef = useRef(null);

  useEffect(() => {
    const node = visualRef.current;
    if (!node || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;
    const supportsPointer = window.matchMedia('(pointer: fine)').matches;
    if (!supportsPointer) return undefined;
    let frame = null;
    const reset = () => {
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        node.style.setProperty('--hero-tilt-x', '0deg');
        node.style.setProperty('--hero-tilt-y', '0deg');
        node.style.setProperty('--hero-shift-x', '0px');
        node.style.setProperty('--hero-shift-y', '0px');
      });
    };
    const move = (event) => {
      const rect = node.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        node.style.setProperty('--hero-tilt-x', `${y * -4}deg`);
        node.style.setProperty('--hero-tilt-y', `${x * 5}deg`);
        node.style.setProperty('--hero-shift-x', `${x * 10}px`);
        node.style.setProperty('--hero-shift-y', `${y * 10}px`);
      });
    };
    node.addEventListener('pointermove', move, { passive: true });
    node.addEventListener('pointerleave', reset, { passive: true });
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerleave', reset);
    };
  }, []);

  return (
    <div ref={visualRef} className="hero-visual" aria-hidden="true">
      <div className="hero-visual__frame">
        <div className="hero-visual__image" />
        <div className="hero-visual__wash" />
        <span className="hero-visual__index">01 — 03</span>
        <span className="hero-visual__caption">The everyday edit</span>
        <span className="hero-visual__rule" />
      </div>
      <div className="hero-visual__ticket">
        <strong>3</strong>
        <span>pieces<br />worth keeping</span>
      </div>
      <div className="hero-visual__stamp">SOURCE<br />LINKED</div>
    </div>
  );
}

function PriceDesk({ product, compact = false }) {
  const offers = (Array.isArray(product.current_offers) ? product.current_offers : [])
    .filter((offer) => Number.isFinite(Number(offer.price)) && Number(offer.price) > 0)
    .sort((a, b) => Number(a.price) - Number(b.price));
  const history = product.price_history || {};
  const observations = (Array.isArray(history.observations) ? history.observations : [])
    .filter((item) => Number.isFinite(Number(item.price)) && Number(item.price) > 0)
    .slice(-5);
  const hasHistory = observations.length > 0 && history.status !== 'unknown';
  const isDemo = history.status === 'fixture';

  return (
    <section className={`price-desk ${compact ? 'price-desk--compact' : ''}`} aria-label={`Price comparison and history for ${sanitizeTitle(product.name)}`}>
      <div className="price-desk__heading">
        <div>
          <span className="section-kicker">The price desk</span>
          <h3>{compact ? 'Offers & observed history' : offers.length > 1 ? 'A better price, with the proof.' : offers.length ? 'One checked price, with context.' : 'Price evidence is still open.'}</h3>
          <p>{sanitizeTitle(product.name)}</p>
        </div>
        {offers.length ? (
          <div className="price-desk__low">
            <span>{offers.length === 1 ? 'Only directly checked offer' : `Lowest of ${offers.length} checked offers`}</span>
            <strong>{formatPrice(offers[0].price)}</strong>
          </div>
        ) : null}
      </div>
      <div className="price-desk__grid">
        <div className="price-desk__column">
          <div className="price-desk__label"><span>Matching retailer offers</span><span>{offers.length ? `${offers.length} checked` : 'Pending'}</span></div>
          {offers.length ? (
            <ol className="price-desk__offers">
              {offers.map((offer, index) => (
                <li key={`${offer.source_url || offer.seller}-${index}`} className={index === 0 ? 'is-lowest' : ''}>
                  <div>
                    <strong>{offer.seller || 'Retailer'}</strong>
                    <small>{offer.source_status === 'direct_page_price_changed' ? 'Search price changed · ' : index === 0 && offers.length > 1 ? 'Lowest observed · ' : ''}{observedTime(offer.observed_at)}</small>
                  </div>
                  <div className="price-desk__offer-end">
                    <b>{formatPrice(offer.price)}</b>
                    {retailerUrl(offer.source_url) ? <a href={retailerUrl(offer.source_url)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${offer.seller || 'retailer'} offer in a new tab`}><Icon name="external" size={15} /></a> : null}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="price-desk__empty">No directly verified matching store offers yet. Confirm the current price at the retailer.</p>
          )}
          <small className="price-desk__caveat">{product.same_product_match === 'gtin' ? 'Matched by product GTIN and variant.' : product.same_product_match === 'brand_and_exact_title' ? 'Matched by brand, exact title, colour, and size.' : 'Only this retailer page could be safely matched.'} Shipping, taxes, and available sizes may change the checkout total.</small>
        </div>
        <div className="price-desk__column">
          <div className="price-desk__label"><span>Recorded price history</span><span>{isDemo ? 'Demo' : hasHistory ? `${history.observation_count || observations.length} recorded prices` : 'Unknown'}</span></div>
          {hasHistory ? (
            <>
              <p className="price-desk__trend">{isDemo ? 'Sample data for demonstration' : history.status === 'first_observation' ? 'First price recorded; a trend needs more checks.' : history.trend_label || 'Observed prices across recorded checks.'}</p>
              <ol className="price-desk__timeline">
                {observations.map((item, index) => (
                  <li key={`${item.observed_at || 'unknown'}-${item.source_url || item.seller}-${index}`}>
                    <span className="price-desk__timeline-dot" aria-hidden="true" />
                    <span>{item.seller || 'Retailer'}<small>{observedTime(item.observed_at)}</small></span>
                    <b>{formatPrice(item.price)}</b>
                  </li>
                ))}
              </ol>
              {history.observed_low ? <small className="price-desk__caveat">Lowest recorded: {formatPrice(history.observed_low)}. History covers Artha's observations only.</small> : null}
            </>
          ) : (
            <p className="price-desk__empty">No recorded price history yet. Artha will show a trend after later verified checks of this product.</p>
          )}
        </div>
      </div>
    </section>
  );
}

function ProductCard({ product, selected, focused, onToggle, onFocus, onOpenProduct, onInspect, onSave, saved, motionIndex = 0 }) {
  const live = product.source_kind === 'live_web';
  const cleanTitle = sanitizeTitle(product.name);
  const cleanDesc = sanitizeSnippet(product.description);
  const sizes = Array.isArray(product.sizes) ? product.sizes : [];
  const colors = Array.isArray(product.colors) ? product.colors : [];

  return (
    <article
      className={`product-card ${selected ? 'is-selected' : ''} ${focused ? 'is-focused' : ''}`}
      style={{ '--motion-index': motionIndex }}
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
          {live && !product.lowest_current_offer ? <small className="product-card__price-signal is-unverified">Price not directly verified · confirm at retailer</small> : null}
          {product.quantity > 1 ? <small className="product-card__quantity-note">{product.quantity} units · {formatPrice(product.unit_total || product.total_price)} each</small> : null}
          <div className="product-card__delivery">
            <Icon name="truck" size={14} />
            <span>{product.delivery_label || 'Confirm at store'}</span>
          </div>
          {sizes.length || colors.length ? (
            <small className="product-card__variant">
              {sizes.length ? `Sizes: ${sizes.slice(0, 4).join(', ')}` : ''}
              {sizes.length && colors.length ? ' · ' : ''}
              {colors.length ? `Colours: ${colors.slice(0, 3).join(', ')}` : ''}
            </small>
          ) : null}
          {product.lowest_current_offer ? <small className="product-card__price-signal">{product.current_offers?.length > 1 ? 'Lowest checked matching offer' : 'Directly checked price'} {formatPrice(product.lowest_current_offer.price)} · {product.current_offers?.length || 1} {product.current_offers?.length === 1 ? 'store' : 'stores'}</small> : null}
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

function RecommendationBanner({ product, onInspect, onOpenTalk }) {
  if (!product) return null;
  const reasons = (product.reason_tags || []).filter(Boolean).slice(0, 3);
  return (
    <aside className="decision-banner" aria-label="Top recommendation">
      <div className="decision-banner__copy">
        <span className="decision-banner__eyebrow"><Icon name="spark" size={13} /> Best fit for your brief</span>
        <strong>{sanitizeTitle(product.name)}</strong>
        <p>{sanitizeSnippet(product.description)} Artha ranked it first because the trade-offs line up best with your constraints.</p>
        <div className="decision-banner__reasons">
          {reasons.map((reason) => <span key={reason}>{reason}</span>)}
        </div>
      </div>
      <div className="decision-banner__actions">
        <strong>{formatPrice(productTotal(product))}</strong>
        <button type="button" className="primary-button" onClick={() => onInspect(product)}>
          <Icon name="shield" size={14} /> Why this pick
        </button>
        <button type="button" className="text-button" onClick={onOpenTalk}>
          Ask about the trade-off <Icon name="arrow" size={13} />
        </button>
      </div>
    </aside>
  );
}

function MissionDecision({ decision, products, onInspect, onOpenProduct, onOpenTalk }) {
  if (!decision) return <RecommendationBanner product={products[0]} onInspect={onInspect} onOpenTalk={onOpenTalk} />;
  const product = products.find((item) => item.id === decision.recommended_product_id);
  const fallback = products.find((item) => item.id === decision.fallback_product_id);
  const isNoFit = decision.status === 'no_safe_fit';
  const isBuyNow = decision.status === 'buy_now';
  const title = isNoFit ? 'No safe fit' : isBuyNow ? 'Buy now' : 'Verify before buying';
  const action = isBuyNow ? 'Open recommended retailer' : 'Open retailer & verify';
  const reasons = [...(decision.reasons || []), ...(decision.blocking_risks || [])].filter(Boolean);
  const lowerOffer = product?.lowest_current_offer;
  const cheaperElsewhere = lowerOffer && lowerOffer.price < Number(product.price)
    && retailerUrl(lowerOffer.source_url) !== retailerUrl(product.url);

  return (
    <aside className={`decision-banner mission-decision mission-decision--${decision.status}`} aria-label="Artha decision">
      <div className="decision-banner__copy">
        <span className="decision-banner__eyebrow"><Icon name={isNoFit ? 'info' : isBuyNow ? 'checkCircle' : 'shield'} size={13} /> Artha decision</span>
        <strong>{title}{product ? ` · ${sanitizeTitle(product.name)}` : ''}</strong>
        <p>{isNoFit ? decision.mission_change || 'Try changing one hard constraint and search again.' : isBuyNow ? 'Every hard constraint is supported by the checked retailer evidence.' : 'One or more purchase facts still need confirmation on the retailer page.'}</p>
        {decision.checked_at ? <small className="mission-decision__time">Decision updated {observedTime(decision.checked_at)}</small> : null}
        <div className="decision-banner__reasons">
          {reasons.map((reason) => <span key={reason}>{reason}</span>)}
        </div>
        {cheaperElsewhere ? (
          <p className="mission-decision__fallback">
            Lower checked item price: {formatPrice(lowerOffer.price)} at {lowerOffer.seller}. Confirm its size, stock, delivery, and checkout total before switching.{' '}
            <a href={retailerUrl(lowerOffer.source_url)} target="_blank" rel="noopener noreferrer">Check lower offer <Icon name="external" size={12} /></a>
          </p>
        ) : null}
        {fallback ? (
          <p className="mission-decision__fallback">
            Fallback: <button type="button" onClick={() => onOpenProduct(fallback)}>{sanitizeTitle(fallback.name)} <Icon name="external" size={12} /></button>
          </p>
        ) : null}
      </div>
      <div className="decision-banner__actions">
        {product ? <strong>{formatPrice(productTotal(product))}</strong> : null}
        {product ? (
          <button type="button" className="primary-button" onClick={() => onOpenProduct(product)} disabled={!product.url}>
            <Icon name="external" size={14} /> {action}
          </button>
        ) : null}
        {product ? <button type="button" className="text-button" onClick={() => onInspect(product)}>What Artha checked <Icon name="shield" size={13} /></button> : null}
        <button type="button" className="text-button" onClick={onOpenTalk}>{isNoFit ? 'Adjust this mission' : 'Talk through the decision'} <Icon name="arrow" size={13} /></button>
      </div>
    </aside>
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
        <small className="price-sub">{product.quantity > 1 ? `${product.quantity} units · ` : ''}{product.lowest_current_offer ? 'Directly checked' : live ? 'Source-listed · verify' : 'Estimated'}</small>
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
  paymentProvider,
  voice,
  isSpeaking,
  onSpeak,
  user,
  isSessionLoading,
  onSavePlan,
  isSavingPlan,
  onStartCheckout,
  onRemoveItem,
  showCheckout,
}) {
  const total = selectedProducts.reduce((sum, product) => sum + productTotal(product), 0);
  const live = sourceMode === 'live';
  const awaitingSearch = sourceMode === 'idle';

  return (
    <aside className="summary-panel" aria-label="Purchase plan summary">
      <div className="summary-panel__header">
        <div className="summary-panel__title-wrap">
          <h2>Your shortlist</h2>
          <span className="item-count-badge">
            {selectedProducts.length} {selectedProducts.length === 1 ? 'item' : 'items'}
          </span>
        </div>
          <small className="summary-panel__sub">Keep the options worth a closer look.</small>
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
            <strong>{intent?.arrive_by || 'Delivery timing to confirm'}</strong>
            <small>{intent?.location ? `Delivering to ${intent.location}` : 'Add a delivery city for better results'}</small>
          </div>
        </div>
        <small className="summary-calc__note">Known item prices and any confirmed shipping. Confirm the final total at the retailer.</small>
      </div>

      <VoiceControl voice={voice} isSpeaking={isSpeaking} onSpeak={onSpeak} disabled={!selectedProducts.length} />

      <button
        type="button"
        className="primary-button summary-button"
        onClick={onSavePlan}
        disabled={!selectedProducts.length || isSavingPlan || isSessionLoading}
      >
        <span>{isSavingPlan ? 'Saving plan…' : isSessionLoading ? 'Checking account…' : user ? 'Save purchase plan' : 'Sign in to save plan'}</span>
        <Icon name="arrow" size={17} />
      </button>

      {showCheckout && selectedProducts.length && paymentProvider === 'sandbox' ? (
        <button type="button" className="secondary-button summary-checkout-button" onClick={onStartCheckout}>
          <span>Review sandbox order</span>
          <Icon name="arrow" size={15} />
        </button>
      ) : null}

      <div className="checkout-trust">
        <p className="checkout-note">
          <Icon name="shield" size={14} />
          <span>Checkout occurs on linked retailer sites. Artha never requests payment info.</span>
        </p>
      </div>

      <div className="summary-legend">
        <LegendRow
          icon="shield"
          title={awaitingSearch ? 'Awaiting live search' : live ? 'Retailer sources found' : 'Live source unavailable'}
          detail={awaitingSearch ? 'Run a brief to query active web retailers.' : live ? 'Open retailer links to confirm current price, stock, and delivery.' : 'Run the search again after the provider recovers.'}
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
  paymentProvider,
  query,
  setQuery,
  mission,
  onMissionChange,
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
  searchError,
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
  isSessionLoading,
  onSavePlan,
  isSavingPlan,
  onStartCheckout,
  onToast,
  onPickPrompt,
  onOpenTalk,
  onQuickAnswer,
  onSelectAll,
  onClearSelection,
  onRemoveSelectedItem,
}) {
  const [viewMode, setViewMode] = useState('cards'); // 'cards' | 'table'
  const resultsRef = useRef(null);
  const discoverRef = useRef(null);
  const lastScrolledSearchRef = useRef(null);
  const selectedProducts = result.products.filter((product) => selectedIds.includes(product.id));
  const priceProduct = result.products.find((product) => product.id === result.intent?.decision?.recommended_product_id) || result.products[0];
  const zeroResult = result.status === 'complete' && !result.products.length;
  const allSelected = result.products.length > 0 && selectedIds.length === result.products.length;

  useEffect(() => {
    const root = discoverRef.current;
    if (!root) return undefined;
    const items = root.querySelectorAll('.js-reveal');
    if (!('IntersectionObserver' in window)) {
      items.forEach((item) => item.classList.add('is-visible'));
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      }),
      { rootMargin: '0px 0px -10% 0px', threshold: 0.08 },
    );
    items.forEach((item) => observer.observe(item));
    return () => observer.disconnect();
  }, [result.products.length]);

  useEffect(() => {
    if (isSearching || !result.search_id || (!result.products.length && result.status !== 'needs_clarification') || lastScrolledSearchRef.current === result.search_id) return undefined;
    lastScrolledSearchRef.current = result.search_id;
    const frame = window.requestAnimationFrame(() => {
      const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      resultsRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isSearching, result.products.length, result.search_id, result.status]);

  return (
    <div ref={discoverRef} className="discover-layout">
      <section className="main-column">
        <div className="hero-copy">
          <div className="hero-copy__intro">
            <h1 aria-label="Good buys. Better reasons.">
              <span className="hero-word hero-word--1">Good</span>{' '}
              <span className="hero-word hero-word--2">buys.</span>
              <br />
              <em>
                <span className="hero-word hero-word--3">Better</span>
                <br />
                <span className="hero-word hero-word--4">reasons.</span>
              </em>
            </h1>
            <p>
              Describe your style. Artha finds the strongest retailer options and makes comparison feel simple.
            </p>
            <div className="hero-copy__note">
              <span className="hero-copy__note-dot" />
              <span>Research that leaves the final call with you.</span>
            </div>
          </div>
          <HeroVisual />
        </div>

        <Composer
          query={query}
          setQuery={setQuery}
          mission={mission}
          onMissionChange={onMissionChange}
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
          searchError={searchError}
          onToast={onToast}
          onPickPrompt={onPickPrompt}
          onOpenTalk={onOpenTalk}
        />

        <AgentStrip
          workflow={result.workflow}
          isSearching={isSearching}
          searchStage={searchStage}
          hasResults={result.products.length > 0}
          resultCount={result.products.length}
          resultStatus={result.status}
          searchError={searchError}
          onOpenTalk={onOpenTalk}
        />
        <LocationContext intent={result.intent} />
        <ConversationTrail conversation={result.conversation} />
        <BudgetOpportunity
          opportunity={result.summary?.opportunity}
          product={result.products.find((item) => item.id === result.summary?.opportunity?.product_id)}
          onInspect={onInspect}
        />

        <section ref={resultsRef} className="results-section js-reveal" aria-labelledby="results-heading">
          <ClarificationNote intent={result.status === 'needs_clarification' ? result.intent : null} onAnswer={onQuickAnswer} onEdit={() => document.getElementById('shopping-brief')?.focus()} />
          <div className="results-toolbar">
            <div className="results-heading">
              <h2 id="results-heading">{result.products.length ? 'Your mission decision' : result.status === 'needs_clarification' ? 'Complete the brief to search' : zeroResult ? 'No product match yet' : 'Build your live shortlist'}</h2>
              <BriefSummary intent={result.intent} show={Boolean(query.trim() || result.products.length)} />
            </div>
          </div>

          <MissionDecision
            decision={result.intent?.decision}
            products={result.products}
            onInspect={onInspect}
            onOpenProduct={onOpenProduct}
            onOpenTalk={onOpenTalk}
          />

          {priceProduct ? <PriceDesk product={priceProduct} /> : null}

          {!result.products.length ? (
            <div className="empty-state results-empty-state">
              <span className="empty-state__icon">
                <Icon name="search" size={24} />
              </span>
              <h2>{result.status === 'needs_clarification' ? 'Answer the questions above to start.' : zeroResult ? 'No purchasable product page found.' : 'Live sources will appear here.'}</h2>
              <p>{result.status === 'needs_clarification' ? 'Once the constraints are clear, Artha will search and verify the relevant retailer sources.' : zeroResult ? 'Artha excluded articles and category pages. Try a more specific product name, another retailer, or a wider budget and search again.' : 'Describe what you want, add a reference image, or paste a public product or post URL to start a verified search.'}</p>
              {zeroResult ? <button type="button" className="secondary-button" onClick={() => document.getElementById('shopping-brief')?.focus()}>Edit brief and retry <Icon name="arrow" size={15} /></button> : null}
            </div>
          ) : (
            <section className="source-explorer" aria-label="Retailer product shortlist">
              <div className="source-explorer__heading">
                <div><span className="section-kicker">The shortlist</span><h3>{result.products.length} product {result.products.length === 1 ? 'option' : 'options'} to compare</h3></div>
                <span>Source links and trade-offs on every card</span>
              </div>
              <div className="source-explorer__content">
                <div className="results-controls">
                  <button type="button" className="select-all-btn" onClick={allSelected ? onClearSelection : onSelectAll}>
                    {allSelected ? 'Deselect all' : 'Select all'}
                  </button>
                  <div className="view-mode-toggle" role="group" aria-label="View layout">
                    <button type="button" className={viewMode === 'cards' ? 'is-active' : ''} onClick={() => setViewMode('cards')} aria-label="Grid card view" title="Card view"><Icon name="grid" size={16} /></button>
                    <button type="button" className={viewMode === 'table' ? 'is-active' : ''} onClick={() => setViewMode('table')} aria-label="Detailed comparison table" title="Table view"><Icon name="list" size={16} /></button>
                  </div>
                </div>
                {viewMode === 'cards' ? (
                  <div className="products-grid">
                    {result.products.map((product, index) => (
                      <ProductCard
                        key={product.id}
                        product={product}
                        motionIndex={index}
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
                  <ResultsTable products={result.products} selectedIds={selectedIds} focusedId={focusedId} onToggle={onToggle} onFocus={onFocus} onOpenProduct={onOpenProduct} onInspect={onInspect} onSave={onSave} savedIds={savedIds} />
                )}
              </div>
            </section>
          )}
        </section>
      </section>

      <SummaryPanel
        selectedProducts={selectedProducts}
        intent={result.intent}
        sourceMode={result.source?.mode}
        paymentProvider={paymentProvider}
        voice={voice}
        isSpeaking={isSpeaking}
        onSpeak={onSpeak}
        user={user}
        isSessionLoading={isSessionLoading}
        onSavePlan={onSavePlan}
        isSavingPlan={isSavingPlan}
        onStartCheckout={onStartCheckout}
        onRemoveItem={onRemoveSelectedItem}
        showCheckout={!result.intent?.mission}
      />

      {/* Floating mobile action bar */}
      {selectedProducts.length > 0 ? (
        <div className="mobile-plan-bar">
          <div className="mobile-plan-bar__info">
            <span className="mobile-plan-bar__count">{selectedProducts.length} items in plan</span>
            <strong className="mobile-plan-bar__total">
              {formatPrice(selectedProducts.reduce((sum, p) => sum + productTotal(p), 0))}
            </strong>
          </div>
          <div className="mobile-plan-bar__actions">
            <button
              type="button"
              className="primary-button mobile-plan-bar__cta"
              onClick={onSavePlan}
              disabled={isSavingPlan || isSessionLoading}
            >
              {isSavingPlan ? 'Saving…' : isSessionLoading ? 'Checking account…' : user ? 'Save Plan' : 'Sign in to Save'}
            </button>
            {!result.intent?.mission && paymentProvider === 'sandbox' ? (
              <button type="button" className="secondary-button mobile-plan-bar__checkout" onClick={onStartCheckout}>
                Sandbox order
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AuthSheet({ onClose, onSignIn }) {
  const closeButtonRef = useRef(null);
  const dialogRef = useRef(null);
  useDialogFocusTrap(true, dialogRef, closeButtonRef, onClose);

  return (
    <div
      className="modal-layer"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section ref={dialogRef} className="auth-sheet" role="dialog" aria-modal="true" aria-labelledby="auth-title" aria-describedby="auth-copy">
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

function CheckoutSheet({ products, intent, isSubmitting, onClose, onConfirm }) {
  const [confirmed, setConfirmed] = useState(false);
  const closeButtonRef = useRef(null);
  const dialogRef = useRef(null);
  const total = products.reduce((sum, product) => sum + productTotal(product), 0);
  useDialogFocusTrap(true, dialogRef, closeButtonRef, onClose);

  return (
    <div className="modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="auth-sheet checkout-sheet" role="dialog" aria-modal="true" aria-labelledby="checkout-title">
        <button ref={closeButtonRef} type="button" className="icon-button auth-sheet__close" onClick={onClose} aria-label="Close checkout">
          <Icon name="close" size={19} />
        </button>
        <span className="section-kicker">Local sandbox checkout</span>
        <h2 id="checkout-title">Ready to place this order?</h2>
        <p>
          Artha will record a sandbox order for {products.length} selected {products.length === 1 ? 'item' : 'items'} and start its local tracking timeline. No payment is collected.
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
          {isSubmitting ? 'Creating order…' : 'Confirm sandbox order'}
          <Icon name="arrow" size={16} />
        </button>
        <small className="checkout-sheet__notice">Development order only. Complete a real purchase on the retailer site.</small>
      </section>
    </div>
  );
}

function ProductEvidenceSheet({ product, onClose, onOpenProduct }) {
  const closeButtonRef = useRef(null);
  const dialogRef = useRef(null);
  useDialogFocusTrap(Boolean(product), dialogRef, closeButtonRef, onClose);
  if (!product) return null;
  const reviewAnalysis = product.review_analysis || {};
  const priceHistory = product.price_history || {};
  const reviewSources = Array.isArray(product.review_sources) ? product.review_sources : [];
  const researchSources = Array.isArray(product.research_sources) ? product.research_sources : [];
  const evidence = Array.isArray(product.evidence) ? product.evidence : [];
  const sampleReviews = product.source_kind === 'sandbox_catalog';
  const reviewLabel = sampleReviews ? 'Demo data' : reviewSources.length ? `${reviewSources.length} sources listed` : 'Not verified';
  const sellerLabel = product.seller ? 'Name listed; verify at retailer' : 'Not independently verified';
  const historyLabel = priceHistory.status === 'fixture' ? 'Demo history' : priceHistory.observed_low ? `From ${formatPrice(priceHistory.observed_low)}` : 'Not recorded yet';
  const directlyChecked = product.research_status === 'complete' && ['matched', 'direct'].includes(product.price_verification);
  return (
    <div className="modal-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="auth-sheet evidence-sheet" role="dialog" aria-modal="true" aria-labelledby="evidence-title">
        <button ref={closeButtonRef} type="button" className="icon-button auth-sheet__close" onClick={onClose} aria-label="Close evidence">
          <Icon name="close" size={19} />
        </button>
        <span className="section-kicker">{directlyChecked ? 'What Artha checked' : 'What still needs checking'}</span>
        <h2 id="evidence-title">{directlyChecked ? 'Evidence behind this decision.' : 'Research with open questions.'}</h2>
        <p className="evidence-sheet__product">{sanitizeTitle(product.name)} · {product.seller || 'Retailer'}</p>

        <div className="evidence-sheet__facts">
          <div><span>Source-listed total</span><strong>{formatPrice(productTotal(product))}</strong></div>
          <div><span>Delivery</span><strong>{product.delivery_label || 'Confirm at retailer'}</strong></div>
          <div><span>Review evidence</span><strong>{reviewLabel}</strong></div>
          <div><span>Seller evidence</span><strong>{sellerLabel}</strong></div>
          <div><span>Price history</span><strong>{historyLabel}</strong></div>
        </div>

        <div className="evidence-sheet__section">
          <div className="evidence-sheet__section-head">
            <span className="section-kicker">Review evidence</span>
          </div>
          <p>{sampleReviews ? 'Sample review notes for demonstration only.' : product.review_summary || 'Review data needs retailer confirmation.'}</p>
          <small>{sampleReviews ? 'Demo content; it does not represent live reviews.' : reviewAnalysis.detail || 'Source counts and ratings do not establish review authenticity.'}</small>
          {reviewSources.length ? (
            <ul className="evidence-sheet__list">
              {reviewSources.map((source, index) => (
                <li key={`${source.name || 'source'}-${index}`}>
                  <span>{source.name || 'Review source'}</span>
                  <small>{source.count ? `${source.count} reviews` : 'Sample size unknown'}{source.rating ? ` · ★ ${source.rating}` : ''}{source.signal ? ` · reported note: ${source.signal}` : ''}</small>
                </li>
              ))}
            </ul>
          ) : (
            <small>Independent review sources were not returned. Treat the rating as unverified.</small>
          )}
        </div>

        <PriceDesk product={product} compact />

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

function AccountLoading() {
  return (
    <div className="empty-state sign-in-prompt" role="status" aria-live="polite">
      <span className="empty-state__icon">
        <Icon name="shield" size={26} />
      </span>
      <h2>Checking your account…</h2>
      <p>Loading your private Artha workspace.</p>
    </div>
  );
}

function PlansView({ user, isSessionLoading, plans, onDiscover, onSignIn }) {
  if (isSessionLoading) {
    return (
      <div className="page-stack">
        <AccountLoading />
      </div>
    );
  }

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

function OrdersView({ user, isSessionLoading, orders, onDiscover, onCancel, onAdvance, onRequestReturn, onRefund, onSignIn }) {
  if (isSessionLoading) {
    return (
      <div className="page-stack">
        <AccountLoading />
      </div>
    );
  }

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
                  {order.payment_provider === 'sandbox' && order.status !== 'cancelled' && !['delivered', 'return_requested', 'refunded'].includes(order.status) ? (
                    <button type="button" className="quiet-action" onClick={() => onCancel(order.id)}>Cancel order</button>
                  ) : null}
                  {order.payment_provider === 'sandbox' && order.status === 'delivered' ? (
                    <button type="button" className="quiet-action" onClick={() => onRequestReturn(order.id)}>Request return</button>
                  ) : null}
                  {order.payment_provider === 'sandbox' && order.status === 'return_requested' ? (
                    <button type="button" className="quiet-action" onClick={() => onRefund(order.id)}>Record sandbox refund</button>
                  ) : null}
                  {order.payment_provider !== 'sandbox' ? <small className="order-actions__note">Live status waits for the merchant adapter</small> : null}
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
  const [query, setQuery] = useState(() => pendingSearch?.query || '');
  const [mission, setMission] = useState(() => pendingSearch?.result ? missionFromIntent(pendingSearch.result.intent) : missionFromIntent({}));
  const [postUrl, setPostUrl] = useState(() => pendingSearch?.postUrl || '');
  const [location, setLocation] = useState(() => pendingSearch?.location || null);
  const [showPostUrl, setShowPostUrl] = useState(false);
  const [reference, setReference] = useState(null);
  const [result, setResult] = useState(() => pendingSearch?.result || DEFAULT_RESULT);
  const [selectedIds, setSelectedIds] = useState(() => pendingSearch?.selectedIds || pendingSearch?.result?.selected_product_ids || DEFAULT_RESULT.selected_product_ids);
  const [focusedId, setFocusedId] = useState(() => pendingSearch?.result?.products?.[0]?.id || DEFAULT_RESULT.products[0]?.id || '');
  const [isSearching, setIsSearching] = useState(false);
  const [searchStage, setSearchStage] = useState(0);
  const [searchError, setSearchError] = useState('');
  const [savedIds, setSavedIds] = useState(readSavedIds);
  const [plans, setPlans] = useState([]);
  const [orders, setOrders] = useState([]);
  const [health, setHealth] = useState({ anakin_configured: false, ai: { provider: 'ollama' }, payment_provider: 'disabled', payment_configured: false });
  const [voice, setVoice] = useState({ provider: 'browser', label: 'Local browser voice' });
  const [usage, setUsage] = useState(null);
  const [usageWindow, setUsageWindow] = useState(30);
  const [usageRuntime, setUsageRuntime] = useState('all');
  const [isUsageLoading, setIsUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState('');
  const [user, setUser] = useState(null);
  const [isSessionLoading, setIsSessionLoading] = useState(true);
  const [authOpen, setAuthOpen] = useState(false);
  const [authAction, setAuthAction] = useState(null);
  const [postAuthAction, setPostAuthAction] = useState(null);
  const [isSavingPlan, setIsSavingPlan] = useState(false);
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [evidenceProduct, setEvidenceProduct] = useState(null);
  const [isCreatingOrder, setIsCreatingOrder] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [talkOpen, setTalkOpen] = useState(false);
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
    }).finally(() => {
      if (active) setIsSessionLoading(false);
    });
    const params = new URLSearchParams(window.location.search);
    if (params.get('auth') === 'success') {
      const restoringPlan = pendingSearch?.pending_action === 'save_plan';
      if (restoringPlan) setPostAuthAction('save_plan');
      setToast(
        restoringPlan
          ? 'Signed in. Restoring your purchase plan…'
          : 'You are signed in. Your purchase plans are private to this account.',
      );
      if (!restoringPlan) clearPendingSearch();
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
  }, [pendingSearch]);

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
    setQuery('');
    setMission(missionFromIntent({}));
    setPostUrl('');
    setLocation(null);
    setShowPostUrl(false);
    setReference(null);
    setResult(DEFAULT_RESULT);
    setSearchError('');
    setSelectedIds([]);
    setFocusedId('');
  }, []);

  const handleSearchWithPayload = useCallback(
    async (text, url, ref, options = {}) => {
      if (isSearching) {
        if (options.throwOnError) throw new Error('The current research is still running. Ask again when it finishes.');
        return null;
      }
      if (!text?.trim() && !url?.trim() && !ref?.dataUrl) return null;
      setIsSearching(true);
      setSearchStage(0);
      setSearchError('');
      const shouldRefine = Boolean(
        !options.forceNew
        &&
        result.search_id
        && text?.trim()
        && !url?.trim()
        && !ref?.dataUrl
        && (result.products.length || result.status === 'needs_clarification' || result.intent?.clarifications?.length),
      );
      try {
        const body = shouldRefine
          ? await refineAgentSearch({
              search_id: result.search_id,
              text: text.trim(),
              mission,
            })
          : await runAgentSearchAsync({
              text: text?.trim() || 'Find products that match this reference.',
              post_url: url?.trim() || null,
              image_name: ref?.name || null,
              reference_image: referencePayload(ref),
              location_coordinates: location,
              mission,
            }, (job) => {
              if (Array.isArray(job?.workflow) && job.workflow.length) {
                setResult((current) => ({ ...current, workflow: job.workflow }));
                const workingIndex = job.workflow.findIndex((stage) => stage.status === 'working');
                const nextIndex = workingIndex >= 0
                  ? workingIndex
                  : job.workflow.findIndex((stage) => stage.status !== 'complete');
                if (nextIndex >= 0) setSearchStage(nextIndex);
              }
            });
        if (!Array.isArray(body.products) || (!body.products.length && !['complete', 'needs_clarification'].includes(body.status))) throw new Error('The search did not return a usable result. Please try again.');
        setResult(body);
        setMission(missionFromIntent(body.intent));
        const nextProducts = Array.isArray(body.products) ? body.products : [];
        setSelectedIds(
          Array.isArray(body.selected_product_ids)
            ? body.selected_product_ids
            : nextProducts.slice(0, 3).map((product) => product.id),
        );
        setFocusedId(nextProducts[0]?.id || '');
        setToast(
          body.status === 'needs_clarification'
            ? 'I need a few more details before searching.'
            : !body.products.length
              ? 'No purchasable product pages found. Adjust the brief and try again.'
              : shouldRefine
                ? 'Shortlist refined from the existing research.'
                : body.source?.research?.completed === 0
                  ? 'Retailer options found, but no direct product page was confirmed.'
                  : 'Retailer options checked and ranked.',
        );
        return body;
      } catch (error) {
        const message = error.message || 'The search could not complete. Please try again.';
        setSearchError(message);
        setToast(message);
        if (options.throwOnError) throw error;
        return null;
      } finally {
        setIsSearching(false);
      }
    },
    [isSearching, location, mission, result],
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
      handleSearchWithPayload(prompt, postUrl, reference, { forceNew: true });
    },
    [handleSearchWithPayload, postUrl, reference],
  );

  const handleTalkAsk = useCallback(
    async (text) => {
      const spoken = String(text || '').trim();
      const question = /^(why|what|which|where|how|is|are|can|could|do|does|tell me)\b/i.test(spoken);
      const products = result.products || [];
      const decision = result.intent?.decision;
      const currentPick = products.find((product) => product.id === decision?.recommended_product_id) || products[0];
      if (/\b(where|track|status)\b.*\b(delivery|order|package)\b/i.test(spoken)) {
        if (!user) return 'Sign in, then open Orders and tracking to check a saved order. A shortlist is not a placed retailer order.';
        let latest;
        try {
          const body = await getOrders();
          setOrders(body.orders || []);
          latest = body.orders?.[0];
        } catch {
          return 'I could not load your saved orders right now. Open Orders and tracking to try again.';
        }
        return latest
          ? latest.payment_provider === 'sandbox'
            ? `Your latest sandbox order is ${String(latest.status || 'unknown').replace(/_/g, ' ')}. Open Orders and tracking for its local timeline.`
            : `Your historical payment record is ${String(latest.payment_status || 'unknown').replace(/_/g, ' ')}. Artha cannot confirm retailer dispatch or delivery; contact the payment merchant for fulfillment status.`
          : 'No saved order is on this account yet. A shortlist is research, not a placed retailer order.';
      }
      if (products.length && question && /\b(why|rank|ranked|ranking)\b/i.test(spoken)) {
        const reasons = [...(decision?.reasons || []), ...(currentPick?.reason_tags || [])].filter(Boolean).slice(0, 3);
        return `${sanitizeTitle(currentPick.name)} leads the checked shortlist. ${reasons.join('. ') || 'Open its evidence card for the details.'}${decision?.blocking_risks?.length ? ` Verify ${decision.blocking_risks.join(', ')} before buying.` : ''}`;
      }
      if (products.length && question && /\b(price|cheapest|lowest|cost|deal|history)\b/i.test(spoken)) {
        const compared = /\b(cheapest|lowest)\b/i.test(spoken)
          ? [...products].filter((product) => product.lowest_current_offer).sort((a, b) => a.lowest_current_offer.price - b.lowest_current_offer.price)[0]
          : currentPick;
        const offer = compared?.lowest_current_offer;
        const history = compared?.price_history || {};
        const current = offer
          ? `${compared.current_offers?.length > 1 ? 'The lowest directly checked matching offer' : 'The only directly checked offer'} for ${sanitizeTitle(compared.name)} is ${formatPrice(offer.price)} at ${offer.seller}.`
          : 'No directly checked matching store offer is available yet.';
        const past = history.status === 'observed' || history.status === 'first_observation'
          ? ` Recorded prices range from ${formatPrice(history.observed_low)} to ${formatPrice(history.observed_high)} across ${history.observation_count} recorded prices.`
          : ' Recorded live price history is not available yet.';
        return `${current}${past} Confirm the final total at the retailer.`;
      }
      if (products.length && question && /\b(fast|sooner|arrive|delivery time)\b/i.test(spoken)) {
        const timed = products.filter((product) => Number.isFinite(Number(product.delivery_days)) && product.delivery_days !== null && product.delivery_days !== undefined);
        if (!timed.length) return 'None of the checked retailers supplied a confirmed arrival time yet. Check delivery on the retailer page.';
        const fastest = [...timed].sort((a, b) => Number(a.delivery_days) - Number(b.delivery_days))[0];
        setFocusedId(fastest.id);
        return `${sanitizeTitle(fastest.name)} has the quickest stated delivery among checked results: ${fastest.delivery_label || `${fastest.delivery_days} days`}. Verify the promise for your pincode at the retailer.`;
      }
      const explicitNew = /^(?:start |do )?(?:a )?new search\b/i.test(spoken);
      const forceNew = explicitNew || /^(?:find|search for|shop for|look for|i (?:want|need|am looking for))\b/i.test(spoken);
      const brief = explicitNew ? spoken.replace(/^(?:start |do )?(?:a )?new search\b[: ,]*/i, '').trim() : spoken;
      if (!brief) return 'Tell me what product you want to search for.';
      setQuery(brief);
      const body = await handleSearchWithPayload(brief, forceNew ? '' : postUrl, forceNew ? null : reference, { throwOnError: true, forceNew });
      if (body?.status === 'needs_clarification') {
        const questions = body.intent?.clarifications || body.clarifications || [];
        return questions.length
          ? `I need a little more detail first: ${questions.map((question) => question.question).join(' ')}`
          : 'I need a little more detail before searching.';
      }
      const nextDecision = body?.intent?.decision;
      const pick = body?.products?.find((product) => product.id === nextDecision?.recommended_product_id);
      if (nextDecision?.status === 'no_safe_fit') return `No safe fit clears this mission yet. ${nextDecision.mission_change || 'Try adjusting one hard constraint.'}`;
      if (nextDecision?.status === 'verify_before_buy') return `${sanitizeTitle(pick?.name)} is the current recommendation. Before buying, verify: ${(nextDecision.blocking_risks || []).join(', ')}.`;
      if (nextDecision?.status === 'buy_now') return `${sanitizeTitle(pick?.name)} now clears the mission. The retailer handoff is ready below.`;
      return 'I updated the mission using the completed research.';
    },
    [handleSearchWithPayload, postUrl, reference, result, user],
  );

  const handleQuickAnswer = useCallback(
    (answer) => {
      setQuery(answer);
      return handleSearchWithPayload(answer, '', null, { throwOnError: false });
    },
    [handleSearchWithPayload],
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
      setAuthAction('save_plan');
      setAuthOpen(true);
      return;
    }
    setIsSavingPlan(true);
    try {
      const body = await createPlan({ search_id: result.search_id, products: selectedProducts });
      setPlans((current) => [body.plan, ...current.filter((plan) => plan.id !== body.plan.id)]);
      clearPendingSearch();
      setAuthAction(null);
      setPostAuthAction(null);
      setActiveView('plans');
      setToast('Purchase plan saved. Open retailer links when you are ready.');
    } catch (error) {
      setPostAuthAction(null);
      if (/sign in/i.test(error.message)) {
        setAuthAction('save_plan');
        setAuthOpen(true);
      } else {
        clearPendingSearch();
        setToast(error.message || 'Could not save this purchase plan.');
      }
    } finally {
      setIsSavingPlan(false);
    }
  }, [isSavingPlan, result.search_id, selectedProducts, user]);

  useEffect(() => {
    if (user?.id && postAuthAction === 'save_plan' && selectedProducts.length && !isSavingPlan) {
      handleSavePlan();
    }
  }, [handleSavePlan, isSavingPlan, postAuthAction, selectedProducts.length, user?.id]);

  const handleStartCheckout = useCallback(() => {
    if (!selectedProducts.length) {
      setToast('Select at least one product before checkout.');
      return;
    }
    if (!user) {
      setAuthOpen(true);
      return;
    }
    if (!health.payment_configured || health.payment_provider !== 'sandbox') {
      setToast('Open the retailer link to complete a real purchase. Artha cannot collect payment for retailer orders.');
      return;
    }
    setCheckoutOpen(true);
  }, [health.payment_configured, health.payment_provider, selectedProducts.length, user]);

  const handleConfirmOrder = useCallback(async () => {
    if (!selectedProducts.length || !user || isCreatingOrder) return;
    setIsCreatingOrder(true);
    const purchasePayload = {
      confirmed: true,
      search_id: result.search_id,
      products: selectedProducts,
      intent: result.intent,
      location: result.intent?.location,
    };
    try {
      const body = await createOrder(purchasePayload);
      setOrders((current) => [body.order, ...current.filter((order) => order.id !== body.order.id)]);
      setCheckoutOpen(false);
      setActiveView('orders');
      setToast(`Order ${body.order.id} confirmed in the local tracker.`);
    } catch (error) {
      setToast(error.message || 'The order could not be created.');
    } finally {
      setIsCreatingOrder(false);
    }
  }, [isCreatingOrder, result.intent, result.search_id, selectedProducts, user]);

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
    const opportunityText = result.summary?.opportunity ? ` One other option is ${sanitizeTitle(result.summary.opportunity.name)} for ${formatPrice(result.summary.opportunity.extra)} more than the stated budget.` : '';
    const text = `Your purchase plan includes ${selectedProducts.map((p) => sanitizeTitle(p.name)).join(', ')}. The current subtotal is ${formatPrice(selectedProducts.reduce((sum, p) => sum + productTotal(p), 0))}. ${result.summary?.delivery_label || 'Confirm delivery with each retailer.'}${opportunityText}`;
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
    (next = '/', pendingAction = null) => {
      preservePendingSearch({ query, postUrl, result, selectedIds, location, pendingAction });
      beginGoogleSignIn(next);
    },
    [location, postUrl, query, result, selectedIds],
  );

  const view =
    activeView === 'discover' ? (
      <DiscoverView
        result={result}
        paymentProvider={health.payment_configured && health.payment_provider === 'sandbox' ? 'sandbox' : 'disabled'}
        query={query}
        setQuery={setQuery}
        mission={mission}
        onMissionChange={setMission}
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
        searchError={searchError}
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
        isSessionLoading={isSessionLoading}
        onSavePlan={handleSavePlan}
        isSavingPlan={isSavingPlan}
        onStartCheckout={handleStartCheckout}
        onToast={setToast}
        onPickPrompt={handlePickPrompt}
        onOpenTalk={() => setTalkOpen(true)}
        onQuickAnswer={handleQuickAnswer}
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
        isSessionLoading={isSessionLoading}
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
        isSessionLoading={isSessionLoading}
        plans={plans}
        onDiscover={startNewSearch}
        onSignIn={() => startSignIn('/plans')}
      />
    );

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to main content</a>
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
          isSessionLoading={isSessionLoading}
          onSignIn={() => startSignIn(activeView === 'plans' ? '/plans' : activeView === 'orders' ? '/orders' : activeView === 'usage' ? '/usage' : '/')}
          onSignOut={handleSignOut}
          onOpenTalk={() => setTalkOpen(true)}
        />
        {view}
      </main>
      <MobileNav activeView={activeView} onNavigate={setActiveView} planCount={plans.length} />
      {authOpen ? (
        <AuthSheet
          onClose={() => {
            setAuthAction(null);
            setAuthOpen(false);
          }}
          onSignIn={() => startSignIn('/', authAction)}
        />
      ) : null}
      {checkoutOpen ? (
        <CheckoutSheet
          products={selectedProducts}
          intent={result.intent}
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
      <TalkDrawer
        open={talkOpen}
        onClose={() => setTalkOpen(false)}
        onAsk={handleTalkAsk}
        onToast={setToast}
        workflow={result.workflow}
      />
      <Toast message={toast} />
      </div>
    </>
  );
}
