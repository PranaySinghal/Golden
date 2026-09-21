import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse } from '../../test/fixtures'
import { mockApi } from '../../test/mockApi'
import { LandingPage } from './LandingPage'

function renderPage(maxBytes = 50 * 1024 * 1024) {
  mockApi({
    'GET /api/upload-limits': () => jsonResponse(200, { max_upload_bytes: maxBytes }),
  })
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <LandingPage onUploaded={() => {}} />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('LandingPage', () => {
  it('leads with the promise and the drop zone', () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1 }).textContent).toContain('Tidy your data.')
    expect(screen.getByText('Drop a CSV or Excel file here')).toBeTruthy()
  })

  it('has the sections the nav links to', () => {
    renderPage()

    expect(screen.getByRole('heading', { name: /It does the reading/ })).toBeTruthy()
    expect(screen.getByRole('heading', { name: /questions people ask/ })).toBeTruthy()
    expect(screen.getAllByRole('article')).toHaveLength(4)
  })

  it('answers the questions people ask before uploading', () => {
    renderPage()

    expect(screen.getByText('Do I need an account?')).toBeTruthy()
    expect(screen.getByText(/There is no sign-up and no login/)).toBeTruthy()
    expect(screen.getByText(/Not by default/)).toBeTruthy()
  })

  it('takes the size limit from the server rather than stating one', async () => {
    renderPage(10 * 1024 * 1024)

    expect(await screen.findByText(/The limit here is 10 MB a file/)).toBeTruthy()
    expect(screen.queryByText(/50 MB/)).toBeNull()
  })
})
