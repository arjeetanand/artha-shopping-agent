import test from 'node:test';
import assert from 'node:assert/strict';
import { WebModelContext, registerWebMCPCommerceTools } from '../src/lib/webmcp.js';

test('WebMCP: registers and executes commerce tools according to specification', async () => {
  const context = new WebModelContext();

  const cleanup = registerWebMCPCommerceTools({
    onSearch: async ({ query }) => ({ results: [`Found ${query}`] }),
    onGetPlan: async () => ({ status: 'buy_now', topPick: 'Linen Shirt' }),
    onCheckout: async ({ productId }) => ({ orderId: 'ORD-12345', status: 'placed', product: productId || 'topPick' }),
  });

  // Verify registration on WebModelContext directly
  const unregister = context.registerTool({
    name: 'test_tool',
    description: 'Test description',
    inputSchema: { type: 'object', properties: { test: { type: 'string' } } },
    execute: async ({ test }) => ({ echo: test }),
  });

  const tools = context.getTools();
  assert.equal(tools.length, 1);
  assert.equal(tools[0].name, 'test_tool');

  const executionResult = await context.executeTool('test_tool', { test: 'hello world' });
  assert.deepEqual(executionResult, {
    content: [{ type: 'text', text: JSON.stringify({ echo: 'hello world' }, null, 2) }],
  });

  unregister();
  assert.equal(context.getTools().length, 0);

  // Calling an unregistered tool must throw
  await assert.rejects(
    async () => {
      await context.executeTool('test_tool', {});
    },
    /not registered/
  );
});

test('WebMCP: validates schema and required fields', () => {
  const context = new WebModelContext();

  assert.throws(() => {
    context.registerTool(null);
  }, /must be an object/);

  assert.throws(() => {
    context.registerTool({ name: '' });
  }, /tool name is required/);

  assert.throws(() => {
    context.registerTool({ name: 'no_execute' });
  }, /execute function is required/);
});

test('WebMCP: commerce tools integration handles checkout and plans', async () => {
  let searched = null;
  let planRequested = false;
  let checkedOut = null;

  const mockApp = {
    handleSearch: async (params) => {
      searched = params;
      return { count: 3, query: params.query };
    },
    handlePlan: async () => {
      planRequested = true;
      return { decision: 'buy_now', recommended: 'Item-A' };
    },
    handleCheckout: async ({ productId }) => {
      checkedOut = productId || 'default';
      return { id: 'ORD-999', total: 2499 };
    },
  };

  const context = new WebModelContext();

  // Register the 3 core tools
  context.registerTool({
    name: 'search_products',
    description: 'Search catalog',
    inputSchema: { type: 'object' },
    execute: mockApp.handleSearch,
  });

  context.registerTool({
    name: 'get_purchase_plan',
    description: 'Get plan',
    inputSchema: { type: 'object' },
    execute: mockApp.handlePlan,
  });

  context.registerTool({
    name: 'agentic_checkout',
    description: 'Agentic Checkout',
    inputSchema: { type: 'object' },
    execute: mockApp.handleCheckout,
  });

  const tools = context.getTools();
  assert.equal(tools.length, 3);
  assert.deepEqual(tools.map((t) => t.name).sort(), ['agentic_checkout', 'get_purchase_plan', 'search_products']);

  // Execute search
  const searchRes = await context.executeTool('search_products', { query: 'summer shoes' });
  assert.deepEqual(searched, { query: 'summer shoes' });
  assert.match(searchRes.content[0].text, /"count": 3/);

  // Execute plan
  const planRes = await context.executeTool('get_purchase_plan', {});
  assert.equal(planRequested, true);
  assert.match(planRes.content[0].text, /"decision": "buy_now"/);

  // Execute Agentic Checkout
  const checkoutRes = await context.executeTool('agentic_checkout', { productId: 'Item-A' });
  assert.equal(checkedOut, 'Item-A');
  assert.match(checkoutRes.content[0].text, /"id": "ORD-999"/);
});

test('WebMCP: native registrations clean up with AbortSignal and can be registered again', async () => {
  const names = new Map();
  const nativeContext = {
    registerTool(tool, { signal } = {}) {
      if (names.has(tool.name)) return Promise.reject(new DOMException('Duplicate tool name', 'InvalidStateError'));
      names.set(tool.name, tool);
      signal?.addEventListener('abort', () => names.delete(tool.name), { once: true });
      return Promise.resolve();
    },
  };
  const globals = ['window', 'document', 'navigator'].map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]);
  let cleanup = () => {};
  const handlers = {
    onSearch: async () => ({}),
    onGetPlan: async () => ({}),
    onCheckout: async () => ({}),
  };

  try {
    Object.defineProperty(globalThis, 'window', { configurable: true, value: {} });
    Object.defineProperty(globalThis, 'document', { configurable: true, value: { modelContext: nativeContext } });
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { modelContext: nativeContext } });

    cleanup = registerWebMCPCommerceTools(handlers);
    await Promise.resolve();
    assert.equal(names.size, 3);
    cleanup();
    assert.equal(names.size, 0);

    cleanup = registerWebMCPCommerceTools(handlers);
    await Promise.resolve();
    assert.equal(names.size, 3);
    cleanup();
    assert.equal(names.size, 0);
  } finally {
    cleanup();
    for (const [key, descriptor] of globals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
});
