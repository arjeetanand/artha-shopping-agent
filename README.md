# Artha — source-linked purchase research

Artha turns a natural-language shopping brief, reference image, or product/post URL into a source-linked purchase plan. It extracts the constraints, searches live retailer sources through Tavily or Anakin, normalizes the evidence, applies budget and delivery constraints, and lets a signed-in user save private retailer handoffs.

This is a research and retailer handoff flow with a clearly labeled local order sandbox. Artha does not submit retailer orders or collect live payments. Even if Razorpay credentials are present, new in-app charges stay disabled until retailer fulfillment is connected; shoppers complete real purchases at the retailer.

## What runs where

- **React + Vite** provides the responsive web interface.
- **Python API** handles provider credentials, Google OAuth, workflow orchestration, and SQLite persistence; `cryptography` encrypts linked Gmail refresh tokens.
- **Tavily** supplies basic-tier live search with 1,000 free credits/month; local Playwright reads retailer Product JSON-LD without API credits. Tavily Extract is a reference-text fallback. **Anakin** remains available as an optional provider.
- **Local fixture catalog** is available only when `SHOPPINGHELP_SEARCH_MODE=fixture`; it keeps development and end-to-end tests deterministic without sending test briefs to a third party.
- **Ollama** is selected by default in local development for brief extraction.
- **Gemini** is selected by default when `APP_ENV=production`; it can analyze reference images as well as text.
- **Kokoro** is the preferred local voice when the optional local voice environment is installed, with browser SpeechSynthesis as a fallback. **ElevenLabs** is selected by default in production.
- **SLNG** provides Nova 3 speech transcription and Aura 2 spoken replies. The browser records the microphone directly; the API key stays on the Python server.
- **Usage & runtime** keeps a persistent SQLite ledger of provider-reported AI tokens, plus clearly marked unmetered search-provider activity and server voice activity. The UI can filter the ledger by local or production runtime without pretending to switch the running deployment.

## Run locally

The easiest way to start both the Python backend and the Vite frontend together:

```bash
./run.sh
# or: npm start
```

Taste OS: sign in with Google, open **Taste OS**, and click **Connect** beside a retailer. Complete retailer login and OTP in the separate Chrome window. The connector reads the last six calendar months of visible order history, downloads available invoice PDFs, and reports missing invoices or incomplete pagination. It never substitutes sample purchases. This requires running the app on your desktop with Chrome installed; hosted deployments need a separate local connector.

You can also connect Gmail from Taste OS. After Google read-only consent, Artha searches retailer emails from Amazon, Flipkart, and Myntra, imports readable product titles into purchase memory, and privately stores attached PDF invoices. Gmail sync checks all matching message history and deduplicates imported messages; unsupported email layouts are reported as partial instead of inventing product data.

Keep the private Chrome window open until sync finishes. Flipkart invoices are downloaded from **Price details** on each item page; shared orders may not expose an invoice download even when their order history was read successfully.

Amazon Business uses a separate year selector; the connector selects it explicitly because Amazon can ignore the date in the URL. Confirm you signed into the account containing your purchases. An empty Business account cannot supply personal-account orders. The browser regression test is `npm run test:retailer-browser`.

Connect Instagram to read shared posts that require login. Sharing a readable post saves its analyzed style as a personal memory. Saving a product also teaches the profile; removing that saved product removes its preference memory. Real semantic vectors use the configured Gemini embedding API, or an installed Ollama embedding model. Unavailable embeddings remain explicitly pending, with keyword retrieval until reindexing succeeds. Invoice PDFs, extracted invoice text, and browser sessions stay in the private OS user-data directory; embedding requests contain product or style descriptions.

This single command:
1. Creates or uses `.venv` and installs the backend requirements when missing.
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
.venv/bin/python -m pip install -r backend/requirements.txt
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

The Gmail OAuth, retailer email parsing, invoice privacy, and purchase-memory import contract runs with mocked Google API responses:

```bash
npm run test:gmail
```

The browser voice-call loop can be checked with `npm run test:voice` after installing Playwright Chromium. To use an existing Chrome binary, set `SHOPPINGHELP_CHROME_PATH` to its executable path.

The SLNG HTTP TTS request contract is covered offline with mocked responses:

```bash
npm run test:slng
```

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

### Gmail purchase history

