# Artha — source-linked purchase research

Artha turns a natural-language shopping brief, reference image, or product/post URL into a source-linked purchase plan. It extracts the constraints, searches live retailer sources through Anakin, normalizes the evidence, applies budget and delivery constraints, and lets a signed-in user save private retailer handoffs.

This is a research and retailer handoff flow with a clearly labeled local order sandbox. Artha does not submit retailer orders or collect live payments. Even if Razorpay credentials are present, new in-app charges stay disabled until retailer fulfillment is connected; shoppers complete real purchases at the retailer.

## What runs where

- **React + Vite** provides the responsive web interface.
- **Python standard library API** handles provider credentials, Google OAuth, workflow orchestration, and SQLite persistence.
- **Anakin** supplies live source search and optional URL extraction.
- **Local fixture catalog** is available only when `SHOPPINGHELP_SEARCH_MODE=fixture`; it keeps development and end-to-end tests deterministic without sending test briefs to a third party.
- **Ollama** is selected by default in local development for brief extraction.
- **Gemini** is selected by default when `APP_ENV=production`; it can analyze reference images as well as text.
- **Kokoro** is the preferred local voice when the optional local voice environment is installed, with browser SpeechSynthesis as a fallback. **ElevenLabs** is selected by default in production.
- **Usage & runtime** keeps a persistent SQLite ledger of provider-reported AI tokens, plus clearly marked unmetered Anakin search and server voice activity. The UI can filter the ledger by local or production runtime without pretending to switch the running deployment.

## Run locally

The easiest way to start both the Python backend and the Vite frontend together:

```bash
./run.sh
# or: npm start
```

This single command:
1. Automatically detects `.venv` (or falls back to `python3`).
2. Creates `.env` from `.env.example` if not present.
3. Installs frontend dependencies if `node_modules/` is missing.
4. Reads configured ports from `.env`.
5. Starts the backend, waits for health check confirmation, and starts Vite.
6. Gracefully shuts down both processes when you press `Ctrl+C`.

### Manual / Separate Terminals

If you prefer running services in separate terminals:

```bash
# Terminal 1: Backend
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-kokoro.txt  # optional local voice
SHOPPINGHELP_PORT=8001 .venv/bin/python backend/server.py

# Terminal 2: Frontend
SHOPPINGHELP_API_TARGET=http://127.0.0.1:8001 npm run dev -- --port 5176
```

Open the Vite URL printed by the frontend. The app proxies `/api` to the Python server, so API keys never reach the browser.

The first Kokoro warm-up uses the cached `hexgrad/Kokoro-82M` model when
available; if the optional dependency is omitted, the app reports the missing
local dependency and falls back to browser speech in development.

If port `8000` is already in use, choose another port consistently:

```bash
SHOPPINGHELP_PORT=8001 npm run backend
SHOPPINGHELP_API_TARGET=http://127.0.0.1:8001 npm run dev -- --port 5176
```

Check the provider routing without exposing credentials:

```bash
curl http://127.0.0.1:8000/api/health
```

### Local end-to-end smoke test

Run the complete deterministic flow against a temporary server and SQLite database:

```bash
npm run test:e2e
```

The test covers the example brief, constraint-aware ranking, seven-stage workflow, server-side checkout-price verification, order creation, delivery progression, return, refund, and cleanup. It uses `SHOPPINGHELP_SEARCH_MODE=fixture` and never touches the developer database or a payment provider.

The offline payment contract can be exercised without credentials or network calls:

```bash
npm run test:payments
```

The OAuth state/PKCE and redirect-safety contract can also be checked offline:

```bash
npm run test:auth
```

The browser voice-call loop can be checked with `npm run test:voice` after installing Playwright Chromium. To use an existing Chrome binary, set `SHOPPINGHELP_CHROME_PATH` to its executable path.

The permissioned location adapter can be exercised offline with mocked Maps responses; it verifies nearby-store parsing and coordinate non-persistence:

```bash
npm run test:location
```

## Configure providers

Copy the names from `.env.example` into `.env`; keep `.env` out of source control.

