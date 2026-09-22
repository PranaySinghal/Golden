import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { dataset, jsonResponse } from '../../test/fixtures'
import { mockApi, type Handler } from '../../test/mockApi'
import { UploadPanel } from './UploadPanel'

const LIMITS: Record<string, Handler> = {
  'GET /api/upload-limits': () => jsonResponse(200, { max_upload_bytes: 50 * 1024 * 1024 }),
}

function renderPanel(onUploaded: (summary: unknown) => void = () => {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <UploadPanel onUploaded={onUploaded} />
    </QueryClientProvider>,
  )
}

function chooseFile(file: File) {
  fireEvent.change(screen.getByLabelText('Choose a file to upload'), { target: { files: [file] } })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('UploadPanel', () => {
  it('starts with a drop zone showing the size limit and what it accepts', async () => {
    mockApi(LIMITS)

    renderPanel()

    expect(screen.getByText('Drop a CSV or Excel file here')).toBeTruthy()
    expect(await screen.findByText(/up to 50 MB/)).toBeTruthy()
    expect(screen.getByText(/\.csv · \.tsv · \.txt · \.xlsx · \.xlsm/)).toBeTruthy()
  })

  it('uploads a file, says it is reading it, then hands the file over', async () => {
    let finish: (response: Response) => void = () => {}
    const onUploaded = vi.fn()
    const fetchMock = mockApi({
      ...LIMITS,
      'POST /api/datasets': () => new Promise<Response>((resolve) => (finish = resolve)),
    })
    renderPanel(onUploaded)

    chooseFile(new File(['Email\na@x.com\n'], 'people.csv', { type: 'text/csv' }))

    expect(await screen.findByText('Reading your file…')).toBeTruthy()
    const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/datasets')!
    const body = init?.body
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get('file')).toBeInstanceOf(File)

    finish(jsonResponse(201, dataset()))

    await vi.waitFor(() => expect(onUploaded).toHaveBeenCalled())
    expect(onUploaded.mock.calls[0][0]).toMatchObject({ id: 'abc123', filename: 'people.csv' })
  })

  it('shows the server message when an upload is rejected', async () => {
    mockApi({
      ...LIMITS,
      'POST /api/datasets': () =>
        jsonResponse(415, {
          code: 'unsupported_format',
          message: "We can't open .pdf files yet. Please upload a CSV or Excel (.xlsx) file.",
        }),
    })
    renderPanel()

    chooseFile(new File(['%PDF'], 'report.pdf'))

    expect((await screen.findByRole('alert')).textContent).toContain("We can't open .pdf files yet")
    expect(screen.getByText('Drop a CSV or Excel file here')).toBeTruthy()
  })

  it('refuses a file over the limit without uploading it', async () => {
    const fetchMock = mockApi({
      'GET /api/upload-limits': () => jsonResponse(200, { max_upload_bytes: 10 }),
    })
    renderPanel()
    await screen.findByText(/up to 1 KB/)

    chooseFile(new File(['more than ten bytes'], 'big.csv'))

    expect((await screen.findByRole('alert')).textContent).toContain('over the 1 KB limit')
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/datasets')).toBe(false)
  })

  it('sends saved steps along with the file when some are attached', async () => {
    const fetchMock = mockApi({
      ...LIMITS,
      'POST /api/datasets': () => jsonResponse(201, dataset()),
    })
    renderPanel()

    fireEvent.change(screen.getByLabelText('Choose a saved recipe file'), {
      target: { files: [new File(['{}'], 'last-month.tidylab.json', { type: 'application/json' })] },
    })
    expect(screen.getByText('last-month.tidylab.json')).toBeTruthy()
    chooseFile(new File(['x'], 'people.csv'))

    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === '/api/datasets')).toBe(true),
    )
    const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/datasets')!
    const body = init?.body as FormData
    expect(body.get('file')).toBeInstanceOf(File)
    expect((body.get('recipe') as File).name).toBe('last-month.tidylab.json')
  })

  it('sends only the file when no steps are attached', async () => {
    const fetchMock = mockApi({
      ...LIMITS,
      'POST /api/datasets': () => jsonResponse(201, dataset()),
    })
    renderPanel()

    chooseFile(new File(['x'], 'people.csv'))

    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => url === '/api/datasets')).toBe(true),
    )
    const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/datasets')!
    expect((init!.body as FormData).get('recipe')).toBeNull()
  })

  it('lets attached steps be taken off again', async () => {
    mockApi(LIMITS)
    renderPanel()

    fireEvent.change(screen.getByLabelText('Choose a saved recipe file'), {
      target: { files: [new File(['{}'], 'last-month.tidylab.json')] },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))

    expect(screen.queryByText('last-month.tidylab.json')).toBeNull()
  })

  it('tells the user when the server is unreachable', async () => {
    mockApi({ 'GET /api/upload-limits': () => new Response('', { status: 502 }) })

    renderPanel()

    expect((await screen.findByRole('alert')).textContent).toMatch(/couldn't reach the server/)
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})
