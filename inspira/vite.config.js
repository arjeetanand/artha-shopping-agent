import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { createApiHandler } from './server/api.mjs';

function inspiraApiPlugin() {
  return {
    name: 'inspira-local-api',
    configureServer(server) {
      server.middlewares.use('/api', createApiHandler());
    },
  };
}

export default defineConfig({
  plugins: [react(), inspiraApiPlugin()],
  server: {
    port: 5173,
  },
});
