# Artha Retailer Connector

The extension connects Amazon India, Flipkart, Myntra, and AJIO to Taste OS. A user starts from the signed-in local portal, signs in on the retailer tab Chrome opens, and the extension reads the visible order-history pages. It filters each page down to order IDs, dates, product links, names, prices, sizes, colors, totals, and delivery status; retailer passwords, cookies, addresses, and unrelated account data stay in Chrome. The extension sends one batch to the portal after the history scan, and the backend parses, deduplicates, saves, and indexes the orders.

Install for local testing:

1. Start the portal with `npm start` and use the local URL it opens. This checkout currently uses `http://127.0.0.1:5176`; the extension also allows `localhost` and port `5173` for development.
2. Open `chrome://extensions`, enable **Developer mode**, select **Load unpacked**, and choose this `extension` folder.
3. Sign in to Taste OS and Google, open Taste Graph, and press **Connect** for a retailer. Sign in only in the retailer tab. Keep that tab open until the portal reports completion.

The extension imports six months of order history in one upload. It does not download invoice PDFs. If a retailer changes its order-history page layout, the connector stops and reports an unreadable page rather than marking partial data as complete. Instagram personal-account history is not available through Meta's official API; add a public Reel URL in Discover to save its style.

For a hosted portal, package a separate extension build with the exact HTTPS portal origin in the first portal entry under `manifest.json`'s `content_scripts.matches` and in `host_permissions`; both bridges read that allowlist from the manifest. Add the same origin to the backend's `SHOPPINGHELP_APP_URL` and `SHOPPINGHELP_CORS_ORIGIN`. This checkout currently targets local testing; no production portal domain or extension store credentials were supplied.
