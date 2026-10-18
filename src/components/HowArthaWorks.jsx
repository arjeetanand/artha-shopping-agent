import React from 'react';
import { Icon } from './Icon';

const stages = [
  {
    agent: 'Brief agent',
    title: 'Understand what you need',
    detail: 'Reads your words and optional reference image or product link; pulls out category, budget, size, color, deadline, and must-haves.',
  },
  {
    agent: 'Location agent',
    title: 'Check where it needs to arrive',
    detail: 'Uses the city or pincode you provide to check delivery context.',
    checkpoint: 'If a key detail is missing, Artha pauses and asks you before it searches.',
  },
  {
    agent: 'Search agent',
    title: 'Find retailer options',
    detail: 'Searches configured retailer sources for product pages, or uses the sample catalog in demo mode.',
  },
  {
    agent: 'Evidence agent',
    title: 'Organize what each source says',
    detail: 'Collects price, seller, stock, variant, delivery, and review details, marking missing facts as unknown.',
  },
  {
    agent: 'Research agent',
    title: 'Check the product pages',
    detail: 'Looks at retailer pages for the exact item and checks other stores when a reliable match is possible.',
  },
  {
    agent: 'Analysis agent',
    title: 'Compare price and review signals',
    detail: 'Cross-checks available review evidence and Artha’s recorded price observations.',
  },
  {
    agent: 'Decision agent',
    title: 'Rank the options and explain risks',
    detail: 'Matches products against your requirements and explains what is ready and what still needs checking.',
  },
];

const storyChapters = [
  {
    number: '01',
    chapter: 'DESCRIBE',
    headline: 'Tell Artha what you need.',
    body: 'Start by speaking; Artha asks follow-up questions and captures your budget, delivery pincode, size, and style. Add a reference photo or Instagram/store link if you have one.',
    annotation: '“Say what you need, then let Artha research.”',
    themeClass: 'story-chapter--describe',
    bg: '#B6FE00',
    ink: '#034102',
    badge: 'FOLDER 01 // BRIEF & INSPIRATION',
    cardTitle: 'Linen shirt under ₹2,500 · Bengaluru',
    cardMeta: 'Reference photo attached · Size M · Arrive in 4 days',
    image: '/assets/editorial-outfit-triptych.png',
    imageAlt: 'Saved reference outfit collage in a shopping folder',
    priceTag: 'Budget cap: ₹2,500',
  },
  {
    number: '02',
    chapter: 'COMPARE',
    headline: 'Understand options, sources, and trade-offs.',
    body: 'Instead of twenty open browser tabs, see verified INR prices, variant availability, delivery windows, and unconfirmed claims side by side. Artha never invents stock or reviews—missing details stay clearly flagged.',
    annotation: '“Every claim checked against the source.”',
    themeClass: 'story-chapter--compare',
    bg: '#FA8005',
    ink: '#034102',
    badge: 'FOLDER 02 // RETAILER EVIDENCE',
    cardTitle: '3 Retailer Pages Compared',
    cardMeta: 'Lowest checked offer: ₹2,190 · 1 store needs pincode check',
    image: '/assets/editorial-outfit-triptych.png',
    imageAlt: 'Neutral linen outfit reference used while comparing retailer options',
    priceTag: 'Evidence checked · ₹2,190',
  },
  {
    number: '03',
    chapter: 'CHOOSE',
    headline: 'Save a shortlist and continue with the retailer.',
    body: 'Organize your top picks into private purchase plans, revisit recorded price history, and click “View at retailer” when you are ready to buy. Real purchases and order fulfillment always happen directly with the merchant.',
    annotation: '“Your moodboard, with the research done.”',
    themeClass: 'story-chapter--choose',
    bg: '#50CBFF',
    ink: '#034102',
    badge: 'FOLDER 03 // SHORTLIST & HANDOFF',
    cardTitle: 'Ready for Retailer Handoff',
    cardMeta: 'Direct merchant links · Zero middleman checkout',
    image: '/assets/premium-white-sneaker.png',
    imageAlt: 'Product cutout ready for direct retailer handoff',
    priceTag: 'View at retailer ↗',
  },
];

