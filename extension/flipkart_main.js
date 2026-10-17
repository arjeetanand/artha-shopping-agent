(() => {
  if (window.__arthaFlipkartOrdersHooked) return;
  window.__arthaFlipkartOrdersHooked = true;
  // shortcut: targets Flipkart's current self-serve orders endpoint; update the sanitizer if that API changes.
  const endpoint = /^https:\/\/www\.flipkart\.com\/api\/\d+\/self-serve\/orders\/?$/;

  function money(value) {
    if (!value || typeof value !== "object") return undefined;
    const currencies = Array.isArray(value.amountValueMultiCurrency)
      ? value.amountValueMultiCurrency.filter((item) => item?.currency === "INR").map((item) => ({ currency: item.currency, inrValue: item.inrValue }))
      : undefined;
    return { amountValueMultiCurrency: currencies, amount: value.amount, totalPayable: value.totalPayable };
  }

  function sanitize(payload) {
    const view = payload?.RESPONSE?.multipleOrderDetailsView;
    if (!Array.isArray(view?.orders)) return null;
    const orders = view.orders.map((order) => {
      const products = {};
      for (const [key, product] of Object.entries(order?.productDataBag || {})) {
        products[key] = {
          productBasicData: { title: product?.productBasicData?.title, url: product?.productBasicData?.url },
          productAttribute: {
            storePath: product?.productAttribute?.storePath,
            brand: product?.productAttribute?.brand,
            size: product?.productAttribute?.size,
            color: product?.productAttribute?.color,
          },
        };
      }
      const units = {};
      for (const [key, unit] of Object.entries(order?.units || {})) {
        units[key] = {
          metaData: {
            listingId: unit?.metaData?.listingId,
            fsn: unit?.metaData?.fsn,
            quantity: unit?.metaData?.quantity,
            status: { key: unit?.metaData?.status?.key },
          },
          moneyDataBag: money(unit?.moneyDataBag),
        };
      }
      return {
        orderMetaData: { orderId: order?.orderMetaData?.orderId, orderDate: order?.orderMetaData?.orderDate },
        productDataBag: products,
        units,
        orderMoneyDataBag: money(order?.orderMoneyDataBag),
      };
    });
    return { RESPONSE: { multipleOrderDetailsView: { orders, moreOrder: view.moreOrder } } };
  }

  function publish(url, value) {
    try {
      const parsed = new URL(url, location.href);
      if (parsed.origin !== location.origin || !endpoint.test(parsed.origin + parsed.pathname)) return;
      const payload = sanitize(value);
      if (payload) window.postMessage({ source: "artha-flipkart-main", type: "ORDERS_PAGE", payload }, location.origin);
    } catch { /* Ignore unreadable retailer responses. */ }
  }

  const originalFetch = window.fetch;
  window.fetch = function (...args) {
    const url = typeof args[0] === "string" ? args[0] : args[0]?.url;
    const response = originalFetch.apply(this, args);
    response.then((value) => {
      if (value.ok && url) value.clone().json().then((body) => publish(url, body)).catch(() => {});
    }).catch(() => {});
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__arthaOrdersUrl = url;
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("load", () => {
      if (!this.__arthaOrdersUrl || this.status < 200 || this.status >= 300) return;
      try { publish(this.__arthaOrdersUrl, this.responseType === "json" ? this.response : JSON.parse(this.responseText)); } catch { /* Ignore unreadable responses. */ }
    }, { once: true });
    return originalSend.apply(this, args);
  };
})();
