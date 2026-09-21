import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { dataset, issueList, jsonResponse } from './test/fixtures'
import { mockApi, type Handler } from './test/mockApi'

const LIMITS: Record<string, Handler> = {
  'GET /api/upload-limits': () => jsonResponse(200, { max_upload_bytes: 50 * 1024 * 1024 }),
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

function chooseFile() {
  fireEvent.change(screen.getByLabelText('Choose a file to upload'), {
    target: { files: [new File(['x'], 'people.csv')] },
  })
}

beforeEach(() => {
  // scrollTo isn't implemented in jsdom, and going home calls it.
  vi.stubGlobal('scrollTo', vi.fn())
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  // The file is remembered in the address, so one test would otherwise decide
  // where the next one starts.
  window.history.replaceState(null, '', '/')
})

describe('App', () => {
  it('opens on the landing page, with the name and the drop zone', async () => {
    mockApi(LIMITS)

    renderApp()

    expect(within(screen.getByRole('banner')).getByText('Tidy Lab')).toBeTruthy()
    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('what it was hiding')
    expect(await screen.findByText(/up to 50 MB/)).toBeTruthy()
  })

  it('points the nav at sections that are really on the page', () => {
    mockApi(LIMITS)

    renderApp()

    expect(screen.getByRole('link', { name: 'Features' }).getAttribute('href')).toBe('#features')
    expect(screen.getByRole('link', { name: 'FAQ' }).getAttribute('href')).toBe('#faq')
    expect(document.getElementById('features')).toBeTruthy()
    expect(document.getElementById('faq')).toBeTruthy()
  })

  it('leaves the landing page for the file once one is uploaded', async () => {
    mockApi({
      ...LIMITS,
      'POST /api/datasets': () => jsonResponse(201, dataset()),
      'GET /api/datasets/abc123/issues': () => jsonResponse(200, issueList()),
      'GET /api/datasets/abc123/ai': () => jsonResponse(200, { status: 'off' }),
    })
    renderApp()

    chooseFile()

    expect(await screen.findByRole('heading', { level: 1, name: 'people.csv' })).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'FAQ' })).toBeNull()
    expect(new URLSearchParams(window.location.search).get('dataset')).toBe('abc123')
  })

  it('goes back to the landing page from the nav', async () => {
    mockApi({
      ...LIMITS,
      'POST /api/datasets': () => jsonResponse(201, dataset()),
      'GET /api/datasets/abc123/issues': () => jsonResponse(200, issueList()),
      'GET /api/datasets/abc123/ai': () => jsonResponse(200, { status: 'off' }),
    })
    renderApp()
    chooseFile()
    await screen.findByRole('heading', { level: 1, name: 'people.csv' })

    fireEvent.click(screen.getByRole('button', { name: 'Home' }))

    await waitFor(() => expect(screen.getByText('Drop a CSV or Excel file here')).toBeTruthy())
    expect(new URLSearchParams(window.location.search).get('dataset')).toBeNull()
  })
})
