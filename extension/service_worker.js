const PROVIDERS = {
  amazon: { origin: "https://www.amazon.in", path: /^\/gp\/your-account\/order-history/, orders: "https://www.amazon.in/gp/your-account/order-history" },
  flipkart: { origin: "https://www.flipkart.com", path: /^\/account\/orders/, orders: "https://www.flipkart.com/account/orders" },
  myntra: { origin: "https://www.myntra.com", path: /^\/my\/orders/, orders: "https://www.myntra.com/my/orders" },
  ajio: { origin: "https://www.ajio.com", path: /^\/my-account\/orders/, orders: "https://www.ajio.com/my-account/orders" },
};
const MAX_BATCH_BYTES = 7_000_000;
const MAX_PAGES = 100;

async function readJobs() { return (await chrome.storage.session.get("jobs")).jobs || {}; }
async function writeJobs(jobs) { await chrome.storage.session.set({ jobs }); }

function allowedPortalOrigins() {
  return (chrome.runtime.getManifest().content_scripts?.[0]?.matches || []).flatMap((pattern) => {
    try {
      const url = new URL(pattern.replace(/\/\*$/, "/"));
      return url.hostname === "*" ? [] : [url.origin];
    } catch { return []; }
  });
}

function validPortal(sender) {
  try { return allowedPortalOrigins().includes(new URL(sender.url).origin); } catch { return false; }
}

function retailerAt(urlValue, provider = "") {
  try {
    const url = new URL(urlValue);
    return Object.entries(PROVIDERS).some(([key, config]) => (!provider || key === provider)
      && url.origin === config.origin && config.path.test(url.pathname));
  } catch { return false; }
}

function indianToday() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function amazonYears(cutoff) {
  const urls = [];
  for (let year = Number(indianToday().slice(0, 4)); year >= Number(cutoff.slice(0, 4)); year -= 1) {
    urls.push(`https://www.amazon.in/gp/your-account/order-history?orderFilter=year-${year}`);
  }
  return urls;
}

function sendPortal(job, message) {
  chrome.tabs.sendMessage(job.portal_tab_id, { ...message, job_id: job.job_id, provider: job.provider }).catch(() => {});
}

function utf8Bytes(value) { return new TextEncoder().encode(JSON.stringify(value)).length; }

async function completeRetailerPage(job, page) {
  if (!page || !retailerAt(page.url, job.provider) || !Array.isArray(page.orders)) throw new Error("The retailer page data is invalid.");
  const jobs = await readJobs();
  const current = jobs[job.job_id];
  if (!current) return;
  const signature = `${page.url}:${page.orders.map((order) => order.orderId || "").join(",")}`;
  if (current.page_signatures.includes(signature)) {
    sendPortal(current, { type: "ERROR", error: "The retailer repeated an order-history page; stop and reconnect to avoid missing orders." });
    delete jobs[current.job_id];
    await writeJobs(jobs);
    return;
  }
  current.page_signatures.push(signature);
  current.pages.push(page);
  current.orders += page.orders.length;
  const payload = { pages: current.pages, stop_reason: "history_end" };
  if (current.pages.length > MAX_PAGES || utf8Bytes(payload) > MAX_BATCH_BYTES) {
    sendPortal(current, { type: "ERROR", error: "This retailer history is too large for one safe upload. Try again after narrowing the history window." });
    delete jobs[current.job_id];
    await writeJobs(jobs);
    return;
  }
  await writeJobs(jobs);
  sendPortal(current, { type: "PROGRESS", pages: current.pages.length, orders: current.orders,
    message: `Read ${current.pages.length} order-history pages from ${current.provider}.` });

  const cutoffFound = page.orders.some((order) => order.orderDate && order.orderDate < current.cutoff);
  if (page.stop_reason === "page_limit" || cutoffFound) {
    current.stop_reason = cutoffFound ? "six_month_window" : "page_limit";
    await finishRetailerJob(current);
    return;
  }
  if (current.pages.length >= MAX_PAGES) {
    current.stop_reason = "page_limit";
    await finishRetailerJob(current);
    return;
  }

  let nextUrl = page.next_url || "";
  if (!nextUrl && current.provider === "amazon" && current.amazon_url_index + 1 < current.amazon_urls.length) {
    current.amazon_url_index += 1;
    nextUrl = current.amazon_urls[current.amazon_url_index];
  }
  if (nextUrl) {
    if (!retailerAt(nextUrl, current.provider)) throw new Error("The retailer supplied an unsafe next-page link.");
    current.visited_urls.push(page.url);
    if (current.visited_urls.includes(nextUrl)) throw new Error("The retailer repeated an order-history page.");
    await writeJobs(jobs);
    await chrome.tabs.update(current.retailer_tab_id, { url: nextUrl });
    return;
  }
  current.stop_reason = page.empty ? "history_end" : page.stop_reason || "history_end";
  await finishRetailerJob(current);
}