### Google sign-in

Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI`. Register the redirect URI **exactly** in the Google Cloud OAuth web-client configuration, for example:

```text
http://127.0.0.1:8000/api/auth/google/callback
```

The flow uses authorization-code OAuth with PKCE. It verifies the Google user identity, creates a server-side session, stores only a hash of the session token in SQLite, and discards Google access tokens after identity verification.

### Search and URL extraction

Set `ANAKIN_API_KEY`. The browser calls the Python API; only Python calls Anakin. Search results are marked **Live source** and keep their source URLs. A pasted product or post URL is first sent through Anakin's URL scraper and contributes context to the retailer search.

### Delivery location

The composer keeps the typed delivery city as the source of truth. **Use my location** requests approximate browser coordinates only after an explicit click; coordinates are validated, used for optional geocoding and nearby-store context, and never persisted. In production, set `GOOGLE_MAPS_API_KEY` and leave `GOOGLE_MAPS_PLACES_ENABLED=1` if you want Google Maps to resolve a permissioned location into a delivery city and return nearby store signals relevant to the category. The UI labels that context as approximate and does not treat a nearby store as proof of inventory. Set `GOOGLE_MAPS_PLACES_ENABLED=0` to keep geocoding without Places calls. If permission is denied or Maps is unavailable, Artha keeps the city the shopper typed.

### AI routing and reference images

```dotenv
AI_PROVIDER=auto
OLLAMA_MODEL=llama3.2:3b
OLLAMA_VISION_MODEL=llama3.2-vision
GEMINI_MODEL=gemini-2.5-flash
```

`AI_PROVIDER=auto` uses Ollama for development and Gemini for production. Set `AI_PROVIDER=gemini` to use Gemini explicitly, or `AI_PROVIDER=ollama` to force local Ollama.

Reference images are limited to PNG, JPEG, WebP, or GIF and 4 MB. They are sent only for the active brief-extraction request and are never written to SQLite. Local image understanding requires a vision-capable `OLLAMA_VISION_MODEL`; production Gemini handles inline image analysis. If a model returns no usable structured brief, Artha labels its typed-rule fallback; it does not substitute fixture products for live research.

### Voice

`VOICE_PROVIDER=auto` uses `LOCAL_VOICE_PROVIDER` during development and ElevenLabs in production. Set `LOCAL_VOICE_PROVIDER=kokoro` for the local studio voice, or `browser` for zero-install development. For production, set `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, and optionally `ELEVENLABS_MODEL_ID`. The ElevenLabs key remains on the Python server; only audio bytes return to the browser. If server voice fails, the call visibly switches to browser speech while keeping the answer in the transcript.

The **Start call** control in Talk to Artha uses the browser's SpeechRecognition microphone permission, submits each spoken turn to the same research and refinement flow as typed requests, reads the answer through the configured voice service, and listens for the next turn. Browsers without SpeechRecognition retain typed chat. The call transcript remains visible and **End call** stops listening and playback.

The local Kokoro configuration is:

```dotenv
VOICE_PROVIDER=auto
LOCAL_VOICE_PROVIDER=kokoro
KOKORO_LANG_CODE=a
KOKORO_VOICE=af_heart
KOKORO_SPEED=0.98
KOKORO_DEVICE=auto
```

### Payments

`PAYMENT_PROVIDER=sandbox` enables the clearly labeled development tracker without charging anyone. Production checkout is a retailer handoff. `/api/payments/order` returns 503, including when Razorpay credentials are present, because Artha has no retailer fulfillment integration. `/api/payments/verify` remains available only to settle historical attempts that were initiated before this gate.

## Workflow

1. **Brief agent** extracts category, quantity, preferred brand, budget, location/pincode, delivery window, color, size, fabric, must-have specifications, and visual/style cues. Written durations such as “three days” are normalized safely.
2. **Clarification checkpoint** pauses before retailer discovery when a decision-critical constraint is missing or ambiguous. The response carries structured questions and can be resumed through the follow-up endpoint without losing the brief.
3. **Location agent** uses the typed city/pincode or an explicitly permissioned browser location, with optional Google Maps geocoding and nearby-store context; raw coordinates are never persisted.
4. **Search agent** calls Anakin for retailer sources, and optionally scrapes a pasted URL for reference context. Provider-neutral retailer and delivery contracts live in `backend/retailers.py`; dedicated marketplace adapters can be added without changing ranking or UI code.
5. **Evidence agent** normalizes source-linked fields and labels unknown delivery, stock, variant, and price information as needing retailer confirmation.
6. **Research agent** checks up to six discovery pages, then up to four exact-item pages from other retailer sites when product identity is strong enough. It uses direct-page details ahead of search snippets, records price mismatches, and keeps empty or failed checks visibly unverified. Fixture mode uses deterministic catalog evidence without network calls.
7. **Analysis agent** cross-checks review-source consistency and current-vs-history price signals when those fields are available, explicitly preserving unknowns.
8. **Decision agent** ranks by fit, seller signals, budget, delivery, stock, color, size, and evidence, then applies an evidence gate. It returns `buy_now`, `verify_before_buy`, or `no_safe_fit`; unknown or conflicting price, delivery, stock, color, or size can never produce `buy_now`.
9. **Purchase-plan service** persists only an authenticated user's selected, linked products in local SQLite.
10. **Order service** persists explicitly confirmed sandbox orders for local testing. Production purchases happen on retailer sites; historical signed payment attempts can still be reconciled, but new charges are blocked.

Each result also carries an evidence ledger when the source provides it: review-source samples and consistency signals, current-vs-history price context, seller/stock/delivery evidence, and explicit unknowns when those fields are unavailable. Select the shield action on a result to inspect that ledger before saving or checkout.

The price desk groups directly checked live pages across stores by a valid Product JSON-LD GTIN and matching known variant, or by brand, exact title, color, and size; otherwise each retailer URL has its own history. After finding a verified item with that strong identity, Artha makes one bounded search for the same item at other retailers. It shows the lowest price among matching offers checked in that search and stores timestamped INR observations in SQLite. Historical lows and trends reflect Artha's observations only. Fixture history is labeled demo data. Store prices can omit shipping, tax, variant availability, and delivery, so the recommended retailer may differ from the lowest item-price offer.

