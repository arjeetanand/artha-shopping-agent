import React from 'react';
import { Icon } from './Icon';

const steps = [
  {
    number: '01',
    title: 'Tell Artha what you like',
    detail: 'Speak naturally about the item, budget, fit, or a style you admire. You can mention a friend like Paras or share a public Instagram post.',
  },
  {
    number: '02',
    title: 'Compare real options',
    detail: 'See retailer links and the details Artha could check. Unknown prices, sizes, and delivery claims stay clearly marked.',
  },
  {
    number: '03',
    title: 'Choose where to buy',
    detail: 'Save your favourites into a plan, then finish your purchase directly with the retailer.',
  },
];

export function HowArthaWorks({ onNavigate, onStartBrief }) {
  const startBrief = () => {
    if (onStartBrief) return onStartBrief();
    const assistant = document.getElementById('home-voice-assistant');
    assistant?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    assistant?.querySelector('[data-testid="home-mic-button"]')?.focus({ preventScroll: true });
  };

  return (
    <div className="editorial-story-wrapper">
      <section className="how-artha-works" id="how-artha-works" aria-labelledby="how-artha-works-title">
        <div className="how-artha-works__intro">
          <span className="section-kicker">A simpler way to shop</span>
          <h2 id="how-artha-works-title">From a thought to a shortlist.</h2>
          <p>Start with your voice. Artha helps you compare the details before you choose a store.</p>
        </div>
        <ol className="how-artha-works__steps">
          {steps.map((step) => (
            <li className="how-artha-works__step" key={step.number}>
              <span className="how-artha-works__number" aria-hidden="true">{step.number}</span>
              <div className="how-artha-works__copy">
                <h3>{step.title}</h3>
                <p>{step.detail}</p>
              </div>
            </li>
          ))}
        </ol>
        <aside className="how-artha-works__trust">
          <strong>Clear research, your call.</strong>
          <span>Prices and stock can change. Confirm the final details with the retailer before you buy.</span>
          <button type="button" className="text-button" onClick={startBrief}>
            Try voice shopping <Icon name="arrow" size={15} />
          </button>
        </aside>
      </section>

      <footer className="artha-editorial-footer" aria-label="Artha footer and quick navigation">
        <div className="artha-editorial-footer__top">
          <div className="artha-editorial-footer__cta-block">
            <span className="artha-editorial-footer__annotation">A little more thought in every buy.</span>
            <h2 className="artha-editorial-footer__invitation">Find your next favourite.</h2>
            <p className="artha-editorial-footer__disclaimer">Compare the evidence, then buy directly from the retailer.</p>
          </div>
          <button type="button" className="stamp-action-button stamp-action-button--lime" onClick={startBrief}>
            <span className="stamp-action-button__label">Start with your voice</span>
            <Icon name="arrow" size={18} />
          </button>
        </div>
        {onNavigate ? (
          <nav className="artha-editorial-footer__nav" aria-label="Footer navigation">
            {[
              { id: 'discover', label: 'Discover' },
              { id: 'taste-graph', label: 'Your style' },
              { id: 'saved', label: 'Saved' },
              { id: 'plans', label: 'Plans' },
              { id: 'orders', label: 'Orders' },
              { id: 'usage', label: 'Usage' },
            ].map((item) => (
              <button type="button" key={item.id} className="artha-editorial-footer__nav-link" onClick={() => onNavigate(item.id)}>
                <span>{item.label}</span><Icon name="arrow" size={14} />
              </button>
            ))}
          </nav>
        ) : null}
        <div className="artha-editorial-footer__wordmark-wrap" aria-hidden="true">
          <div className="artha-editorial-footer__wordmark">ARTHA</div>
        </div>
      </footer>
    </div>
  );
}
