/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // The browser only ever talks to the Vite origin; API calls are forwarded
    // to FastAPI so no CORS setup is needed in development.
    proxy: {
      '/api': backendUrl,
    },
  },
  test: {
    environment: 'jsdom',
  },
})
