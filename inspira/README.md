# INSPIRA — AI Purchase Agent

“See it. Want it. Let AI shop it.”

INSPIRA is a hackathon-ready React/Vite frontend paired with a Make.com orchestration specification. The product is intentionally more than a recommendation chatbot: it turns an image or natural-language brief into structured requirements, applies deterministic hard constraints, ranks valid options, pauses at an explicit approval gate, creates a simulated order, and tracks status changes.

## Run the complete local app

```bash
cd inspira
npm install
npm run dev
```

Open the printed localhost URL. `npm run dev` runs the Vite frontend and the local API gateway together. Click **Use a demo inspiration**, then follow the journey:

1. AI understanding
2. Constraint-checked recommendations
3. Select a bundle
4. Confirm simulated purchase
5. Open tracking and advance the demo status

The local API persists sessions, requirements, pending approvals, orders, and order events in `server/data/state.json`. The deterministic engine in `src/lib/demoEngine.js` keeps results repeatable and does not require API keys, payment details, or a live commerce system.

For a production-style local run:

```bash
npm run build
npm start
```

Then open `http://127.0.0.1:8787`.

## Connect Make.com

1. Copy `.env.example` to `.env.local`.
2. Set `VITE_MAKE_GATEWAY_URL` to the URL of `PA_01_User_Request_Gateway`.
3. Configure the scenarios described in [`docs/MAKE_IMPLEMENTATION.md`](./docs/MAKE_IMPLEMENTATION.md).
4. Restart Vite.

The frontend sends only the request contract. AI/provider connections, API keys, Data Stores, hard constraint calculations, purchase verification, and notifications stay in Make when the remote URL is configured. If the variable is blank, the local gateway is used. Set `VITE_GATEWAY_MODE=demo` only if you explicitly want the original in-browser fallback.

## Project map

```text
src/App.jsx                 UI states and user journey
src/lib/demoEngine.js       deterministic catalog, filters, scoring, mock orders
src/lib/gateway.js          optional Make webhook adapter
server/api.mjs              local API gateway and persistence
server/index.mjs            production static server + API
server/data/state.json      runtime persistence (gitignored)
public/assets/inspira-hero.png  generated inspiration-board hero asset
docs/MAKE_IMPLEMENTATION.md Make scenarios, schemas, prompts, filters, tests
make/inspira-scenario-spec.json account-neutral scenario blueprint/spec
```

## Important demo boundaries

- Prices, shipping, seller reliability, delivery dates, and order tracking are explicitly simulated in local demo mode.
- No real payment information is collected or stored.
- The frontend never claims that the demo order is a real-world purchase.
- A recommendation is not approval. The order state only changes after **Confirm simulated purchase**.

## Visual QA

The interface is built with a warm editorial commerce direction: paper background, ink type, terracotta intent accent, sage operational status, and an image-led inspiration board. The core path is responsive and has been checked in the in-app browser at desktop and mobile viewport sizes.