export function HowArthaWorks({ onNavigate, onStartBrief }) {
  const handleStartBrief = () => {
    if (onStartBrief) {
      onStartBrief();
      return;
    }
    const input = document.getElementById('shopping-brief');
    if (input) {
      input.scrollIntoView({ behavior: 'smooth', block: 'center' });
      input.focus();
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  return (
    <div className="editorial-story-wrapper">
      {/* Curved top transition into Story Chapters */}
      <div className="section-curve section-curve--to-forest" aria-hidden="true">
        <svg viewBox="0 0 1440 72" preserveAspectRatio="none">
          <path d="M0,72 C360,8 1080,8 1440,72 L1440,72 L0,72 Z" fill="#034102" />
        </svg>
      </div>

      <section className="story-chapters" aria-labelledby="story-chapters-heading">
        <div className="story-chapters__intro">
          <span className="story-chapters__eyebrow">WHY ARTHA EXISTS</span>
          <h2 id="story-chapters-heading" className="story-chapters__headline">
            <span>YOUR SHOPPING MOODBOARD,</span>
            <span className="story-chapters__headline-accent">WITH THE RESEARCH DONE.</span>
          </h2>
          <p className="story-chapters__sub">
            Artha researches shopping options across retailers so you can compare real evidence. Real purchases happen at the retailer.
          </p>
        </div>

        <div className="story-chapters__stack">
          {storyChapters.map((item) => (
            <article
              key={item.chapter}
              className={`story-chapter-card ${item.themeClass}`}
              style={{ '--chapter-bg': item.bg, '--chapter-ink': item.ink }}
            >
              <div className="story-chapter-card__copy">
                <div className="story-chapter-card__meta">
                  <span className="story-chapter-card__num">{item.number}</span>
                  <span className="story-chapter-card__badge">{item.badge}</span>
                </div>
                <h3 className="story-chapter-card__title">{item.chapter}</h3>
                <p className="story-chapter-card__lead">{item.headline}</p>
                <p className="story-chapter-card__body">{item.body}</p>
                <span className="story-chapter-card__annotation" aria-hidden="true">
                  {item.annotation}
                </span>
              </div>

              <div className="story-chapter-card__visual">
                <div className="story-collage-folder">
                  <div className="story-collage-folder__tab">{item.badge}</div>
                  <div className="story-collage-folder__photo-frame">
                    <img
                      src={item.image}
                      alt={item.imageAlt}
                      loading="lazy"
                      decoding="async"
                      onError={(e) => {
                        e.currentTarget.style.display = 'none';
                      }}
                    />
                  </div>
                  <div className="story-collage-folder__note">
                    <strong>{item.cardTitle}</strong>
                    <small>{item.cardMeta}</small>
                  </div>
                  <span className="story-collage-folder__price-tag">{item.priceTag}</span>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* Detailed 7-agent "How Artha works" explanation preserved */}
      <section id="how-artha-works" className="how-artha-works" aria-labelledby="how-artha-works-title">
        <div className="how-artha-works__intro">
          <span className="section-kicker">The research, step by step</span>
          <h2 id="how-artha-works-title">From your brief to a clearer choice.</h2>
          <p>Start by speaking or typing a brief, then add a reference image or style link if you have one. Artha researches options; you review the evidence and choose where to buy.</p>
        </div>

        <ol className="how-artha-works__steps">
          {stages.map((stage, index) => (
            <li className="how-artha-works__step" key={stage.agent}>
              <span className="how-artha-works__number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
              <div className="how-artha-works__copy">
                <span className="how-artha-works__agent">{stage.agent}</span>
                <h3>{stage.title}</h3>
                <p>{stage.detail}</p>
                {stage.checkpoint ? <p className="how-artha-works__checkpoint">{stage.checkpoint}</p> : null}
              </div>
            </li>
          ))}
        </ol>

        <aside className="how-artha-works__trust" aria-label="What Artha's recommendation means">
          <h3>Clear about what it knows</h3>
          <p>
            Artha can recommend a product or tell you what to verify. Retailer pages confirm the final price, stock, variant, and delivery. Purchases and real order tracking happen with the retailer.
          </p>
          <div className="how-artha-works__outcomes" aria-label="Recommendation outcomes">
            <span className="outcome-pill outcome-pill--checked"><b>Evidence checked</b> meets Artha’s checks</span>
            <span className="outcome-pill outcome-pill--verify"><b>Verify first</b> some details are unknown</span>
            <span className="outcome-pill outcome-pill--nofit"><b>No safe fit</b> nothing clears the requirements</span>
          </div>
        </aside>
      </section>

      {/* Oversized Artha Editorial Footer */}
      <footer className="artha-editorial-footer" aria-label="Artha footer and quick navigation">
        <div className="artha-editorial-footer__top">
          <div className="artha-editorial-footer__cta-block">
            <span className="artha-editorial-footer__annotation">A little more thought in every buy.</span>
            <h2 className="artha-editorial-footer__invitation">
              READY TO TURN YOUR NEXT IDEA INTO A VETTED SHORTLIST?
            </h2>
            <p className="artha-editorial-footer__disclaimer">
              Artha researches shopping options and organizes evidence. Real purchases happen at the retailer.
            </p>
          </div>
          <button
            type="button"
            className="stamp-action-button stamp-action-button--lime"
            onClick={handleStartBrief}
          >
            <span className="stamp-action-button__ring" aria-hidden="true" />
            <span className="stamp-action-button__label">START A BRIEF</span>
            <Icon name="arrow" size={18} />
          </button>
        </div>

        {onNavigate ? (
          <nav className="artha-editorial-footer__nav" aria-label="Footer navigation">
            {[
              { id: 'discover', label: 'Discover' },
              { id: 'taste-graph', label: 'Taste OS' },
              { id: 'saved', label: 'Saved' },
              { id: 'plans', label: 'Purchase plans' },
              { id: 'orders', label: 'Orders' },
              { id: 'usage', label: 'Usage' },
            ].map((item) => (
              <button
                type="button"
                key={item.id}
                className="artha-editorial-footer__nav-link"
                onClick={() => {
                  onNavigate(item.id);
                  window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
              >
                <span>{item.label}</span>
                <Icon name="arrow" size={14} />
              </button>
            ))}
          </nav>
        ) : null}

        <div className="artha-editorial-footer__wordmark-wrap" aria-hidden="true">
          <div className="artha-editorial-footer__wordmark">
            <span>A</span>
            <span>R</span>
            <span>T</span>
            <span>H</span>
            <span>A</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
