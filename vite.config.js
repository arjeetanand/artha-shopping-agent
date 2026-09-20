import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const port = env.SHOPPINGHELP_PORT || '8000';
  const apiTarget = process.env.SHOPPINGHELP_API_TARGET || env.SHOPPINGHELP_API_TARGET || `http://127.0.0.1:${port}`;

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': apiTarget,
      },
    },
  };
});