When a product just outside the budget still satisfies delivery and stock constraints, the result includes a clearly labeled **Worth a small stretch** opportunity. It never changes the selected plan automatically; the user can inspect that product's evidence before deciding.

Live searches can be started asynchronously with `POST /api/agent/search/jobs` and polled at `GET /api/agent/search/jobs/:job_id`. The job returns queued, working, complete, waiting, or failed stage snapshots while Anakin and parallel direct-page checks run, so the UI can keep the workflow visible instead of holding a blank request open.

When required details are missing, the search response uses `status: "needs_clarification"`, returns `intent.clarifications`, and contains no retailer shortlist. Send the user's answer to `POST /api/agent/refine` with the prior `search_id`, answer text, and edited mission. Artha loads the saved research on the server, starts discovery when the checkpoint has no products, and reuses completed evidence for soft follow-ups.

Refinement also accepts the edited `mission` object, so budget, deadline, pincode, size, color, occasion, and style changes reach the server. Changed delivery location, pincode, or requested color/size triggers fresh retailer research; other hard changes trigger it when the previous shortlist no longer fits.

`POST /api/agent/search` and `POST /api/agent/search/jobs` also accept an optional `mission` object: `{ occasion, arrive_by_date, budget, pincode, size, color, style }`. `arrive_by_date` is a date-only `YYYY-MM-DD` India deadline; the server derives its delivery window. The response stores the resolved fields at `intent.mission` and adds `intent.decision` with the decision status, recommended and optional fallback product IDs, reasons, blocking risks, and `checked_at`.

The displayed total includes shipping only when a direct retailer page confirms it. Unknown shipping, tax, and retailer-specific fees must be confirmed at retailer checkout.

## API surface

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Safe provider and environment status |
| `GET /api/auth/session` | Current authenticated user, if any |
| `GET /api/auth/google/start` | Start Google OAuth with PKCE |
| `GET /api/auth/google/callback` | Complete Google OAuth and create the session |
| `POST /api/auth/logout` | End the local session |
| `POST /api/agent/search` | Run the seven-stage brief → location → search → evidence → research → analysis → decision workflow |
| `POST /api/agent/search/jobs` | Start the same research workflow asynchronously and return a job id |
| `GET /api/agent/search/jobs/:job_id` | Poll workflow stage progress and read the completed result |
| `POST /api/agent/refine` | Apply a follow-up to a server-saved search; repeat discovery when delivery evidence or hard constraints require it |
| `GET /api/plans` | List the signed-in user's private purchase plans |
| `POST /api/plans` | Save a source-linked purchase plan after user selection |
| `GET /api/orders` | List the signed-in user's confirmed orders and tracking timelines |
| `GET /api/orders/:id` | Read one user-scoped order |
| `POST /api/orders` | Create an explicitly confirmed sandbox order or verified provider order |
| `POST /api/payments/order` | Reject new in-app charges until retailer fulfillment is connected |
| `POST /api/payments/verify` | Verify and reconcile a historical Razorpay attempt |
| `POST /api/orders/:id/cancel` | Cancel a cancellable sandbox order |
| `POST /api/orders/:id/advance` | Advance a sandbox order through delivery statuses for local tracker testing |
| `POST /api/orders/:id/return` | Record a sandbox return request after delivery |
| `POST /api/orders/:id/refund` | Record a sandbox refund state after a return request |
| `GET /api/usage?days=30&runtime=all` | View token totals, provider breakdowns, and recent activity; production requires Google sign-in |
| `GET /api/voice/status` | Selected voice provider and availability |
| `POST /api/voice/warm` | Warm the selected local Kokoro voice before playback |
| `POST /api/voice/speak` | Produce the summary audio or local-browser speech instruction |

## Data and safety notes

- SQLite stores searches, OAuth state, hashed sessions, users, user-scoped purchase plans, and provider usage events in `backend/shoppinghelp.sqlite3`.
- Usage events store counts and metadata only: provider, operation, model name, token counts when reported, character/byte counts for unmetered activity, runtime, status, and timestamp. Provider credentials are never written to the ledger.
- No Google OAuth token, payment credential, or reference-image bytes are persisted.
- The service cannot submit a retailer checkout, create a merchant order, or truthfully track a merchant order without a retailer integration that explicitly supports those actions. Razorpay payment authorization is separate from retailer fulfillment.
- In development, the local sandbox order flow is clearly labeled and never stores payment credentials or claims a merchant charge. Production rejects sandbox checkout until a real payment/merchant adapter is enabled.
- New Razorpay payment orders are blocked. Historical attempts are verified server-side with the signed `order_id|payment_id` callback; failed or replayed attempts do not create an order.
- Orders created from a search are rehydrated from the server-side verified search result, so a modified browser payload cannot change the catalog price or quantity at checkout.
- The development tracker can advance through delivery, return, and refund states for QA; production status changes must come from merchant webhooks or a supported order API.
- Live saved plans are therefore intentionally named **Ready for retailer checkout**, not paid orders or delivery tracking.
