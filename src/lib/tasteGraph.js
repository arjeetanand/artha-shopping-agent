const meaningfulGroups = new Set(['vibe', 'brand', 'size', 'address', 'order', 'memory', 'invoice', 'search']);

export const hasMeaningfulTasteGraphData = (nodes = []) => nodes.some((node) => meaningfulGroups.has(node.group));

export const getConnectionNotice = (message = '') =>
  /(?:page\.[\w]+:|target page, context|browser has been closed)/i.test(message)
    ? 'The retailer tab closed before the sync finished. Reconnect and try again.'
    : message;
