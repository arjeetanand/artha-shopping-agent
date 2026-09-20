import React, { useMemo, useRef, useState } from 'react';
import {
  advanceOrder,
  analyzeRequest,
  buildUnderstanding,
  createApproval,
  createOrder,
  formatINR,
  getRejected,
  makeSessionId,
  searchAndRank,
  trackingSteps,
} from './lib/demoEngine';
import { callMakeGateway, isGatewayConfigured } from './lib/gateway';

const stageOrder = ['home', 'understanding', 'searching', 'recommendations', 'approval', 'confirmation', 'tracking'];

function Icon({ name, size = 18 }) {
  const paths = {
    arrow: <><path d="M4 12h15" /><path d="m13 6 6 6-6 6" /></>,
    back: <><path d="M20 12H5" /><path d="m11 18-6-6 6-6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    image: <><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9" r="1.5" /><path d="m21 15-4.5-4.5L7 20" /></>,
    mic: <><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3M8 22h8" /></>,
    sparkle: <><path d="m12 3-1.4 5.6L5 10l5.6 1.4L12 17l1.4-5.6L19 10l-5.6-1.4L12 3Z" /><path d="m19 16-.7 2.3L16 19l2.3.7L19 22l.7-2.3L22 19l-2.3-.7L19 16Z" /></>,
    bag: <><path d="M5 8h14l1 13H4L5 8Z" /><path d="M9 8V6a3 3 0 0 1 6 0v2" /></>,
    pin: <><path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="2.5" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    refresh: <><path d="M20 11a8.1 8.1 0 0 0-14.8-3L3 11" /><path d="M3 5v6h6" /><path d="M4 13a8.1 8.1 0 0 0 14.8 3L21 13" /><path d="M21 19v-6h-6" /></>,
    external: <><path d="M14 4h6v6" /><path d="m20 4-9 9" /><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function Provenance({ children, tone = 'verified' }) {
  return <span className={`provenance provenance-${tone}`}><i />{children}</span>;
}

function ProductVisual({ variant = 'oat', large = false }) {
  return <div className={`product-visual product-visual-${variant} ${large ? 'product-visual-large' : ''}`} aria-hidden="true">
    <div className="visual-halo" />
    <div className="visual-scarf" />
    <div className="visual-item visual-shirt" />
    <div className="visual-item visual-trouser" />
    <div className="visual-item visual-shoe" />
  </div>;
}

function ProgressRail({ view, sessionId, order }) {
  const labels = [
    ['home', 'Your brief'],
    ['understanding', 'AI understanding'],
    ['searching', 'Constraint check'],
    ['recommendations', 'Curated matches'],
    ['approval', 'Approval gate'],
    ['tracking', 'Order tracking'],
  ];
  const current = stageOrder.indexOf(view);
  return <aside className="progress-rail">
    <div className="rail-top">
      <span className="rail-kicker">LIVE AGENT RUN</span>
      <span className="rail-dot" />
    </div>
    <div className="rail-session">{sessionId ? sessionId.replace('sess_', 'session / ') : 'new session'}</div>
    <nav className="rail-steps" aria-label="Purchase journey">
      {labels.map(([key, label], index) => {
        const complete = current > stageOrder.indexOf(key) || (key === 'tracking' && order);
        const active = view === key || (view === 'confirmation' && key === 'tracking');
        return <button key={key} className={`rail-step ${active ? 'is-active' : ''} ${complete ? 'is-complete' : ''}`} onClick={() => {}} type="button">
          <span className="rail-step-icon">{complete ? <Icon name="check" size={14} /> : String(index + 1).padStart(2, '0')}</span>
          <span>{label}</span>
        </button>;
      })}
    </nav>
    <div className="rail-footer">
      <div className="rail-status"><span className="status-pulse" /> Make orchestration <strong>connected</strong></div>
      <p>Business rules run in the workflow layer. This demo never stores payment details.</p>
      {order && <button className="text-link" type="button" onClick={() => {}}>INSP-ORDER · {order.trackingStatus}</button>}
    </div>
  </aside>;
}

function Header({ onReset, onTrack, order }) {
  return <header className="app-header">
    <button className="wordmark" type="button" onClick={onReset} aria-label="Go to INSPIRA home"><span>INSPIRA</span><em>AI PURCHASE AGENT</em></button>
    <div className="header-actions">
      <span className="header-location"><Icon name="pin" size={15} /> Bangalore · INR</span>
      {order && <button className="header-track" type="button" onClick={onTrack}><span className="header-order-dot" /> Track order <Icon name="arrow" size={15} /></button>}
      <button className="new-request" type="button" onClick={onReset}>New request <span>↗</span></button>
    </div>
  </header>;
}

function Home({ message, setMessage, image, setImage, demoImage, setDemoImage, onSubmit }) {
  const fileRef = useRef(null);
  const upload = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (loadEvent) => { setImage(loadEvent.target.result); setDemoImage(true); };
    reader.readAsDataURL(file);
  };
  return <main className="home-view content-view">
    <section className="hero-copy">
      <p className="eyebrow">A shopping agent for the things you can’t quite search for</p>
      <h1>See it.<br /><i>Want it.</i><br />Let AI shop it.</h1>
      <p className="hero-lede">Show INSPIRA what sparked your interest. It turns the visual cue into a brief, filters real constraints, and waits for your yes before it places a simulated order.</p>
      <div className="hero-proof"><span><Icon name="sparkle" size={15} /> Multimodal brief</span><span><Icon name="check" size={15} /> Hard constraints</span><span><Icon name="bag" size={15} /> Approval-gated</span></div>
    </section>
    <section className="brief-composer" aria-label="Shopping brief composer">
      <div className="composer-image-wrap">
        <div className={`composer-image ${demoImage ? 'has-image' : ''}`} style={{ backgroundImage: demoImage ? `url(${image})` : 'none' }}>
          <div className="composer-image-overlay" />
          {!demoImage && <div className="image-empty">
            <span className="image-mark"><Icon name="image" size={22} /></span>
            <strong>Start with an image</strong>
            <span>or describe what you’re after</span>
          </div>}
          {demoImage && <div className="image-caption"><span>INSPIRATION / 01</span><strong>Neutral travel set</strong></div>}
          <button className="image-upload-button" type="button" onClick={() => fileRef.current?.click()}><Icon name="image" size={15} /> {demoImage ? 'Replace image' : 'Upload image'}</button>
        </div>
        <input ref={fileRef} type="file" accept="image/*" onChange={upload} hidden />
        {!demoImage && <button className="demo-inspiration" type="button" onClick={() => { setDemoImage(true); setMessage('I want an outfit like this for a Goa trip'); }}><span>✦</span> Use a demo inspiration</button>}
      </div>
      <div className="composer-text">
        <label htmlFor="brief">What inspired you today?</label>
        <textarea id="brief" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Find me something like this for a Goa trip — under ₹6,000, delivered to Bangalore within 5 days." rows={4} />
        <div className="composer-meta"><span>Try “whole outfit under ₹6,000”</span><button className="voice-button" type="button" onClick={() => setMessage((current) => `${current}${current ? ' ' : ''}Whole outfit under ₹6,000, delivered within 5 days.`)}><Icon name="mic" size={16} /> Voice note</button></div>
        <button className="primary-button composer-submit" type="button" onClick={onSubmit}>Build my shortlist <Icon name="arrow" size={18} /></button>
        <div className="composer-note"><span className="secure-mark">⌁</span> No payment details needed. You’ll approve before any demo order is created.</div>
      </div>
    </section>
    <section className="home-bottomline"><span>Recent demo activity</span><span className="home-line" /><span>1 order tracking · 3 saved preferences</span></section>
  </main>;
}

function Understanding({ understanding, onContinue, onClarify }) {
  const needsClarification = understanding.clarification_needed || !understanding.description || understanding.description.includes('uploaded inspiration image');
  return <main className="content-view understanding-view">
    <div className="section-heading"><div><p className="eyebrow">01 / Translate the signal</p><h2>I think you’re looking for<span>.</span></h2></div><Provenance tone="inferred">AI inferred</Provenance></div>
    <div className="understanding-grid">
      <div className="understanding-panel">
        <div className="understanding-visual"><ProductVisual variant="oat" large /><div className="visual-stamp">INSPIRATION<br />MATCH</div></div>
        <div className="visual-caption"><span>From the image / your brief</span><strong>{understanding.description || 'A relaxed neutral travel outfit'}</strong></div>
      </div>
      <div className="signal-list">
        <div className="signal-row"><span>Category</span><strong>{understanding.productCategory}</strong></div>
        <div className="signal-row"><span>Style direction</span><strong>{understanding.style?.join(' · ')}</strong></div>
        <div className="signal-row"><span>Palette</span><strong>{understanding.colors?.join(' · ') || 'neutral / low contrast'}</strong></div>
        <div className="signal-row"><span>Occasion</span><strong>{understanding.occasion}</strong></div>
        {understanding.visualAttributes?.map((attribute) => <div className="signal-row" key={attribute}><span>Visual cue</span><strong>{attribute}</strong></div>)}
        <div className="understanding-legend"><span><i className="dot-inferred" /> AI inferred</span><span><i className="dot-user" /> User provided</span><span><i className="dot-verified" /> Verified after search</span></div>
      </div>
    </div>
    {needsClarification ? <div className="clarify-box"><div><p className="eyebrow">One quick question</p><h3>Are you shopping for the whole look or one piece from it?</h3></div><div className="clarify-actions"><button type="button" onClick={() => onClarify('Whole outfit under ₹6,000, delivered to Bangalore within 5 days.')}>Whole outfit <Icon name="arrow" size={15} /></button><button type="button" onClick={() => onClarify('Only the shirt under ₹2,500, delivered to Bangalore within 5 days.')}>Just the shirt <Icon name="arrow" size={15} /></button></div></div> : <div className="section-action-row"><span><Icon name="check" size={15} /> Intent structured · no missing critical fields</span><button className="primary-button" type="button" onClick={onContinue}>Search valid options <Icon name="arrow" size={17} /></button></div>}
  </main>;
}

function Searching({ searchStage }) {
  const stages = ['Understanding inspiration', 'Finding products', 'Checking hard constraints', 'Comparing total cost', 'Ranking matches'];
  return <main className="content-view searching-view"><div className="searching-center"><div className="search-orbit"><span /><span /><span /><Icon name="sparkle" size={25} /></div><p className="eyebrow">02 / Make orchestration in progress</p><h2>Building a shortlist<br /><i>that can actually happen.</i></h2><p className="searching-lede">AI is interpreting the brief. The workflow is checking stock, price, delivery, and seller quality before it lets a product through.</p><div className="search-timeline">{stages.map((stage, index) => <div className={`search-timeline-row ${index <= searchStage ? 'is-done' : ''} ${index === searchStage ? 'is-active' : ''}`} key={stage}><span className="timeline-node">{index < searchStage ? <Icon name="check" size={13} /> : index + 1}</span><span>{stage}</span>{index === searchStage && <em>running</em>}</div>)}</div><div className="search-footnote"><span className="status-pulse" /> Rules live in PA_01_User_Request_Gateway · demo mode</div></div></main>;
}

function BundleCard({ item, selected, onSelect }) {
  return <article className={`bundle-card ${selected ? 'is-selected' : ''}`}>
    <div className="bundle-card-top"><div className="bundle-rank">0{item.rank}</div><span className={`recommendation-badge badge-${item.badgeTone}`}>{item.badge}</span></div>
    <ProductVisual variant={item.rank === 1 ? 'oat' : item.rank === 2 ? 'clay' : 'cream'} large />
    <div className="bundle-copy"><div className="bundle-title-row"><div><p className="bundle-eyebrow">{item.items.map((part) => part.category).join(' / ')}</p><h3>{item.title}</h3></div><div className="score"><strong>{item.score}</strong><span>match</span></div></div><div className="bundle-price"><strong>{formatINR(item.totalCost)}</strong><span>incl. {formatINR(item.shipping)} shipping</span></div><div className="bundle-details"><span><Icon name="clock" size={14} /> {item.deliveryDays} days</span><span><Icon name="check" size={14} /> In stock</span><span><Icon name="pin" size={14} /> Bangalore</span></div><ul className="why-list">{item.why.map((reason) => <li key={reason}><span>↳</span>{reason}</li>)}</ul><div className="bundle-footer"><div className="provenance-row"><Provenance tone="verified">stock / ratings</Provenance><Provenance tone="simulated">price / delivery</Provenance></div><button className={selected ? 'selected-button' : 'secondary-button'} type="button" onClick={() => onSelect(item)}>{selected ? <><Icon name="check" size={16} /> Selected</> : <>Select set <Icon name="arrow" size={16} /></>}</button></div></div>
  </article>;
}

function SingleCard({ item, selected, onSelect }) {
  return <article className={`single-card ${selected ? 'is-selected' : ''}`}><div className="single-card-visual"><ProductVisual variant="graphite" large /><span className="single-score">{item.score}<small>match</small></span></div><div className="single-card-copy"><p className="bundle-eyebrow">{item.category} · {item.brand}</p><h3>{item.title}</h3><div className="single-price"><strong>{formatINR(item.totalCost)}</strong><span>delivery in {item.deliveryDays} days</span></div><div className="single-stats"><span>★ {item.rating}</span><span>{item.stock} in stock</span><span>{item.sellerReliability}% seller</span></div><div className="constraint-mini"><span className={item.budgetPass ? 'pass' : 'fail'}>{item.budgetPass ? '✓ budget' : '× budget'}</span><span className={item.deliveryPass ? 'pass' : 'fail'}>{item.deliveryPass ? '✓ delivery' : '× delivery'}</span><span className={item.stockPass ? 'pass' : 'fail'}>{item.stockPass ? '✓ stock' : '× stock'}</span></div><button className={selected ? 'selected-button' : 'secondary-button'} type="button" onClick={() => onSelect(item)}>{selected ? <><Icon name="check" size={16} /> Selected</> : <>Select option <Icon name="arrow" size={16} /></>}</button></div></article>;
}

function Recommendations({ understanding, recommendations, rejected, selected, onSelect, onBack }) {
  const isBundle = understanding.purchaseMode === 'outfit_bundle';
  return <main className="content-view recommendations-view"><div className="section-heading recommendation-heading"><div><p className="eyebrow">03 / Valid matches only</p><h2>{recommendations.length ? 'Three ways to wear the idea' : 'Nothing passed every rule'}<span>.</span></h2><p className="section-lede">{recommendations.length ? 'Every option below clears the hard constraints before style and value decide the order.' : 'I found candidates, but not a valid match for every mandatory requirement.'}</p></div><div className="constraint-summary"><span className="status-pulse" />{understanding.budget ? `Under ${formatINR(understanding.budget)}` : 'No budget invented'}<br />{understanding.maxDeliveryDays ? `Within ${understanding.maxDeliveryDays} days` : 'Delivery not invented'}</div></div>{recommendations.length ? <><div className={isBundle ? 'bundle-grid' : 'single-grid'}>{recommendations.map((item, index) => isBundle ? <BundleCard item={{ ...item, rank: index + 1 }} key={item.id} selected={selected?.id === item.id} onSelect={onSelect} /> : <SingleCard item={item} key={item.id} selected={selected?.id === item.id} onSelect={onSelect} />)}</div><div className="comparison-strip"><div><span className="strip-label">What gets verified</span><strong>Budget · stock · delivery · total cost · seller quality</strong></div><div className="strip-note"><Provenance tone="verified">VERIFIED API</Provenance><Provenance tone="simulated">SIMULATED DEMO</Provenance><Provenance tone="inferred">AI RECOMMENDATION</Provenance></div></div></> : <div className="no-match-panel"><div className="no-match-icon">↯</div><h3>No valid options surfaced</h3><p>The workflow rejected every candidate because at least one mandatory constraint failed. Relax delivery or budget to continue; I won’t show an invalid match as a valid recommendation.</p>{rejected.map((item) => <div className="rejected-row" key={item.id}><span>{item.title}</span><strong>{item.reason}</strong></div>)}</div>}<div className="back-row"><button className="text-button" type="button" onClick={onBack}><Icon name="back" size={15} /> Edit brief</button>{selected && <span>Selected: <strong>{selected.title}</strong> · ready for approval</span>}</div></main>;
}

function Approval({ item, understanding, onConfirm, onBack }) {
  const items = item.items ?? [item];
  return <main className="content-view approval-view"><div className="section-heading"><div><p className="eyebrow">04 / Explicit approval required</p><h2>Ready when you are<span>.</span></h2><p className="section-lede">I’ve held this selection. Nothing has been ordered. Review the demo total, then choose what happens next.</p></div><div className="approval-lock"><span>⌁</span> approval gate</div></div><div className="approval-layout"><div className="approval-selection"><div className="approval-selection-head"><span>Your selected {items.length > 1 ? 'set' : 'option'}</span><span>Recommendation {item.score}/100</span></div><div className="approval-visual"><ProductVisual variant="oat" large /><div><p className="bundle-eyebrow">{items.map((part) => part.category).join(' / ')}</p><h3>{item.title}</h3><p>Curated for {understanding.occasion}. The style match is AI-recommended; stock and prices are simulated demo commerce data.</p></div></div><div className="approval-items">{items.map((part) => <div className="approval-item" key={part.id}><span className="item-dot" /><span>{part.title}</span><strong>{formatINR(part.price)}</strong></div>)}</div></div><div className="approval-receipt"><div className="receipt-top"><span>DEMO ORDER SUMMARY</span><span className="receipt-status"><span className="status-pulse" /> held for 20 min</span></div><div className="receipt-row"><span>Items · {items.length}</span><strong>{formatINR(item.subtotal ?? item.price)}</strong></div><div className="receipt-row"><span>Shipping <Provenance tone="simulated">SIMULATED</Provenance></span><strong>{formatINR(item.shipping ?? 0)}</strong></div><div className="receipt-total"><span>Total in INR</span><strong>{formatINR(item.totalCost)}</strong></div><div className="receipt-delivery"><Icon name="pin" size={17} /><div><span>Delivering to Bangalore</span><strong>Estimated {item.deliveryDate}</strong></div></div><button className="primary-button confirm-button" type="button" onClick={onConfirm}>Confirm simulated purchase <Icon name="arrow" size={17} /></button><button className="text-button choose-again" type="button" onClick={onBack}><Icon name="back" size={15} /> Choose another</button><p className="receipt-disclaimer">By confirming, you create a simulated hackathon transaction only. No real payment, customer secret, or merchant order is used.</p></div></div></main>;
}

function Confirmation({ order, onTrack, onNew }) {
  return <main className="content-view confirmation-view"><div className="confirmation-art"><div className="confirmation-ring"><Icon name="check" size={37} /></div><div className="confetti confetti-a" /><div className="confetti confetti-b" /><div className="confetti confetti-c" /></div><p className="eyebrow">05 / Mock order created</p><h2>Your demo order is on its way<span>.</span></h2><p className="confirmation-lede">INSPIRA created a simulated order only after your explicit approval. The workflow has saved the transaction and opened tracking.</p><div className="order-card"><div><span className="order-card-label">ORDER ID</span><strong>{order.orderId}</strong></div><div><span className="order-card-label">TOTAL</span><strong>{formatINR(order.total)}</strong></div><div><span className="order-card-label">EST. DELIVERY</span><strong>{order.estimatedDelivery}</strong></div></div><div className="confirmation-actions"><button className="primary-button" type="button" onClick={onTrack}>Open live tracking <Icon name="arrow" size={17} /></button><button className="text-button" type="button" onClick={onNew}>Start another brief</button></div><div className="mock-note"><span>SIMULATED</span> Order creation returned success · payment_status = MOCK_PAID · no real purchase occurred</div></main>;
}

function Tracking({ order, onAdvance, onCancel, onNew }) {
  const currentIndex = trackingSteps.findIndex((step) => step.key === order.trackingStatus);
  return <main className="content-view tracking-view"><div className="section-heading"><div><p className="eyebrow">06 / Order tracking</p><h2>Keep an eye on it<span>.</span></h2><p className="section-lede">Every status change becomes an order event. Advance the demo state to show the notification loop.</p></div><div className="tracking-id"><span>{order.orderId}</span><strong>{order.trackingStatus.replaceAll('_', ' ')}</strong></div></div><div className="tracking-layout"><div className="tracking-timeline">{trackingSteps.map((step, index) => <div className={`tracking-step ${index < currentIndex ? 'is-complete' : ''} ${index === currentIndex ? 'is-current' : ''}`} key={step.key}><div className="tracking-node">{index <= currentIndex ? <Icon name="check" size={14} /> : <span>{index + 1}</span>}</div><div className="tracking-step-copy"><strong>{step.label}</strong><span>{index === currentIndex ? step.note : index < currentIndex ? 'Complete' : 'Waiting for previous step'}</span>{index === currentIndex && <em>current status</em>}</div></div>)}</div><aside className="tracking-aside"><div className="tracking-aside-top"><span>DELIVERY DETAIL</span><Icon name="external" size={16} /></div><div className="tracking-detail-row"><span>Destination</span><strong>Bangalore, IN</strong></div><div className="tracking-detail-row"><span>ETA</span><strong>{order.estimatedDelivery}</strong></div><div className="tracking-detail-row"><span>Items</span><strong>{order.itemCount} {order.itemCount === 1 ? 'item' : 'items'}</strong></div><div className="tracking-notification"><span className="notification-icon"><Icon name="sparkle" size={16} /></span><div><strong>Notification sent</strong><span>“{order.trackingStatus.replaceAll('_', ' ').toLowerCase()}” event synced to the user.</span></div></div><button className="primary-button advance-button" type="button" onClick={onAdvance} disabled={currentIndex >= trackingSteps.length - 1}><Icon name="refresh" size={16} /> Advance demo status</button><button className="danger-button" type="button" onClick={onCancel}>Cancel order</button><button className="text-button track-new" type="button" onClick={onNew}>Shop again <Icon name="arrow" size={15} /></button></aside></div></main>;
}

export default function App() {
  const [view, setView] = useState('home');
  const [message, setMessage] = useState('');
  const [image, setImage] = useState('/assets/inspira-hero.png');
  const [demoImage, setDemoImage] = useState(false);
  const [sessionId, setSessionId] = useState('');
  const [understanding, setUnderstanding] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [rejected, setRejected] = useState([]);
  const [selected, setSelected] = useState(null);
  const [approval, setApproval] = useState(null);
  const [order, setOrder] = useState(null);
  const [searchStage, setSearchStage] = useState(0);
  const [error, setError] = useState('');

  const reset = () => { setView('home'); setMessage(''); setDemoImage(false); setSessionId(''); setUnderstanding(null); setRecommendations([]); setRejected([]); setSelected(null); setApproval(null); setOrder(null); setError(''); };
  const begin = async (workingMessage = message) => {
    if (!workingMessage.trim() && !demoImage) { setError('Add a short brief or an inspiration image to begin.'); return; }
    const nextSession = sessionId || makeSessionId();
    if (isGatewayConfigured) {
      try {
        setView('searching'); setSearchStage(1);
        const response = await callMakeGateway({ session_id: sessionId || undefined, conversation_id: nextSession, action: 'shop', input_type: demoImage && workingMessage ? 'combined' : demoImage ? 'image' : 'text', message: workingMessage, image_url: null, image_data: demoImage ? image : null, context: { currency: 'INR', location: 'Bangalore' } });
        setSessionId(response.session_id || nextSession);
        if (response.data?.requirements) setUnderstanding(response.data.requirements);
        if (response.data?.recommendations) setRecommendations(response.data.recommendations);
        if (response.data?.rejected) setRejected(response.data.rejected);
        setError('');
        setView(response.response_type === 'clarification' ? 'understanding' : response.response_type === 'recommendations' ? 'recommendations' : 'understanding');
        return;
      } catch (gatewayError) {
        setError(`Make gateway unavailable: ${gatewayError.message}`);
        return;
      }
    }
    const analysis = analyzeRequest({ message: workingMessage, hasImage: demoImage });
    const nextUnderstanding = buildUnderstanding({ analysis, message: workingMessage, hasImage: demoImage });
    setSessionId(nextSession); setUnderstanding(nextUnderstanding); setError(''); setView('understanding');
  };
  const runSearch = () => {
    setView('searching'); setSearchStage(0);
    [400, 800, 1200, 1600].forEach((delay, index) => setTimeout(() => setSearchStage(index + 1), delay));
    setTimeout(() => { const next = searchAndRank(understanding); setRecommendations(next); setRejected(getRejected(understanding)); setView('recommendations'); }, 2050);
  };
  const clarify = async (reply) => {
    setMessage(reply);
    if (isGatewayConfigured) { await begin(reply); return; }
    const analysis = analyzeRequest({ message: reply, hasImage: demoImage }); setUnderstanding(buildUnderstanding({ analysis, message: reply, hasImage: demoImage })); setTimeout(() => { setView('searching'); setSearchStage(0); [400, 800, 1200, 1600].forEach((delay, index) => setTimeout(() => setSearchStage(index + 1), delay)); setTimeout(() => { setRecommendations(searchAndRank(analysis)); setRejected(getRejected(analysis)); setView('recommendations'); }, 2050); }, 180);
  };
  const select = (item) => { setSelected(item); setApproval(item.approval_token ? { approvalToken: item.approval_token, status: 'PENDING_CONFIRMATION', selected: item } : createApproval(item, sessionId)); setView('approval'); };
  const confirm = async () => {
    if (!approval || approval.status !== 'PENDING_CONFIRMATION') return;
    if (isGatewayConfigured) {
      try {
        const response = await callMakeGateway({ action: 'confirm_purchase', session_id: sessionId, approval_token: approval.approvalToken, confirmed: true });
        setOrder(response.data?.order); setApproval({ ...approval, status: 'PURCHASED' }); setView('confirmation');
      } catch (confirmError) { setError(confirmError.message); }
      return;
    }
    setOrder(createOrder(approval)); setApproval({ ...approval, status: 'PURCHASED' }); setView('confirmation');
  };
  const advance = async () => {
    if (!order) return;
    if (isGatewayConfigured) {
      try { const response = await callMakeGateway({ action: 'advance_order', session_id: sessionId, order_id: order.orderId }); setOrder(response.data?.order); } catch (advanceError) { setError(advanceError.message); }
      return;
    }
    setOrder((current) => advanceOrder(current));
  };
  const cancel = async () => {
    if (!order) return;
    if (isGatewayConfigured) {
      try { const response = await callMakeGateway({ action: 'cancel_order', session_id: sessionId, order_id: order.orderId }); setOrder(response.data?.order); } catch (cancelError) { setError(cancelError.message); }
      return;
    }
    setOrder((current) => ({ ...current, trackingStatus: 'CANCELLED', lastNotifiedStatus: 'CANCELLED' }));
  };
  const activeIndex = useMemo(() => stageOrder.indexOf(view), [view]);
  return <div className="app-shell"><Header onReset={reset} onTrack={() => order && setView('tracking')} order={order} /><div className="app-body"><ProgressRail view={view} sessionId={sessionId} order={order} /><div className="main-stage">{error && <div className="error-banner" role="alert">{error}<button type="button" onClick={() => setError('')}>Dismiss</button></div>}{view === 'home' && <Home {...{ message, setMessage, image, setImage, demoImage, setDemoImage }} onSubmit={() => begin()} />}{view === 'understanding' && understanding && <Understanding understanding={understanding} onContinue={runSearch} onClarify={clarify} />}{view === 'searching' && <Searching searchStage={searchStage} />}{view === 'recommendations' && understanding && <Recommendations understanding={understanding} recommendations={recommendations} rejected={rejected} selected={selected} onSelect={select} onBack={() => setView('understanding')} />}{view === 'approval' && selected && understanding && <Approval item={selected} understanding={understanding} onConfirm={confirm} onBack={() => setView('recommendations')} />}{view === 'confirmation' && order && <Confirmation order={order} onTrack={() => setView('tracking')} onNew={reset} />}{view === 'tracking' && order && <Tracking order={order} onAdvance={advance} onCancel={cancel} onNew={reset} />}</div></div><footer className="app-footer"><span>INSPIRA / demo environment</span><span>Make.com is the orchestration brain · approval before action</span><span>Journey {String(Math.min(Math.max(activeIndex + 1, 1), 6)).padStart(2, '0')} / 06</span></footer></div>;
}
