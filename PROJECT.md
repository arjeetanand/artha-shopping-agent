# Artha — product and UI design brief

> A portable brief for a designer or UI builder. Upload this file or paste its final prompt into your design tool. Based on the local project on 17 October 2026. This document describes the product and proposes a coherent visual handoff; it does not change the running app.

## 1. What I am building

**Artha is a personal shopping research assistant that helps people find what fits and understand why.**

A shopper describes what they need, adds a reference image or product/social-post link, sets a budget and delivery context, and receives a researched shortlist. Artha compares retailer options, explains trade-offs, exposes the evidence behind its recommendations, and helps the shopper save a purchase plan and continue to the retailer.

**Core promise:** “Find what fits. Know why.”

**Supporting copy:** “Tell Artha what you need. Compare real retailer options, prices, and trade-offs in one thoughtful shortlist.”

The experience should feel like a thoughtful personal shopper with a research notebook: stylish, calm, helpful, and clear about uncertainty.

### Audience and context

- Design for shoppers comparing options across retailers, especially Indian shoppers using rupees, cities, and delivery pincodes.
- Current examples emphasize clothing and personal style; the underlying product supports broader shopping categories, including furniture.
- Users may arrive with a specific need, an inspiration image, or a social post they want to translate into shoppable options.
- Budget, size, color, occasion, stock, and delivery deadlines can matter as much as appearance.

### Example mission

“Find an office-ready neutral outfit under ₹18,000, in my size, delivered to Bangalore before my event.”

Artha should help the shopper understand what matches, what was checked, what remains uncertain, and which retailer to visit next.

## 2. Product scope and trust

| Capability | What the UI should communicate |
| --- | --- |
| Shopping brief | Accept natural language; surface extracted constraints for correction. |
| Reference image | Attach, preview, and remove an image. Current limit: 4 MB; PNG, JPEG, WebP, or GIF. Analysis depends on the configured model. |
| Product or social-post URL | Show the supplied reference and any extracted style context. Handle inaccessible links without claiming successful analysis. |
| Retailer research | Show source links, checked facts, and gaps in evidence. |
| Comparison | Compare price, variant, availability, delivery context, and reasons for fit. |
| Price history | Display recorded observations when available; otherwise say “No recorded price history yet.” |
| Saved picks | Let shoppers bookmark products and revisit them. Do not imply every local bookmark is synced to an account. |
| Purchase plans | Signed-in users can save private retailer handoffs. |
| Voice | Offer a focused conversation with a transcript, explicit call controls, and typed fallback. |
| Location | Keep typed location usable. Ask for browser location only after “Use my location.” Nearby-store context is not proof of inventory. |
| Orders | Existing delivery/return/refund tracking is a local development sandbox. Label it clearly. |
| Usage | A secondary view shows runtime and provider activity, with unknown/unmetered usage labeled honestly. |

**Real purchases happen on retailer websites.** Artha does not currently submit retailer orders or collect live payments. Never present a saved plan as a paid order, a nearby store as confirmed stock, or an estimated arrival as a delivery guarantee. A source link alone does not establish that every product claim is verified.

## 3. Primary journey

1. **Describe:** enter the shopping brief, with an optional image or link.
2. **Clarify:** review the budget, deadline, location, size, and style; answer missing questions.
3. **Research:** see meaningful progress as retailer sources and product claims are checked.
4. **Decide:** read a top recommendation with reasons, trade-offs, and unresolved questions.
5. **Compare:** inspect product cards or switch to a detailed comparison table.
6. **Shortlist:** select products, see the source-listed total, and save a purchase plan.
7. **Continue:** visit each retailer to confirm details and complete the purchase.

Voice can help users describe, refine, and question the shortlist throughout this journey.

## 4. Screens to design

These are existing views. Preserve their responsibilities when redesigning.

| View | Route | Main content | Main action |
| --- | --- | --- | --- |
| Discover | `/` | Hero, brief composer, research progress, decision, product grid/table, shortlist | Find options / refine search |
| Saved picks | `/saved` | Bookmarked products, retailer links, selection controls, empty state | Add to shortlist |
| Purchase plans | `/plans` | Saved plans, item totals, retailer breakdown, checkout handoffs | Continue to retailer |
| Orders & tracking | `/orders` | Clearly labeled sandbox orders and their lifecycle | View sandbox order |
| Usage & runtime | `/usage` | Usage totals, provider activity, runtime filters, errors | Refresh activity |

