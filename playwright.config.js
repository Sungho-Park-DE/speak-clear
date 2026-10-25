import { defineConfig } from '@playwright/test';

// tests/helpers.js swaps the mic for a 220 Hz signal inside the page.
// (Real getUserMedia in installed Chrome stops at the macOS microphone permission prompt.)
export default defineConfig({
  testDir: 'tests',
  timeout: 30_000,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8791',
    channel: process.env.PW_CHANNEL || 'chrome',   // installed Chrome; bundled Chromium with PW_CHANNEL=chromium
    launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] },
  },
  webServer: {
    command: 'python3 -m http.server 8791 --bind 127.0.0.1',
    url: 'http://127.0.0.1:8791/voice-practice.html',
    reuseExistingServer: true,
  },
});
