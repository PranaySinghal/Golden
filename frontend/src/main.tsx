import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { ApiError } from './api/client'
import App from './App.tsx'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A file we can't find or a request we got wrong won't come good by asking
      // again; only a connection problem is worth a second try.
      retry: (failures, error) =>
        error instanceof ApiError && (error.status === 0 || error.status >= 500)
          ? failures < 2
          : false,
    },
  },
})

const root = document.getElementById('root')
if (!root) {
  throw new Error('Missing #root element in index.html')
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
