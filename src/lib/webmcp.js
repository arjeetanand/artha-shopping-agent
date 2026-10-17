/**
 * WebMCP (Web Model Context Protocol) Standard Implementation
 * 
 * Provides native registration or polyfills document.modelContext and navigator.modelContext
 * to expose machine-readable tools directly to in-browser AI agents and assistants.
 * Compliant with Google Chrome Labs WebMCP specifications and Apache 2.0 reference implementations.
 */

export class WebModelContext {
  constructor() {
    this._tools = new Map();
  }

  registerTool(toolDefinition, { signal } = {}) {
    if (!toolDefinition || typeof toolDefinition !== 'object') {
      throw new TypeError('WebMCP: toolDefinition must be an object.');
    }
    const { name, description, inputSchema, execute } = toolDefinition;
    if (!name || typeof name !== 'string') {
      throw new TypeError('WebMCP: tool name is required and must be a string.');
    }
    if (typeof execute !== 'function') {
      throw new TypeError(`WebMCP: execute function is required for tool "${name}".`);
    }

    const tool = {
      name,
      description: description || '',
      inputSchema: inputSchema || { type: 'object', properties: {} },
      execute,
    };

    this._tools.set(name, tool);

    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('modelcontext:toolregistered', { detail: { name, tool } })
      );
    }

    if (signal) {
      const unregister = () => this.unregisterTool(name);
      if (signal.aborted) unregister();
      else signal.addEventListener('abort', unregister, { once: true });
    }

    return () => this.unregisterTool(name);
  }

  unregisterTool(name) {
    if (this._tools.has(name)) {
      this._tools.delete(name);
      if (typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent('modelcontext:toolunregistered', { detail: { name } })
        );
      }
      return true;
    }
    return false;
  }

  getTools() {
    return Array.from(this._tools.values()).map(({ name, description, inputSchema }) => ({
      name,
      description,
      inputSchema,
    }));
  }

  async executeTool(name, params = {}) {
    const tool = this._tools.get(name);
    if (!tool) {
      throw new Error(`WebMCP: Tool "${name}" is not registered.`);
    }
    try {
      const result = await tool.execute(params);
      if (result && typeof result === 'object' && Array.isArray(result.content)) {
        return result;
      }
      return {
        content: [
          {
            type: 'text',
            text: typeof result === 'string' ? result : JSON.stringify(result, null, 2),
          },
        ],
      };
    } catch (err) {
      return {
        isError: true,
        content: [
          {
            type: 'text',
            text: `Error executing WebMCP tool ${name}: ${err?.message || String(err)}`,
          },
        ],
      };
    }
  }
}

let polyfillInstance = null;

export function initWebMCP() {
  if (typeof window === 'undefined') {
    return new WebModelContext();
  }

  if (!polyfillInstance) {
    polyfillInstance = new WebModelContext();
  }

  // Bind to document.modelContext if not natively present
  if (typeof document !== 'undefined' && !('modelContext' in document)) {
    try {
      Object.defineProperty(document, 'modelContext', {
        value: polyfillInstance,
        configurable: true,
        writable: true,
      });
    } catch {
      document.modelContext = polyfillInstance;
    }
  }

  // Also bind to navigator.modelContext for broader compatibility
  if (typeof navigator !== 'undefined' && !('modelContext' in navigator)) {
    try {
      Object.defineProperty(navigator, 'modelContext', {
        value: polyfillInstance,
        configurable: true,
        writable: true,
      });
    } catch {
      navigator.modelContext = polyfillInstance;
    }
  }

  return (typeof document !== 'undefined' && document.modelContext) || polyfillInstance;
}

export function registerWebMCPCommerceTools({ onSearch, onGetPlan, onCheckout }) {
  const modelContext = initWebMCP();
  const controller = new AbortController();
  const unregisterCallbacks = [];
  const register = (tool) => {
    try {
      const unregister = modelContext.registerTool(tool, { signal: controller.signal });
      if (typeof unregister === 'function') unregisterCallbacks.push(unregister);
      else if (unregister && typeof unregister.catch === 'function') {
        unregister.catch((error) => {
          if (!controller.signal.aborted) console.error('WebMCP tool registration failed:', error);
        });
      }
    } catch (error) {
      if (!controller.signal.aborted) console.error('WebMCP tool registration failed:', error);
    }
  };

  if (onSearch) {
    register({
      name: 'search_products',
      description: 'Search live retailer catalogs and run purchase research on Artha for products matching brief constraints, budget, and location.',
      inputSchema: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'Product brief or search query' },
          budget: { type: 'number', description: 'Maximum budget in INR' },
          location: { type: 'string', description: 'Destination city or 6-digit pincode' },
        },
        required: ['query'],
      },
      execute: async ({ query, budget, location }) => {
        const res = await onSearch({ query, budget, location });
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify(res, null, 2),
            },
          ],
        };
      },
    });
  }

  if (onGetPlan) {
    register({
      name: 'get_purchase_plan',
      description: 'Retrieve current shortlist, recommended purchase decision, pricing analysis, and retailer handoffs from Artha.',
      inputSchema: {
        type: 'object',
        properties: {},
      },
      execute: async () => {
        const plan = await onGetPlan();
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify(plan, null, 2),
            },
          ],
        };
      },
    });
  }

  if (onCheckout) {
    register({
      name: 'agentic_checkout',
      description: 'Execute instant conversational or programmatic checkout for a product in the shortlist.',
      inputSchema: {
        type: 'object',
        properties: {
          productId: { type: 'string', description: 'ID of product to order, or leave empty for the recommended product' },
        },
      },
      execute: async ({ productId } = {}) => {
        const orderRes = await onCheckout({ productId });
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify(orderRes, null, 2),
            },
          ],
        };
      },
    });
  }

  return () => {
    controller.abort();
    unregisterCallbacks.forEach((cb) => {
      try {
        if (typeof cb === 'function') cb();
      } catch {}
    });
  };
}
