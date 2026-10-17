const portalOrigins = new Set((chrome.runtime.getManifest().content_scripts?.[0]?.matches || []).flatMap((pattern) => {
  try { return [new URL(pattern.replace(/\/\*$/, "/")).origin]; } catch { return []; }
}));

function post(type, detail = {}) {
  window.postMessage({ source: "artha-extension", type, ...detail }, location.origin);
}

window.addEventListener("message", (event) => {
  if (event.source !== window || event.origin !== location.origin || !portalOrigins.has(location.origin)) return;
  const message = event.data;
  if (message?.source !== "artha-portal") return;
  if (message.type === "PING") {
    post("READY");
  } else if (message.type === "START") {
    chrome.runtime.sendMessage({ type: "START", job_id: message.job_id, provider: message.provider, cutoff: message.cutoff }, (result) => {
      post("START_RESULT", result || { ok: false, error: "The connector could not open the retailer." });
    });
  } else if (message.type === "CANCEL" || message.type === "FINISH") {
    chrome.runtime.sendMessage({ type: message.type, job_id: message.job_id }, (result) => {
      post(`${message.type}_RESULT`, result || { ok: false });
    });
  }
});

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "PROGRESS" || message?.type === "COMPLETE_BATCH" || message?.type === "ERROR") {
    post(message.type, message);
  }
});
