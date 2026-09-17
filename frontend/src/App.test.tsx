import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows a loading state, then the connected state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(200, { status: 'ok' })))

    renderApp()

    expect(screen.getByRole('heading', { name: 'Golden Analytics' })).toBeTruthy()
    expect(screen.getByText('Checking the connection…')).toBeTruthy()
    expect(await screen.findByText('Connected and ready.')).toBeTruthy()
  })

  it('shows the server message when the server returns an error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(413, { code: 'file_too_large', message: 'This file is too big.' }),
      ),
    )

    renderApp()

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('This file is too big.')).toBeTruthy()
  })

  it('treats a gateway error from the proxy as an unreachable server', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 502 })))

    renderApp()

    expect(await screen.findByText(/couldn't reach the server/)).toBeTruthy()
  })

  it('shows a generic message for other unexpected errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>', { status: 500 })))

    renderApp()

    expect(await screen.findByText(/Something went wrong on our side/)).toBeTruthy()
  })

  it('shows a friendly message when the server is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    renderApp()

    expect(await screen.findByText(/couldn't reach the server/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})
