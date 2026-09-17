import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { jsonResponse } from './test/fixtures'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows the TidyLab name, the tagline, and the upload screen', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(200, { max_upload_bytes: 50 * 1024 * 1024 })),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    )

    expect(screen.getByRole('heading', { level: 1, name: 'TidyLab' })).toBeTruthy()
    expect(screen.getByText('Tidy your data. See what it was hiding.')).toBeTruthy()
    expect(await screen.findByText(/up to 50 MB/)).toBeTruthy()
  })
})
