import { defineConfig } from '@playwright/test'

const FRONTEND_PORT = 5273
const BACKEND_PORT = 8100

/**
 * One end-to-end run, against servers this config starts itself, so the whole
 * flow is one command. The backend runs with no model service configured: the
 * app has to be complete without one.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `uv run --directory ../backend uvicorn app.main:app --port ${BACKEND_PORT}`,
      url: `http://localhost:${BACKEND_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
      env: { LLM_PROVIDER: 'none' },
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: !process.env.CI,
      // Vite forwards /api to whichever backend this run started.
      env: { BACKEND_URL: `http://127.0.0.1:${BACKEND_PORT}` },
      timeout: 60_000,
    },
  ],
})
