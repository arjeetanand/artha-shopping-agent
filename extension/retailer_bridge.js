(() => {
  const RETAILERS = {
    amazon: { origin: "https://www.amazon.in", path: /^\/gp\/your-account\/order-history/, cards: ".order-card, .js-order-card", products: 'a[href*="/dp/"], a[href*="/gp/product/"]' },
    myntra: { origin: "https://www.myntra.com", path: /^\/my\/orders/, cards: '[class*="order-card"], [class*="orderCard"], [data-testid="order-card"]', products: 'a[href*="/buy"]' },
    ajio: { origin: "https://www.ajio.com", path: /^\/my-account\/orders/, cards: '[class*="order-card"], [class*="orderCard"]', products: 'a[href*="/p/"]' },
  };
  const provider = Object.keys(RETAILERS).find((key) => location.origin === RETAILERS[key].origin && RETAILERS[key].path.test(location.pathname));
  if (!provider || window.__arthaRetailerBridgeRunning) return;
  window.__arthaRetailerBridgeRunning = true;
  let job = null;

  const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
  const text = (node) => String(node?.innerText || node?.textContent || "").replace(/\s+/g, " ").trim();
  const orderDate = (value) => {
    const raw = String(value || "");
    const labelled = raw.match(/(?:order\s*(?:placed|date)|placed\s*on|ordered\s*on)\s*[:\-]?\s*((?:\d{4}-\d{1,2}-\d{1,2})|(?:\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}[, ]+20\d{2})|(?:[A-Za-z]{3,9}\s+\d{1,2}[, ]+20\d{2})|(?:\d{1,2}[/.\-]\d{1,2}[/.\-]20\d{2}))/i);
    const candidate = (labelled?.[1] || raw.match(/\b(?:20\d{2}-\d{1,2}-\d{1,2}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}[, ]+20\d{2}|[A-Za-z]{3,9}\s+\d{1,2}[, ]+20\d{2}|\d{1,2}[/.\-]\d{1,2}[/.\-]20\d{2})\b/i)?.[0] || "").replace(/(\d)(?:st|nd|rd|th)\b/i, "$1");
    let year, month, day;
    let match = candidate.match(/^(20\d{2})-(\d{1,2})-(\d{1,2})$/);
    if (match) [, year, month, day] = match;
    if (!match && (match = candidate.match(/^(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2})$/))) [, day, month, year] = match;
    const months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
    if (!match && (match = candidate.match(/^(\d{1,2})\s+([A-Za-z]{3,9})[, ]+(20\d{2})$/))) {
      [, day, month] = match; year = match[3]; month = months.indexOf(month.slice(0, 3).toLowerCase()) + 1;
    }
    if (!match && (match = candidate.match(/^([A-Za-z]{3,9})\s+(\d{1,2})[, ]+(20\d{2})$/))) {
      [, month, day, year] = match; month = months.indexOf(month.slice(0, 3).toLowerCase()) + 1;
    }
    if (!match) return "";
    year = Number(year); month = Number(month); day = Number(day);
    const parsed = new Date(Date.UTC(year, month - 1, day));
    return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day ? parsed.toISOString().slice(0, 10) : "";
  };

  function safeProductUrl(value) {
    try {
      const url = new URL(value, location.href);
      const goodPath = provider === "amazon" ? /\/(?:dp|gp\/product)\//i.test(url.pathname)
        : provider === "myntra" ? /\/buy\/?$/i.test(url.pathname) : /\/p\//i.test(url.pathname);
      return url.origin === RETAILERS[provider].origin && goodPath ? url.href : "";
    } catch { return ""; }
  }

  function cardSnapshot(card) {
    const raw = text(card);
    const ids = [
      ...raw.matchAll(/\b\d{3}-\d{7}-\d{7}\b/g),
      ...raw.matchAll(/\bOD[A-Z0-9-]{8,40}\b/gi),
      ...raw.matchAll(/(?:order\s*(?:id|number|no\.?|#))\s*[:#-]?\s*([A-Z0-9-]{6,40})/gi),
    ].map((match) => match[1] || match[0]);
    if (new Set(ids).size > 1) return null;
    const orderId = String(card.getAttribute("data-order-id") || card.getAttribute("data-orderid") || "").trim()
      || raw.match(/\b\d{3}-\d{7}-\d{7}\b/)?.[0]
      || raw.match(/\bOD[A-Z0-9-]{8,40}\b/i)?.[0]
      || raw.match(/(?:order\s*(?:id|number|no\.?|#))\s*[:#-]?\s*([A-Z0-9-]{6,40})/i)?.[1]
      || [...card.querySelectorAll('a[href*="orderID="], a[href*="order_id="], a[href*="/my/orders/"]')]
        .map((link) => { try { const url = new URL(link.href); return url.searchParams.get("orderID") || url.searchParams.get("order_id") || url.pathname.match(/\/my\/orders\/([A-Z0-9-]{6,50})/i)?.[1] || ""; } catch { return ""; } })
        .find(Boolean) || "";
    const date = orderDate(card.getAttribute("data-order-date") || raw);
    if (!orderId || !date) return null;

    const total = raw.match(/(?:grand\s*total|order\s*total|total\s*amount|total\s*paid)\s*[:\-]?\s*((?:₹|INR|Rs\.?)\s*[\d,]+(?:\.\d{1,2})?)/i)?.[1] || "";
    const status = raw.match(/\b(delivered|cancelled|canceled|returned|refunded|shipped|dispatched)\b/i)?.[1] || "";
    const products = [];
    const seen = new Set();
    for (const link of card.querySelectorAll(RETAILERS[provider].products)) {
      const url = safeProductUrl(link.href);
      const name = text(link) || String(link.querySelector("img")?.alt || "").trim();
      if (!url || name.length < 4 || seen.has(url)) continue;
      seen.add(url);
      const itemText = text(link.parentElement);
      const attributes = [
        itemText.match(/\bSize\s*[:=-]\s*([^,|]{1,20})/i)?.[1],
        itemText.match(/\bColou?r\s*[:=-]\s*([^,|]{1,30})/i)?.[1],
      ].filter(Boolean);
      products.push({ name: name.slice(0, 300), url, text: attributes.join("\n"),
        price: itemText.match(/(?:₹|INR|Rs\.?)\s*[\d,]+(?:\.\d{1,2})?/i)?.[0] || "" });
      if (products.length >= 100) break;
    }
    const fields = [`Order ID: ${orderId}`, `Order placed on ${date}`, status, total && `Order total ${total}`].filter(Boolean);
    return { url: location.href, orderId, orderDate: date, text: fields.join("\n"), products };
  }

  function snapshots() {
    const unique = new Set();
    const cards = [];
    for (const card of document.querySelectorAll(RETAILERS[provider].cards)) {
      const snapshot = cardSnapshot(card);
      if (!snapshot || unique.has(snapshot.orderId)) continue;
      unique.add(snapshot.orderId);
      cards.push(snapshot);
    }
    return cards;
  }

  function nextPageUrl() {
    const anchors = [...document.querySelectorAll('a[rel="next"], a[aria-label*="next" i], li.a-last:not(.a-disabled) a')];
    const anchor = anchors.find((node) => node.href && !node.closest(".a-disabled"))
      || [...document.querySelectorAll("a")].find((node) => /^(?:next|next page)$/i.test(text(node)) && node.href);
    if (!anchor) return "";
    try {
      const url = new URL(anchor.href);
      return url.origin === RETAILERS[provider].origin && RETAILERS[provider].path.test(url.pathname) ? url.href : "";
    } catch { return ""; }
  }

  async function prepareAmazonYear() {
    if (provider !== "amazon") return;
    const year = new URL(location.href).searchParams.get("orderFilter")?.replace("year-", "");
    const filter = document.querySelector("#timeFilterDropdown");
    if (filter && year && filter.value !== year) {
      filter.value = year;
      filter.dispatchEvent(new Event("change", { bubbles: true }));
      await wait(1200);
    }
  }

  async function scan() {
    if (!job) return;
    try {
      if (document.readyState === "loading") await new Promise((resolve) => document.addEventListener("DOMContentLoaded", resolve, { once: true }));
      await wait(700);
      await prepareAmazonYear();
      let cards = snapshots();
      let stable = 0;
      for (let attempt = 0; attempt < 20 && stable < 3; attempt += 1) {
        window.scrollTo(0, document.body.scrollHeight);
        const button = [...document.querySelectorAll("button, [role=button]")].find((node) => /^(?:load more|view more|show more)$/i.test(text(node)) && !node.disabled);
        const previousCount = cards.length;
        if (button) { button.click(); await wait(900); }
        else await wait(500);
        const next = snapshots();
        cards = next;
        if (next.length > previousCount) stable = 0; else stable += 1;
      }
      const body = text(document.body);
      const empty = /(?:no orders|haven.t placed any orders|you have not placed any|no purchases)/i.test(body);
      if (!cards.length && !empty) {
        const signIn = /sign in|log in|login/i.test(body) && Boolean(document.querySelector('input[type="password"]'));
        throw new Error(signIn ? `Sign in to ${provider} on this tab, then start the sync again from Taste Graph.` : `Could not recognize ${provider}'s order-history layout; no orders were saved.`);
      }
      const nextUrl = nextPageUrl();
      const older = cards.some((order) => order.orderDate && order.orderDate < job.cutoff);
      chrome.runtime.sendMessage({ type: "RETAILER_PAGE", job_id: job.id, provider,
        page: { url: location.href, orders: cards, next_url: older ? "" : nextUrl, empty,
          stop_reason: older ? "six_month_window" : "" } });
    } catch (error) {
      chrome.runtime.sendMessage({ type: "RETAILER_ERROR", job_id: job?.id, provider, error: error.message || "The retailer history could not be read." });
    }
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type !== "INIT" || message.provider !== provider || typeof message.job_id !== "string" || job) return;
    job = { id: message.job_id, cutoff: message.cutoff };
    scan();
  });
})();