### Discover: first visit

- A recognizable Artha wordmark and simple navigation.
- Eyebrow: “A little more thought in every buy.”
- Hero: **“Find what fits. Know why.”**
- One short explanatory paragraph and an original editorial product collage.
- A prominent brief composer with a visible label, example input, and one primary action.
- Secondary controls: add image, add link, delivery location, and “Talk to Artha.”
- Optional constraints should be easy to expand without turning the entry point into a long form.
- Suggestion chips can use the current examples: neutral office outfit, linen overshirts, leather loafers, and relaxed weekend wear.
- Show an honest initial state before the first search; avoid filling the screen with invented live products.

### Discover: research and results

- Keep the user's brief and constraints available for editing.
- Present the seven internal stages as a readable trail: brief, location, search, evidence, research, analysis, decision. A compact four-step grouping is acceptable.
- Display actual working, complete, blocked, and error states. Do not invent percentages.
- Lead results with a clear recommendation and its strongest reason, then show alternatives.
- Keep shortlist totals and retailer handoffs nearby on desktop; use an unobtrusive plan bar on mobile.

### Product card

Reading order: product image → product name → retailer → price → delivery/variant context → reason for fit → evidence status → actions.

Actions: inspect evidence, select for the plan, bookmark, and open retailer. Selection and bookmarking are separate states. Missing price or delivery information must stay visible as unknown.

### Evidence drawer or sheet

Show checked price, source URL, checked time when available, variant match, delivery context, review sources, seller evidence, recorded price history, and unresolved questions. Keep “Open retailer” easy to reach. Product names and long source URLs must wrap safely.

### Voice drawer

Keep the transcript readable. Include start/end call, listening/thinking/speaking feedback, a typed input, and a clear close control. Explain microphone failure or unavailable speech recognition with a useful fallback. Avoid making the conversation depend on an animated orb.

### Supporting states

Design empty saved picks, signed-out purchase plans, sign-in sheet, permission denied, invalid image, blocked reference URL, slow research, partial evidence, no matches, retryable error, and saved-plan confirmation. Sandbox checkout and tracking must remain visibly separate from real retailer handoffs.

## 5. Recommended visual direction

**Warm editorial commerce:** an independent style magazine meets a useful shopping research desk.

Use warm paper, forest navigation, terracotta actions, generous whitespace, expressive serif headlines, clean UI typography, and product photography with room to breathe. The interface should feel curated and tactile, with facts easy to scan.

Use thin rules, restrained shadows, small evidence labels, and occasional receipt or notebook details. Keep product facts and the brief more prominent than decorative art. Avoid dense dashboard chrome, neon gradients, continuous background motion, and excessive floating glass panels.

### Relationship to existing styling

The latest `Editorial storefront refresh` token block in `src/styles.css` supplies the warm paper/forest/terracotta foundation below. `DESIGN.md` records an earlier coral/cobalt direction. **For a new UI exploration using this brief, use the warm storefront palette as the default.** The current stylesheet still contains older colors and some component-specific overrides; this brief is a target for consistency, not a claim that every current component already matches it. Preserve the accessibility and evidence principles in `DESIGN.md`.

## 6. Color palette

Foundation colors come from the latest storefront token block. Cobalt and confirmation green are existing supporting tokens; the error treatment below is a proposed semantic addition for the design brief.

