const receivedPages = [];
const pendingPages = [];
const pageKeys = new Set();
const orderIds = new Set();
let job = null;
let stopped = false;
let batchBytes = 0;

function indianDate(value) {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp) || timestamp <= 0) return "";
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(timestamp > 1e12 ? timestamp : timestamp * 1000));
}

function sendToPortal(type, details) {
  if (job) chrome.runtime.sendMessage({ type: `FLIPKART_${type}`, job_id: job.id, ...details });
}

function tryNextPage() {
  window.setTimeout(() => {
    window.scrollTo(0, document.body.scrollHeight);
    const next = [...document.querySelectorAll("button, [role=button], a")].find((node) => {
      const text = (node.innerText || "").trim();
      const label = (node.getAttribute("aria-label") || "").trim();
      return /^(load more|view more|show more|next|next page)$/i.test(text) || /^(load more|view more|show more|next|next page)$/i.test(label);
    });
    if (next) next.click();
  }, 600);
}

function acceptPage(payload) {
  const view = payload?.RESPONSE?.multipleOrderDetailsView;
  if (!Array.isArray(view?.orders) || stopped) return;
  const pageKey = `${view.moreOrder}:${view.orders.map((order) => `${order?.orderMetaData?.orderId || ""}:${order?.orderMetaData?.orderDate || ""}`).join(",")}`;
  if (pageKeys.has(pageKey)) return;
  const pageBytes = new TextEncoder().encode(JSON.stringify(payload)).length;
  if (batchBytes + pageBytes > 7_000_000) {
    if (receivedPages.length) {
      stopped = true;
      sendToPortal("COMPLETE", { pages: receivedPages, stop_reason: "page_limit" });
    } else {
      stopped = true;
      sendToPortal("ERROR", { error: "A Flipkart order page is too large to upload safely." });
    }
    return;
  }
  pageKeys.add(pageKey);
  receivedPages.push(payload);
  batchBytes += pageBytes;
  for (const order of view.orders) {
    const id = order?.orderMetaData?.orderId;
    if (typeof id === "string" && id) orderIds.add(id);
  }

  const cutoffReached = Boolean(job && view.orders.some((order) => {
    const date = indianDate(order?.orderMetaData?.orderDate);
    return date && date < job.cutoff;
  }));
  sendToPortal("PROGRESS", {
    pages: receivedPages.length,
    orders: orderIds.size,
    more_order: view.moreOrder,
    message: "Reading Flipkart history. Sign in on the Flipkart tab; Artha never receives your password.",
  });

  let stopReason = null;
  if (view.moreOrder === false) stopReason = "history_end";
  else if (cutoffReached) stopReason = "six_month_window";
  else if (receivedPages.length >= 100) stopReason = "page_limit";
  if (!stopReason) {
    if (job) tryNextPage();
    return;
  }

  stopped = true;
  if (!job) return;
  const batch = { pages: receivedPages, stop_reason: stopReason };
  if (new TextEncoder().encode(JSON.stringify(batch)).length > 7_000_000) {
    sendToPortal("ERROR", { error: "The order history is too large for one upload. Try a shorter history window." });
    return;
  }
  sendToPortal("COMPLETE", batch);
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type !== "INIT" || typeof message.job_id !== "string") return;
  job = { id: message.job_id, cutoff: message.cutoff };
  for (const payload of pendingPages.splice(0)) acceptPage(payload);
});

window.addEventListener("message", (event) => {
  if (event.source !== window || event.origin !== location.origin || event.data?.source !== "artha-flipkart-main") return;
  if (!job) pendingPages.push(event.data.payload);
  else acceptPage(event.data.payload);
});
