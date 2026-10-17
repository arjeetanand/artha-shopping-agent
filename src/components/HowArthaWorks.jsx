import React from 'react';

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

export function HowArthaWorks() {
  return (
    <section id="how-artha-works" className="how-artha-works" aria-labelledby="how-artha-works-title">
      <div className="how-artha-works__intro">
        <span className="section-kicker">The research, step by step</span>
        <h2 id="how-artha-works-title">From your brief to a clearer choice.</h2>
        <p>Start with a brief, reference image, or product/style link. Artha researches options; you review the evidence and choose where to buy.</p>
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
          <span><b>Evidence checked</b> meets Artha’s checks</span>
          <span><b>Verify first</b> some details are unknown</span>
          <span><b>No safe fit</b> nothing clears the requirements</span>
        </div>
      </aside>
    </section>
  );
}
