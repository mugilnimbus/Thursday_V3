import { defineConfig } from '@playwright/test';

declare const process: { env: Record<string, string | undefined> };

// Browser checks against the built dashboard with the gateway mocked (see e2e/gateway.ts).
// Uses Playwright's Chromium, or any Chromium given in THURSDAY_E2E_CHROMIUM (a chrome.exe path).
export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  fullyParallel: true,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    launchOptions: {
      executablePath: process.env.THURSDAY_E2E_CHROMIUM || undefined,
      // A fake microphone and auto-granted permission, so the voice test needs no hardware.
      args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required'],
    },
  },
  webServer: { command: 'npx vite preview --host 127.0.0.1 --port 4173 --strictPort', url: 'http://127.0.0.1:4173', reuseExistingServer: true },
});
