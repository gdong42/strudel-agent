import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: ['mock-repl.spec.ts'],
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5273',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: [
    {
      command:
        'cd .. && rm -rf .e2e-workspace && mkdir -p .e2e-workspace/tracks && cp tracks/main.strudel.js .e2e-workspace/tracks/main.strudel.js && cd backend && STRUDEL_AGENT_ROOT=../.e2e-workspace UV_CACHE_DIR=../.uv-cache uv run uvicorn app.main:app --host 127.0.0.1 --port 8877',
      port: 8877,
      reuseExistingServer: false,
    },
    {
      command: 'cd .. && VITE_STRUDEL_REPL_MOCK=1 VITE_BACKEND_URL=http://127.0.0.1:8877 npm run dev -- --port 5273',
      port: 5273,
      reuseExistingServer: false,
    },
  ],
});
