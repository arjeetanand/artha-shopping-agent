# Artha — source-linked purchase research

Artha turns a natural-language shopping brief, reference image, or product/post URL into a source-linked purchase plan. It extracts the constraints, searches live retailer sources through Anakin, normalizes the evidence, applies budget and delivery constraints, and lets a signed-in user save private retailer handoffs.

This is a real research and handoff flow, not a simulated payment system. Artha never collects payment credentials, sends an order to a retailer, or claims that retailer checkout is complete. The user opens each saved retailer link and completes checkout on the retailer's own secure site.

## What runs where

- **React + Vite** provides the responsive web interface.
- **Python standard library API** handles provider credentials, Google OAuth, workflow orchestration, and SQLite persistence.
- **Anakin** supplies live source search and optional URL extraction.
- **Ollama** is selected by default in local development for brief extraction.
- **Gemini** is selected by default when `APP_ENV=production`; it can analyze reference images as well as text.
- **Kokoro** is the preferred local voice when the optional local voice environment is installed, with browser SpeechSynthesis as a fallback. **ElevenLabs** is selected by default in production.

## Run locally

```bash
cp .env.example .env
npm install
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-kokoro.txt
SHOPPINGHELP_PORT=8000 .venv/bin/python backend/server.py
```

In another terminal:

```bash
SHOPPINGHELP_API_TARGET=http://127.0.0.1:8000 npm run dev
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

1. **Brief agent** extracts category, budget, location, delivery window, must-haves, and visual/style cues.
2. **Search agent** calls Anakin for retailer sources, and optionally scrapes a pasted URL for reference context.
3. **Evidence agent** normalizes source-linked fields and labels unknown delivery, stock, and price information as needing retailer confirmation.
4. **Decision agent** ranks by fit and excludes products with a known budget or delivery-window failure from the default plan.
5. **Purchase-plan service** persists only an authenticated user's selected, linked products in local SQLite.

The known item subtotal deliberately excludes shipping, tax, and any retailer-specific fees that the live source does not verify. The user must confirm those values at checkout.

## API surface

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Safe provider and environment status |
| `GET /api/auth/session` | Current authenticated user, if any |
| `GET /api/auth/google/start` | Start Google OAuth with PKCE |
| `GET /api/auth/google/callback` | Complete Google OAuth and create the session |
| `POST /api/auth/logout` | End the local session |
| `POST /api/agent/search` | Run the brief → search → evidence → decision workflow |
| `GET /api/plans` | List the signed-in user's private purchase plans |
| `POST /api/plans` | Save a source-linked purchase plan after user selection |
| `GET /api/voice/status` | Selected voice provider and availability |
| `POST /api/voice/warm` | Warm the selected local Kokoro voice before playback |
| `POST /api/voice/speak` | Produce the summary audio or local-browser speech instruction |

## Data and safety notes

- SQLite stores searches, OAuth state, hashed sessions, users, and user-scoped purchase plans in `backend/shoppinghelp.sqlite3`.
- No Google OAuth token, payment credential, or reference-image bytes are persisted.
- The service cannot charge a card, submit a retailer checkout, create a merchant order, or truthfully track a merchant order without a retailer integration that explicitly supports those actions.
- Saved plans are therefore intentionally named **Ready for retailer checkout**, not paid orders or delivery tracking.