async function finishRetailerJob(job) {
  const jobs = await readJobs();
  const current = jobs[job.job_id];
  if (!current || current.completed_sent) return;
  current.stop_reason = job.stop_reason || current.stop_reason || "history_end";
  current.completed_sent = true;
  await writeJobs(jobs);
  sendPortal(current, { type: "COMPLETE_BATCH", pages: current.pages, stop_reason: current.stop_reason || "history_end" });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "START" && validPortal(sender)) {
    (async () => {
      const provider = message.provider;
      const config = PROVIDERS[provider];
      const cutoff = message.cutoff;
      if (!config || !/^sync-[a-f0-9]{32}$/.test(message.job_id || "") || !/^\d{4}-\d{2}-\d{2}$/.test(cutoff || "")) {
        sendResponse({ ok: false, error: "The retailer sync request is invalid." });
        return;
      }
      const urls = provider === "amazon" ? amazonYears(cutoff) : [config.orders];
      const tab = await chrome.tabs.create({ url: "about:blank", active: true });
      const jobs = await readJobs();
      jobs[message.job_id] = {
        job_id: message.job_id, provider, portal_tab_id: sender.tab.id, retailer_tab_id: tab.id, cutoff,
        pages: [], orders: 0, page_signatures: [], visited_urls: [], amazon_urls: urls, amazon_url_index: 0,
      };
      await writeJobs(jobs);
      await chrome.tabs.update(tab.id, { url: urls[0] });
      sendResponse({ ok: true, started: true });
    })().catch(() => sendResponse({ ok: false, error: "Chrome could not open the retailer tab." }));
    return true;
  }

  if ((message?.type === "CANCEL" || message?.type === "FINISH") && validPortal(sender)) {
    (async () => {
      const jobs = await readJobs();
      const job = jobs[message.job_id];
      delete jobs[message.job_id];
      await writeJobs(jobs);
      if (job && message.type === "CANCEL") await chrome.tabs.remove(job.retailer_tab_id).catch(() => {});
      sendResponse({ ok: true });
    })().catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (["FLIPKART_PROGRESS", "FLIPKART_COMPLETE", "FLIPKART_ERROR"].includes(message?.type) && retailerAt(sender.url, "flipkart")) {
    (async () => {
      const jobs = await readJobs();
      const job = Object.values(jobs).find((item) => item.retailer_tab_id === sender.tab?.id && item.provider === "flipkart");
      if (!job) return;
      if (message.type === "FLIPKART_COMPLETE") {
        job.completed_sent = true;
        job.stop_reason = message.stop_reason;
        await writeJobs(jobs);
        sendPortal(job, { type: "COMPLETE_BATCH", pages: message.pages, stop_reason: message.stop_reason });
      } else {
        if (message.type === "FLIPKART_ERROR") {
          delete jobs[job.job_id];
          await writeJobs(jobs);
          sendPortal(job, { type: "ERROR", error: message.error });
        } else sendPortal(job, { ...message, type: "PROGRESS" });
      }
    })().catch(() => {});
  }

  if (message?.type === "RETAILER_PAGE" && sender.tab && retailerAt(sender.url, message.provider)) {
    (async () => {
      const jobs = await readJobs();
      const job = Object.values(jobs).find((item) => item.retailer_tab_id === sender.tab.id && item.provider === message.provider);
      if (!job || job.completed_sent) return;
      if (message.job_id !== job.job_id) return;
      await completeRetailerPage(job, message.page);
    })().catch(async () => {
      const jobs = await readJobs();
      const job = Object.values(jobs).find((item) => item.retailer_tab_id === sender.tab?.id);
      if (!job) return;
      delete jobs[job.job_id];
      await writeJobs(jobs);
      sendPortal(job, { type: "ERROR", error: "The retailer page could not be read safely. Reload the order-history page and retry." });
    });
  }

  if (message?.type === "RETAILER_ERROR" && sender.tab && retailerAt(sender.url, message.provider)) {
    (async () => {
      const jobs = await readJobs();
      const job = Object.values(jobs).find((item) => item.retailer_tab_id === sender.tab.id && item.provider === message.provider && item.job_id === message.job_id);
      if (!job) return;
      delete jobs[job.job_id];
      await writeJobs(jobs);
      sendPortal(job, { type: "ERROR", error: String(message.error || "The retailer history could not be read.").slice(0, 300) });
    })().catch(() => {});
  }
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !retailerAt(tab.url)) return;
  const jobs = await readJobs();
  const job = Object.values(jobs).find((item) => item.retailer_tab_id === tabId);
  if (job) chrome.tabs.sendMessage(tabId, { type: "INIT", job_id: job.job_id, provider: job.provider, cutoff: job.cutoff }).catch(() => {});
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const jobs = await readJobs();
  const job = Object.values(jobs).find((item) => item.retailer_tab_id === tabId);
  if (!job) return;
  delete jobs[job.job_id];
  await writeJobs(jobs);
  if (!job.completed_sent) sendPortal(job, { type: "ERROR", error: `The ${job.provider} tab closed before history upload finished.` });
});
