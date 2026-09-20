# Artha — source-linked purchase research

Artha turns a natural-language shopping brief, reference image, or product/post URL into a source-linked purchase plan. It extracts the constraints, searches live retailer sources through Anakin, normalizes the evidence, applies budget and delivery constraints, and lets a signed-in user save private retailer handoffs.

This is a real research and handoff flow, not a simulated payment system. Artha never collects payment credentials, sends an order to a retailer, or claims that retailer checkout is complete. The user opens each saved retailer link and completes checkout on the retailer's own secure site.

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

The composer keeps the typed delivery city as the source of truth. **Use my location** requests approximate browser coordinates only after an explicit click; coordinates are validated, used for optional geocoding, and never persisted. In production, set `GOOGLE_MAPS_API_KEY` if you want Google Maps to resolve a permissioned location into a delivery city. If permission is denied or geocoding is unavailable, Artha keeps the city the shopper typed.

### AI routing and reference images

```dotenv
AI_PROVIDER=auto
OLLAMA_MODEL=llama3.2:3b
OLLAMA_VISION_MODEL=llama3.2-vision
GEMINI_MODEL=gemini-2.5-flash
```

`AI_PROVIDER=auto` uses Ollama for development and Gemini for production. Set `AI_PROVIDER=gemini` to use Gemini explicitly, or `AI_PROVIDER=ollama` to force local Ollama.

Reference images are limited to PNG, JPEG, WebP, or GIF and 4 MB. They are sent only for the active brief-extraction request and are never written to SQLite. Local image understanding requires a vision-capable `OLLAMA_VISION_MODEL`; production Gemini handles inline image analysis. If the selected provider cannot return a structured brief, the API reports the provider failure instead of fabricating a local/demo brief.

### Voice

`VOICE_PROVIDER=auto` uses `LOCAL_VOICE_PROVIDER` during development and ElevenLabs in production. Set `LOCAL_VOICE_PROVIDER=kokoro` for the local studio voice, or `browser` for zero-install development. For production, set `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, and optionally `ELEVENLABS_MODEL_ID`. The ElevenLabs key remains on the Python server; only audio bytes return to the browser. Production does not silently fall back to browser speech when ElevenLabs is missing.

The local Kokoro configuration is:

```dotenv
VOICE_PROVIDER=auto
LOCAL_VOICE_PROVIDER=kokoro
KOKORO_LANG_CODE=a
KOKORO_VOICE=af_heart
KOKORO_SPEED=0.98
KOKORO_DEVICE=auto
```

## Workflow

1. **Brief agent** extracts category, quantity, preferred brand, budget, location, delivery window, must-have specifications, and visual/style cues.
2. **Location agent** uses the typed city or an explicitly permissioned browser location, with optional Google Maps geocoding and no coordinate persistence.
3. **Search agent** calls Anakin for retailer sources, and optionally scrapes a pasted URL for reference context.
4. **Evidence agent** normalizes source-linked fields and labels unknown delivery, stock, and price information as needing retailer confirmation.
5. **Research agent** checks up to six returned live product pages in parallel through Anakin's URL scraper, fills only missing structured fields, records price mismatches, and keeps direct-page failures visibly unverified. Fixture mode uses its deterministic catalog evidence without network calls.
6. **Analysis agent** cross-checks review-source consistency and current-vs-history price signals when those fields are available, explicitly preserving unknowns.
7. **Decision agent** ranks by fit, seller signals, budget, delivery, stock, and evidence, and excludes products with a known constraint failure from the default plan. It calculates line totals for requested quantities instead of ranking on unit price alone.
8. **Purchase-plan service** persists only an authenticated user's selected, linked products in local SQLite.
9. **Order service** persists an explicitly confirmed sandbox order and tracking timeline in local SQLite. It is disabled in production until a real merchant/payment adapter is configured.

Each result also carries an evidence ledger when the source provides it: review-source samples and consistency signals, current-vs-history price context, seller/stock/delivery evidence, and explicit unknowns when those fields are unavailable. Select the shield action on a result to inspect that ledger before saving or checkout.

The known item subtotal deliberately excludes shipping, tax, and any retailer-specific fees that the live source does not verify. The user must confirm those values at checkout.

## API surface

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Safe provider and environment status |
| `GET /api/auth/session` | Current authenticated user, if any |
| `GET /api/auth/google/start` | Start Google OAuth with PKCE |
| `GET /api/auth/google/callback` | Complete Google OAuth and create the session |
| `POST /api/auth/logout` | End the local session |
| `POST /api/agent/search` | Run the brief → search → evidence → analysis → decision workflow |
| `POST /api/agent/refine` | Apply a follow-up preference to an existing research set without repeating retailer discovery |
| `GET /api/plans` | List the signed-in user's private purchase plans |
| `POST /api/plans` | Save a source-linked purchase plan after user selection |
| `GET /api/orders` | List the signed-in user's confirmed orders and tracking timelines |
| `GET /api/orders/:id` | Read one user-scoped order |
| `POST /api/orders` | Create an explicitly confirmed local sandbox order during development |
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
- The service cannot charge a card, submit a retailer checkout, create a merchant order, or truthfully track a merchant order without a retailer integration that explicitly supports those actions.
- In development, the local sandbox order flow is clearly labeled and never stores payment credentials or claims a merchant charge. Production rejects sandbox checkout until a real payment/merchant adapter is enabled.
- Orders created from a search are rehydrated from the server-side verified search result, so a modified browser payload cannot change the catalog price or quantity at checkout.
- The development tracker can advance through delivery, return, and refund states for QA; production status changes must come from merchant webhooks or a supported order API.
- Live saved plans are therefore intentionally named **Ready for retailer checkout**, not paid orders or delivery tracking.
