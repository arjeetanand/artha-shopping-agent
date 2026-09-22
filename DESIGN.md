# Artha design direction — editorial commerce, not a clone

## Purpose

This file is the visual and motion contract for Artha. It takes inspiration from the pacing, tactility, and confidence of [SayBriefly](https://saybriefly.com/?ref=a1.gallery), then translates those traits into an original, evidence-led shopping experience.

The aim is not to reproduce SayBriefly. Do not copy its name, logo, copy, illustrations, product screenshots, video, yellow paper tab, or source assets. Use this document to recreate the feeling: big editorial hierarchy, a tangible research trail, motion with a point of view, and product proof that feels alive.

## The decision

Artha should feel like a sharp independent magazine editor has built a personal shopping researcher:

- Quiet, warm paper surfaces make product evidence easy to scan.
- Oversized type creates a clear point of view without turning shopping into a generic dashboard.
- Coral signals action and discovery; cobalt signals source evidence; green confirms a completed or trustworthy state.
- Real retailer evidence and product imagery are the hero assets. Decorative motion supports the task; it never obscures it.
- The user stays in control: Artha explains the recommendation, exposes source evidence, and never treats an inference as a fact.

The current implementation already begins this direction. The canonical CSS layer starts at the “Editorial motion refresh” comment in src/styles.css, followed by the “Motion system: editorial, responsive, and task-safe” layer. Earlier full-theme cascades in that file are legacy context, not a second design system to extend.

## What the reference teaches us

The source is effective because it combines:

1. A sticky, translucent navigation ribbon with a strong branded silhouette.
2. A small label, oversized headline, restrained paragraph, and one obvious call to action.
3. Long, chapter-like storytelling: diagram, product proof, impact claim, then the next feature.
4. Hand-made-looking flourishes beside credible product UI screenshots.
5. Large, calm transitions instead of constant micro-animation.

Artha should improve on that formula:

- Lead with a live shopping brief and visible evidence, not a marketing-video preloader.
- Use Artha’s black ink, coral, cobalt, and paper palette—not the reference’s forest/yellow/lavender identity.
- Make all controls keyboard-operable, focus-visible, and large enough to use on touch.
- Keep every animation interruptible and provide a complete reduced-motion version.

## Design principles

### 1. Research is the product

The main visual is the result of a user’s brief: curated products, live availability, source links, delivery details, trade-offs, and a plan. Avoid decorative placeholders where a useful source, product image, or short explanation can appear.

### 2. Editorial hierarchy beats dashboard density

Use a strong headline, generous blank space, one primary action, and clear chapter breaks. Let the shopping workflow unfold in a deliberate order:

1. Brief
2. Research progress
3. Top recommendation
4. Product evidence
5. Comparison and purchase plan

### 3. Tactile, not fake

Paper-like surfaces, a slightly rotated hero frame, ticket labels, stamps, rules, and subtle image grain are welcome. They must use original assets or CSS textures created for Artha; never lift branded drawings or screenshots from the reference.

### 4. Motion explains change

Animation can reveal a new chapter, show research advancing, or focus attention on a recommendation. It must not delay input, hide an error, move a target while it is being used, or replay aggressively.

### 5. Evidence earns the visual drama

A product card may be beautiful, but its retailer, price, delivery context, source status, and reason-for-fit remain more important than its decoration.

## Visual language

### Palette

Use the existing semantic tokens; do not scatter raw hex values through components.

| Role | Token | Value | Use |
| --- | --- | --- | --- |
| Canvas | --bg-app | #FFFFFF | Main application background |
| Paper / quiet section | --bg-deep | #F5F4F0 | Editorial breaks and restrained framing |
| Subtle surface | --surface-subtle | #F8F7F3 | Inputs, delivery rows, quiet utility areas |
| Ink | --ink | #141414 | Primary text, rules, critical controls |
| Secondary ink | --ink-secondary | #454540 | Supporting copy |
| Coral | --primary / --coral | #EE5A3B | Primary action, active research, lively emphasis |
| Cobalt | --accent-blue | #2D5BD1 | Evidence, source-linked states, secondary contrast |
| Confirmation green | --emerald | #287E5D | Complete / trustworthy states only |
| Warning paper | --coral-soft | #FFF0EB | Clarifications and opportunity notes |

The coral/cobalt pairing is deliberately different from the reference. It makes Artha recognizable at a glance while retaining the warm, graphic energy that made the reference compelling.

### Typography

| Role | Typeface | Rules |
| --- | --- | --- |
| Editorial display | Instrument Serif | Use for the wordmark and occasional large editorial emphasis. Keep it sparse. |
| Product/UI sans | Plus Jakarta Sans | Use for headings, body, controls, data, and all transactional copy. |
| Provenance label | system monospace, only when useful | Use for short source labels, timestamps, and internal-style annotations; never for paragraphs. |

Typography should be assertive but readable:

- Hero: three to five short lines maximum; use a serif emphasis only for a deliberate phrase.
- Section title: one idea, no more than two lines on desktop.
- Supporting paragraph: 16–18px, comfortable line height, approximately 60–75 characters per line.
- Labels and metadata: 11–12px with clear contrast; do not use tiny gray text as the only way to convey a decision.

### Shape, lines, and depth

- Prefer a 1px ink or translucent-ink rule to a heavy card border.
- Use near-square editorial frames, modest 10–14px radii for functional panels, and pills only for filters, labels, and lightweight actions.
- Let the hero visual have a slight rotation and offset ticket/stamp. Functional content must remain straight and scannable.
- Use shadows sparingly: shallow black shadow for product cards, a stronger shadow only for a floating drawer, sheet, or primary decision.

## Layout and responsive behavior

### Desktop: 821px and above

- Keep the 172px sticky navigation rail; it is the app’s equivalent of the reference’s persistent ribbon.
- Keep the main column readable rather than full-bleed. Let large editorial moments break that rhythm intentionally.
- Hero is a two-column composition: copy on the left, original editorial product visual on the right.
- Research results use a grid of product cards, then a persistent or nearby plan/summary panel.
- Reuse the reference’s visual alternation: quiet copy, evidence-rich visual, quiet copy, then the next evidence-rich visual.

### Mobile: 820px and below

- Replace the rail with a compact header and accessible menu/drawer.
- Collapse hero copy and visual into a single sequence; never rely on hover or a fine pointer.
- Make product panels full width and stack research details in reading order.
- Keep primary actions at least 44 by 44 CSS pixels and ensure text does not depend on horizontal scrolling.
- Preserve useful sticky affordances only when they do not cover the brief, results, or checkout controls.

The reference succeeds on mobile by simplifying its nav and stacking the desktop story. Artha should do the same, while keeping the brief and the selected products easier to reach than decorative material.

## Component contracts

| Surface | Existing implementation | Required direction |
| --- | --- | --- |
| Navigation | .nav-rail, mobile header | Clean editorial rail, active item indicated by a coral rule; do not turn it into a dense SaaS sidebar. |
| Hero | HeroVisual and .hero-copy | Oversized “Good buys. Better reasons.” hierarchy, a real original product/editorial image, offset ticket and source stamp. |
| Brief composer | .composer | The calm task entry point. Use paper surface, strong focus line, concise chips, and plain-language validation. |
| Research progress | AgentStrip | A visible linear research trail with states: queued, working, complete, blocked. Progress must reflect real state, not a decorative loop. |
| Top recommendation | decision-banner | One decisive recommendation with evidence, price context, and an inspect action—not a vague AI verdict. |
| Product card | ProductCard and .product-card | Image first, then retail facts and the “why this fits” reason. Keep selection obvious without hiding details. |
| Plan / summary | summary panel and mobile plan bar | Treat it like a concise editor’s shortlist. Preserve totals, retailer choices, and checkout context. |
| Voice interaction | TalkDrawer | A focused conversational workspace with trapped focus, clear close action, and no unnecessary ambient motion. |
| Feedback | toast, errors, clarification notes | Signal state using text, icon, and color together. Errors must stay visible until resolved or dismissed. |

## Motion specification

### Motion tokens

Use the existing values as the source of truth:

~~~css
--motion-editorial: cubic-bezier(0.16, 1, 0.3, 1);
--motion-spring: cubic-bezier(0.22, 1.18, 0.36, 1);
--motion-fast: 180ms;
--motion-base: 520ms;
--motion-slow: 900ms;
~~~

### Required behaviors

| Moment | Behavior | Timing |
| --- | --- | --- |
| Initial hero copy | Reveal words upward with a small 3D rotation; stagger each word without delaying reading. | 740ms, 82ms word stagger |
| Hero image | Slight entrance, halo drift, restrained grid movement, and frame shine. Fine-pointer devices can tilt it a maximum of about 4–5 degrees. | 340–1200ms, slow drift only |
| Composer focus | Grow a coral focus rule across the input. | 180–500ms |
| Research stages | Enter in sequence; completed stages have one springy confirmation; working stage gets a calm ring. | 520ms, 70ms stage stagger |
| Recommendation | Fade/raise once when a new answer is ready. | 680ms |
| Product cards | Raise into view sequentially from below. Hover may add depth, but selection and source controls remain stable. | 720ms, 90ms card stagger |
| Mobile plan bar | Enter upward once when there are selected products. | 520ms |
| Drawer / sheet | Fade and slide from its physical origin; move focus only after it is usable. | 180–520ms |

### Reference patterns worth adapting

The source uses 0.9s chapter reveals with a soft decelerating curve, 120ms cascades, a 700ms illustrated carousel, 500ms screenshot crossfades, and a mobile menu that combines height, fade, and upward movement. Adapt the intent, not the implementation:

- Use chapter reveals only for meaningful groups, not every label.
- If a carousel is added, give it explicit previous/next controls, pause it on focus/hover, and never make it the only place to read a feature.
- If a desktop visual becomes sticky during a story, switch to normal stacked reading order on mobile.
- Do not add the reference’s preloader. Artha should show its useful UI immediately.

### Motion safety rules

- Respect prefers-reduced-motion: reduce: remove entrance, drift, shine, tilt, and spring effects; preserve all state changes instantly.
- Run pointer tilt only for a fine pointer and never make it required to understand the image.
- Do not animate layout height while a form control has focus, except for an explicitly opened dialog/drawer.
- Do not make loading depend on an infinite animation. Show a label such as “Checking retailer availability” alongside progress.
- Keep hover-only affordances additive. Touch users must receive the same actions by default.

## Original asset direction

Create an Artha-specific visual kit instead of importing anything from the reference:

- Original collage or editorial outfit/product image for the hero.
- Abstract retailer-receipt, map-pin, or evidence-thread motifs for tickets and stamps.
- Product thumbnails from permitted retailer/source data, with a neutral fallback image when no source image is available.
- A subtle, low-contrast grain or paper texture created locally, not a copied source SVG.
- Small reusable status icons that remain legible at 16px.

Never hotlink assets from the reference website. Treat its assets as brand-specific even when they are technically discoverable in the browser.

## Accessibility and performance are non-negotiable

- Keep the existing live-region, focus-trap, pointer capability, and reduced-motion protections.
- Use semantic buttons for selection and carousel controls; do not use a clickable div.
- Provide a visible focus ring that is distinguishable from a selected state.
- Maintain normal text contrast of at least 4.5:1; check coral and cobalt labels on paper surfaces before shipping.
- Give every meaningful product image a useful alt description. Decorative ticket, stamp, and grain layers should be hidden from assistive technology.
- Reserve image space to prevent layout shift, lazy-load below-the-fold media, and limit large animated layers to transforms and opacity.
- Keep the first useful brief/composer content immediately usable even if product art or external images are slow.

## Build order

1. Preserve the functional shopping flow and current accessible interactions.
2. Consolidate the canonical tokens and motion layer in src/styles.css; do not append another full theme cascade.
3. Stabilize the hero, composer, research strip, decision banner, product cards, plan, and talk drawer against this document.
4. Add original art only after its intended frame, crop, and responsive behavior are known.
5. Test desktop, mobile, keyboard-only, reduced-motion, loading, empty, error, and long-product-name states.

## Acceptance checklist

- [ ] A first-time visitor understands what Artha does before they scroll.
- [ ] A shopper can submit a brief, inspect evidence, select products, and view a plan without losing context.
- [ ] Coral, cobalt, and green retain their semantic roles consistently.
- [ ] No SayBriefly branding, copy, screenshots, illustrations, video, or source assets are present.
- [ ] Motion explains an event and can be interrupted; reduced-motion mode is complete and calm.
- [ ] Keyboard focus, menu/drawer behavior, errors, and product selection are visible and operable.
- [ ] Desktop rail and mobile header are both navigable and do not consume excessive space.
- [ ] Product facts and source evidence remain more prominent than decorative treatment.
- [ ] The page is visually coherent because the final editorial-motion layer, not a legacy cascade, controls the result.

## Implementation hand-off

When using this file for a build task, give the implementer this constraint:

> Implement the existing Artha shopping flow according to DESIGN.md. Use the SayBriefly reference only for high-level pacing and tactile editorial energy. Keep Artha’s original ink/coral/cobalt/paper identity, all accessible behavior, real evidence states, and reduced-motion support. Do not copy source branding, text, illustrations, screenshots, or assets.