| Role | Hex | Suggested token | Use |
| --- | --- | --- | --- |
| Warm canvas | `#F5F3ED` | `--bg-app` | Page background |
| Deeper paper | `#EBE8DE` | `--bg-deep` | Quiet section breaks |
| Card ivory | `#FFFEFA` | `--surface` | Cards, drawers, main inputs |
| Subtle paper | `#F1EFE8` | `--surface-subtle` | Input groups and quiet rows |
| Forest | `#1C3027` | `--rail-bg` | Navigation and strong brand surfaces |
| Light on forest | `#E9EEE7` | `--rail-text` | Navigation text |
| Terracotta | `#A94F32` | `--primary` | Main action and active emphasis |
| Terracotta hover | `#8E3F27` | `--primary-hover` | Hover and pressed emphasis |
| Dark ink | `#222A24` | `--ink` | Headings, body, price |
| Secondary ink | `#596159` | `--ink-secondary` | Supporting text |
| Muted | `#7D8279` | `--muted` | Decorative or nonessential metadata; check contrast before text use |
| Border | `#E5E1D7` | `--line` | Dividers and card edges |
| Cobalt | `#2D5BD1` | `--accent-blue` | Source links and focus indicators |
| Confirmation | `#287E5D` | `--emerald` | Completed checks, accompanied by text |
| Error ink, proposed | `#B42318` | `--danger` | Errors on a light surface |
| Error paper, proposed | `#FEF3F2` | `--danger-soft` | Error message background |

Use roughly 80% light neutrals, 15% forest/ink, and 5% accent as a composition guide. Color must not be the only signal for selection, verification, warnings, or errors. Use dark ink for long copy and validate actual foreground/background combinations before implementation.

## 7. Typography, spacing, and shape

| Role | Typeface | Suggested size |
| --- | --- | --- |
| Hero and editorial emphasis | Instrument Serif | 64–88px desktop; 40–52px mobile |
| Section titles and UI headings | Plus Jakarta Sans | 24–36px |
| Body and forms | Plus Jakarta Sans | 16px minimum, line height around 1.5 |
| Buttons and product facts | Plus Jakarta Sans | 14–16px |
| Evidence labels and timestamps | System monospace, sparingly | 12–13px |

Use the serif for a deliberate editorial moment, with the sans for controls, facts, and longer reading. Avoid tiny all-caps labels for essential information.

- Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64, 96px.
- Functional panel radius: 10–14px. Pills are for compact chips and status labels.
- Borders: generally 1px. Shadows: shallow and infrequent.
- Images: consistent frames, neutral backgrounds, contained product photography, intentional crops for lifestyle images.
- Icons: one consistent outlined family; pair unfamiliar icons with text.

## 8. Layout and interaction

- **Desktop:** approximately 218px navigation rail, flexible main workspace, generous reading width, and a nearby shortlist panel. Use two or three product columns when space supports readable cards.
- **Tablet:** reduce columns and move the plan below results when the side panel would compress product content.
- **Mobile:** compact header/menu, single-column flow, full-width cards, and a shortlist bar that never hides controls. Keep Usage secondary.
- Design at 375, 768, 1024, and 1440px; accommodate 320px and browser zoom without clipped forms or page-wide horizontal scrolling.
- Comparison tables may scroll within a clearly labeled region; preserve a readable card alternative.
- Make touch targets at least 44 × 44px. Give inputs visible labels and local validation messages.
- Use semantic controls, visible keyboard focus, accessible drawer focus management, and meaningful image descriptions.
- Aim for at least 4.5:1 contrast for normal text and 3:1 for large text and essential control boundaries.
- Use 150–220ms feedback for small interactions and occasional 300–500ms section reveals. Respect reduced motion and never delay input for animation.

These layout and accessibility details are design guidance grounded in the existing flow; the local design-search database did not produce a suitable product-specific match.

## 9. Visual references and resources

Treat the following as a moodboard and study prompts, not templates to copy. Reference sites can change; the interpretation below is a proposed direction for Artha, not a full visual audit of their current pages.

