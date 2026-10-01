import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';

declare const process: { env: Record<string, string | undefined> };

// Dev server proxies the API to the gateway's localhost listener. The gateway checks Host and
// Origin, so the proxy presents itself as the gateway's own origin.
const gateway = process.env.THURSDAY_GATEWAY ?? 'http://127.0.0.1:8700';

export default defineConfig({
  plugins: [svelte()],
  assetsInclude: ['**/*.bin'], // the voice field's face cloud
  build: { target: 'es2022', sourcemap: false, assetsInlineLimit: 0 },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/v1': { target: gateway, ws: true, changeOrigin: true, headers: { origin: gateway } },
    },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
});