Enable the Gmail API in the same Google Cloud project and register `GOOGLE_GMAIL_REDIRECT_URI` as an authorized redirect URI alongside the sign-in callback. The default local value is:

```text
http://127.0.0.1:8000/api/auth/gmail/callback
```

Gmail is an explicit second consent step. Artha requests only `gmail.readonly`, stores the refresh token encrypted with AES-GCM, and reads retailer messages from Amazon, Flipkart, and Myntra. The encryption key is derived from `GOOGLE_CLIENT_SECRET`; rotating that secret requires connecting Gmail again. Disconnecting Gmail revokes the Google grant and keeps imported orders and invoice PDFs in the user's history.

Google classifies `gmail.readonly` as a restricted scope. Google OAuth verification and its security assessment requirements apply before enabling this feature for public users; test deployments can use configured OAuth consent-screen test users. See [Google's Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes) and [OAuth web-server guidance](https://developers.google.com/identity/protocols/oauth2/web-server).

### Search and URL extraction

For the free-tier route, get a key from [Tavily](https://app.tavily.com) and add it to your local `.env` (never to frontend variables):

```dotenv
TAVILY_API_KEY=your-key
SHOPPINGHELP_SEARCH_PROVIDER=tavily
SHOPPINGHELP_SEARCH_MODE=live
```

Restart with `npm start`. `/api/health` should report `search_provider: "tavily"` and `search_configured: true`; this confirms configuration, not account credits or connectivity. The sidebar and Usage & runtime view show the selected provider. Search results retain their source URLs. Public product pages are checked through the existing local Playwright scraper with its public-network guard; exact Product JSON-LD supplies purchase evidence. If Chrome/Chromium is unavailable or a retailer blocks extraction, Tavily Extract can return reference text, but text alone never verifies a price or stock.

[Tavily's free plan](https://docs.tavily.com/documentation/api-credits) provides 1,000 credits/month without a credit card. We explicitly use basic search (1 credit/request) with automatic parameter upgrades disabled. A normal brief runs three searches (3 credits); an exact-item cross-store check may add one, and multi-item briefs run searches per item. Local page extraction costs no API credits. Basic Tavily extraction costs 1 credit per 5 successful URL extractions. Free-tier limits still apply; keep pay-as-you-go and automatic paid upgrades disabled in your Tavily account if you want to stay free.

`SHOPPINGHELP_SEARCH_PROVIDER=auto` prefers Tavily when its key is set, otherwise Anakin. To keep Anakin explicitly, set `SHOPPINGHELP_SEARCH_PROVIDER=anakin` and `ANAKIN_API_KEY`. Provider failures never silently switch to a paid service or demo products. Credit, authentication, and rate-limit errors are reported separately without exposing provider response bodies or keys.

Discovery uses category-specific store queries and requires an India storefront or INR evidence before accepting a source. The search introduction labels live search and the demo catalog separately. Products with unknown prices stay unselected. If the scraper groups the main item with recommendations, Artha can recover its price and unavailable-stock status from a single Product JSON-LD object on the same product page; listing pages and redirects do not qualify.

Run the offline live-search contracts with `npm run test:search`.

The budget field accepts INR amounts such as `2000`, `₹2,000`, `2k`, and `2.5k`. Explicit shorts-and-shirt outfits keep each piece's color and size separately. Artha asks for missing sizes, wearer, delivery timing, and whether the budget covers the outfit or each item. Answers can be submitted together in the follow-up form. A complete outfit is selected only when both pieces have known prices and fit the confirmed budget; missing retailer evidence remains flagged.

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

`VOICE_PROVIDER=auto` uses `LOCAL_VOICE_PROVIDER` during development and ElevenLabs in production. Set `LOCAL_VOICE_PROVIDER=kokoro` for the local studio voice, or `browser` for zero-install development. Set `VOICE_PROVIDER=slng` with `SLNG_API_KEY` to send spoken replies through SLNG Aura 2; `SLNG_API_BASE_URL` defaults to `https://in.api.slng.ai`. SLNG retired the global `api.slng.ai` gateway: update existing `.env` files to a [supported regional gateway](https://docs.slng.ai/api-reference/text-to-speech/deepgram/deepgram-aura-2/aura-2-http). The Python server posts normalized answer text to `/v1/tts/deepgram/aura:2` with model `aura-2-thalia-en` and explicitly requests 24 kHz linear PCM in a WAV container for browser playback. The key stays on the Python server. If server voice fails, the call switches to browser speech with a visible notice while keeping the answer in the transcript.

For the hackathon demo, add your SLNG key to the ignored `.env`, then run a deterministic shopping scenario with SLNG voice output:

```bash
npm run demo:voice
```

Open the frontend address printed by the startup script in Chrome or Edge, then choose **Talk to Artha → Start call** and allow microphone access. You can begin the search entirely by voice:

1. “Find me an office chair.” Artha asks one missing detail at a time, starting with budget.
2. “Under twelve thousand rupees, delivered to Bangalore within five days.” Artha fetches and ranks the fixture products.
3. “Why did you rank it first?” Artha explains the recommendation from the existing evidence.
4. “Can anything arrive faster?” Artha compares the stated delivery times.

For an outfit, start with “I want to buy a white shirt and white pants.” You can answer each question briefly: “two thousand”, “Bengaluru”, “five days”, “men”, “whole outfit”, then the requested shirt and pants sizes and delivery pincode. Each answer refines the same search. “I want it cheaper” keeps the existing shortlist; say “new search” to start over. Product cards, prices, delivery caveats, and retailer links appear inside the voice chat. Use **Interrupt and speak** to stop an answer and ask the next question. Real purchases finish on the retailer website; the in-app order tracker is a local sandbox.

With SLNG selected, both **Speak brief** and **Start call** capture raw microphone samples with an AudioWorklet and send a WAV recording to `/api/voice/transcribe`. The server uses SLNG Nova 3 English at `/v1/stt/slng/deepgram/nova:3-en`; browser SpeechRecognition is not used. Speak in English and pause for about 1.2 seconds, or press **Send voice** in the call to submit manually. A turn lasts at most 30 seconds; no detected microphone audio ends the call with an explanation after 10 seconds. The microphone stops while the recording is transcribed. Recordings are sent to SLNG for transcription and are not saved to disk. SLNG speaks the answer, and the call resumes listening afterward. End the call when finished.

Microphone samples are mixed to mono, resampled to 16 kHz, and encoded directly as PCM WAV. Voice input uses neither MediaRecorder nor decodeAudioData, so browser recording-codec support cannot trigger an audio-decode failure. The worklet outputs silence to avoid playing the microphone back through the speakers. In the Talk drawer, **Send voice** submits the recognized request to the shopping agent even without starting a continuous call. Transcription status clears when recording finishes; failures stay visible inside the drawer, and stalled uploads time out after 40 seconds. Server failure logs include only recording format, exception class, and provider HTTP status, never recording contents or the API key.

Fixture mode uses deterministic brief parsing and a local sample catalog, with no LLM or live retailer search. The products and delivery estimates are demo data. Use `npm start` with `SHOPPINGHELP_SEARCH_MODE=live` for live retailer research. **End call** or closing the drawer cancels recording, pending transcription, and playback. Typed questions also work in the same drawer.

`npm run test:voice:live` generates three microphone samples with SLNG and feeds them through Web Audio into one continuous Chrome call. Every turn uses the real recorder, SLNG transcription, backend shopping workflow, and SLNG reply playback: initial brief, budget/delivery clarification, and a delivery comparison. It verifies automatic listening between turns, retailer links inside the chat, and no browser-voice fallback. Search uses an isolated fixture catalog and database. The test incurs three STT and six TTS requests, within the existing ten-request per-minute limit; no transcript events or shopping API responses are mocked. Physical microphone selection and OS permission still need a manual check. `npm run test:voice` covers PCM encoding, worklet capture, one-question follow-ups, shopping-versus-checkout routing, cheaper refinements, retailer links, playback interruption, manual send, transcription errors, cancellation, and browser voice fallback offline. `npm run test:slng` checks the provider contracts. The server allows ten combined STT/TTS requests per IP per minute (five spoken turns) and 120 globally per rolling hour. Transcription failures stop the call with an explanation; reply synthesis failures use browser voice with a notice.

Other voice providers retain browser SpeechRecognition for input. The call transcript stays visible, and every spoken turn uses the same research and refinement flow as typed requests. Use Chrome or Edge if microphone recording is unavailable in an embedded browser.

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
4. **Search agent** calls the selected search provider for retailer sources, and optionally scrapes a pasted URL for reference context. Provider-neutral retailer and delivery contracts live in `backend/retailers.py`; dedicated marketplace adapters can be added without changing ranking or UI code.
5. **Evidence agent** normalizes source-linked fields and labels unknown delivery, stock, variant, and price information as needing retailer confirmation.
6. **Research agent** checks up to four discovery pages in parallel, then up to four exact-item pages from other retailer sites when product identity is strong enough. Each page check has a 45-second time budget. It uses direct-page details ahead of search snippets, records price mismatches, and keeps empty or failed checks visibly unverified. Fixture mode uses deterministic catalog evidence without network calls.
7. **Analysis agent** cross-checks review-source consistency and current-vs-history price signals when those fields are available, explicitly preserving unknowns.
8. **Decision agent** ranks by fit, seller signals, budget, delivery, stock, color, size, and evidence, then applies an evidence gate. It returns `buy_now`, `verify_before_buy`, or `no_safe_fit`; unknown or conflicting price, delivery, stock, color, or size can never produce `buy_now`.
9. **Purchase-plan service** persists only an authenticated user's selected, linked products in local SQLite.
10. **Order service** persists explicitly confirmed sandbox orders for local testing. Production purchases happen on retailer sites; historical signed payment attempts can still be reconciled, but new charges are blocked.

Each result also carries an evidence ledger when the source provides it: review-source samples and consistency signals, current-vs-history price context, seller/stock/delivery evidence, and explicit unknowns when those fields are unavailable. Select the shield action on a result to inspect that ledger before saving or checkout.

The price desk groups directly checked live pages across stores by a valid Product JSON-LD GTIN and matching known variant, or by brand, exact title, color, and size; otherwise each retailer URL has its own history. After finding a verified item with that strong identity, Artha makes one bounded search for the same item at other retailers. It shows the lowest price among matching offers checked in that search and stores timestamped INR observations in SQLite. Historical lows and trends reflect Artha's observations only. Fixture history is labeled demo data. Store prices can omit shipping, tax, variant availability, and delivery, so the recommended retailer may differ from the lowest item-price offer.

When a product just outside the budget still satisfies delivery and stock constraints, the result includes a clearly labeled **Worth a small stretch** opportunity. It never changes the selected plan automatically; the user can inspect that product's evidence before deciding.

Live searches can be started asynchronously with `POST /api/agent/search/jobs` and polled at `GET /api/agent/search/jobs/:job_id`. The job returns queued, working, complete, waiting, or failed stage snapshots while live search and parallel direct-page checks run, so the UI can keep the workflow visible instead of holding a blank request open.

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
| `GET /api/auth/gmail/start` | Request Gmail read-only consent for the signed-in user |
| `GET /api/auth/gmail/callback` | Save the encrypted Gmail grant and start the first sync |
| `POST /api/profile/gmail/sync` | Sync retailer messages and PDF invoices |
| `POST /api/profile/gmail/cancel` | Stop the active Gmail sync |
| `POST /api/profile/gmail/disconnect` | Revoke Gmail access and keep imported history |
| `GET /api/profile/gmail/status` | Read the user's Gmail sync status |
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

- SQLite stores searches, OAuth state, hashed sessions, users, user-scoped purchase plans, Gmail token ciphertext, Gmail import IDs, and provider usage events in `backend/shoppinghelp.sqlite3`.
- Usage events store counts and metadata only: provider, operation, model name, token counts when reported, character/byte counts for unmetered activity, runtime, status, and timestamp. Provider credentials are never written to the ledger.
- Google sign-in tokens are discarded after identity verification. Gmail refresh tokens are encrypted at rest; payment credentials and reference-image bytes are not persisted.
- The service cannot submit a retailer checkout, create a merchant order, or truthfully track a merchant order without a retailer integration that explicitly supports those actions. Razorpay payment authorization is separate from retailer fulfillment.
- In development, the local sandbox order flow is clearly labeled and never stores payment credentials or claims a merchant charge. Production rejects sandbox checkout until a real payment/merchant adapter is enabled.
- New Razorpay payment orders are blocked. Historical attempts are verified server-side with the signed `order_id|payment_id` callback; failed or replayed attempts do not create an order.
- Orders created from a search are rehydrated from the server-side verified search result, so a modified browser payload cannot change the catalog price or quantity at checkout.
- The development tracker can advance through delivery, return, and refund states for QA; production status changes must come from merchant webhooks or a supported order API.
- Live saved plans are therefore intentionally named **Ready for retailer checkout**, not paid orders or delivery tracking.