| Reference | Study prompt for Artha |
| --- | --- |
| [SayBriefly](https://saybriefly.com/) | Existing project reference: study the progression from a strong promise to workflow explanation and product proof. Apply the pacing to shopping research. |
| [COS India](https://www.cos.com/en-in) | Explore a restrained fashion-commerce direction: give product imagery room and keep surrounding UI quiet. |
| [Perplexity](https://www.perplexity.ai/) | Explore a research-entry direction: make asking a question and investigating sources feel straightforward. |
| [Instrument Serif on Google Fonts](https://fonts.google.com/specimen/Instrument+Serif) | Preview the editorial display face already configured in the app. |
| [Plus Jakarta Sans on Google Fonts](https://fonts.google.com/specimen/Plus+Jakarta+Sans) | Preview the UI face already configured in the app. |

Moodboard search phrases: “warm editorial ecommerce”, “forest green terracotta web design”, “fashion research workspace”, “paper texture product comparison”, and “serif shopping assistant”.

Use original artwork and permitted product imagery. Do not copy reference branding, screenshots, illustrations, or copy. Illustrative products in a prototype must be labeled demo data; avoid fabricated ratings, discounts, testimonials, or guaranteed delivery.

## 10. Ready-to-paste prompt for a UI builder

```text
Design a polished responsive web interface for Artha, a personal shopping
research assistant. Its promise is “Find what fits. Know why.”

Users describe a shopping need, add an optional image or product/social-post
link, and specify budget, delivery location, deadline, size, color, or style.
Artha researches retailer sources, explains trade-offs, recommends options,
and creates a shortlist with source evidence and retailer checkout handoffs.
Design for Indian shopping context with ₹ prices and delivery pincodes.
Fashion is the lead visual example, but support other shopping categories.

Create these existing views: Discover, Saved picks, Purchase plans,
Orders & tracking (clearly labeled local sandbox), and Usage & runtime.
Prioritize Discover in both empty and researched-results states, with an
evidence drawer, a voice conversation drawer, and a mobile shortlist bar.

Use warm editorial commerce: paper #F5F3ED, ivory cards #FFFEFA,
forest navigation #1C3027 with text #E9EEE7, terracotta actions #A94F32,
hover #8E3F27, ink #222A24, supporting text #596159, borders #E5E1D7,
cobalt source links #2D5BD1, and confirmation green #287E5D.
Use Instrument Serif for editorial display and Plus Jakarta Sans for UI.
Use generous whitespace, fine rules, restrained shadows, 10–14px panel
corners, original editorial product art, and readable factual product cards.

Hero: “Find what fits. Know why.”
Supporting text: “Tell Artha what you need. Compare real retailer options,
prices, and trade-offs in one thoughtful shortlist.”
Primary task: enter a brief and find options. Secondary controls: image,
link, location, and Talk to Artha. Keep optional constraints expandable.

After search, show meaningful research progress, a recommendation with
reasons and uncertainties, product cards/table, and a nearby shortlist.
Product cards show image, name, retailer, price, delivery/variant context,
reason for fit, evidence status, inspect, bookmark, select, and retailer link.
The evidence sheet includes checked facts, source links, recorded price
history when available, and open questions. Voice has a transcript,
start/end controls, state feedback, and a typed fallback.

Keep real payments and fulfillment on retailer sites. Never imply a saved
plan is paid, a retailer link verifies every claim, or delivery is guaranteed.
Include loading, clarification, no results, partial evidence, error,
signed-out, permission-denied, and empty saved-list states. Label all demo
products and local sandbox orders honestly.

Use SayBriefly as a study reference for storytelling, COS for a possible
fashion-commerce direction, and Perplexity for a research-entry direction.
Build an original Artha identity. Do not copy their assets or branding.

Support mobile, tablet, desktop, keyboard navigation, visible focus,
44px touch targets, accessible contrast, reduced motion, and stable layouts.
Avoid dense dashboard chrome, tiny text, decorative loading percentages,
neon gradients, and motion that interferes with shopping.

For a coded prototype, use the existing React + Vite structure and reusable
components. Keep provider credentials on the backend. Present all required
states without inventing backend capabilities or adding unrelated features.
```

## 11. Handoff checklist

- A first-time visitor can explain Artha before scrolling.
- The brief, evidence, and retailer handoff remain easy to find.
- Cards distinguish selection, bookmarks, and evidence status.
- Uncertainty, unavailable history, and missing delivery details are readable.
- Desktop and mobile preserve the same shopping journey.
- Real retailer checkout and the development sandbox are unambiguous.
- Color, typography, spacing, focus, and motion are consistent across states.

## Repository context

Product behavior was reviewed in `README.md`, `src/App.jsx`, `src/data.js`, and `src/components/SocialThemeBar.jsx`; the palette foundation comes from `src/styles.css`. `DESIGN.md` provides earlier editorial and accessibility guidance. The stack is React + Vite, a Python API, and SQLite, with configurable research, AI, authentication, and voice providers. Provider availability is configuration-dependent, so the UI must support unavailable and fallback states.
