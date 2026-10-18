import { defineConfig } from '@playwright/test';

// 마이크는 tests/helpers.js가 페이지 안에서 220 Hz 신호로 바꿔 끼운다.
// (설치된 Chrome에 진짜 getUserMedia를 쓰면 macOS 마이크 권한 단계에서 멈춘다)
export default defineConfig({
  testDir: 'tests',
  timeout: 30_000,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8791',
    channel: process.env.PW_CHANNEL || 'chrome',   // 설치된 Chrome 사용. 번들 Chromium은 PW_CHANNEL=chromium
    launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] },
  },
  webServer: {
    command: 'python3 -m http.server 8791 --bind 127.0.0.1',
    url: 'http://127.0.0.1:8791/voice-practice.html',
    reuseExistingServer: true,
  },
});
