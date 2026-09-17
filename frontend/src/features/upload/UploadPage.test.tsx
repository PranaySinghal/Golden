import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { column, dataset, jsonResponse } from '../../test/fixtures'
import { UploadPage } from './UploadPage'

type Handler = (init?: RequestInit) => Response | Promise<Response>

function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(input)}`
    const handler = routes[key]
    if (!handler) throw new Error(`Unexpected request: ${key}`)
    return handler(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const LIMITS: Record<string, Handler> = {
  'GET /api/upload-limits': () => jsonResponse(200, { max_upload_bytes: 50 * 1024 * 1024 }),
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <UploadPage />
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

describe('UploadPage', () => {
  it('starts with a drop zone showing the size limit', async () => {
    mockApi(LIMITS)

    renderPage()

    expect(screen.getByText('Drop a CSV or Excel file here')).toBeTruthy()
    expect(await screen.findByText(/up to 50 MB/)).toBeTruthy()
  })

  it('uploads a file, shows progress, then the summary and column table', async () => {
    let finish: (response: Response) => void = () => {}
    const fetchMock = mockApi({
      ...LIMITS,
      'POST /api/datasets': () => new Promise<Response>((resolve) => (finish = resolve)),
    })
    renderPage()

    chooseFile(new File(['Email\na@x.com\n'], 'people.csv', { type: 'text/csv' }))

    expect(await screen.findByText('Reading your file…')).toBeTruthy()
    const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/datasets')!
    const body = init?.body
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get('file')).toBeInstanceOf(File)

    finish(jsonResponse(201, dataset()))

    expect(await screen.findByRole('heading', { name: 'people.csv' })).toBeTruthy()
    expect(screen.getByText('1,020 rows · 2 columns')).toBeTruthy()
    const rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(3)
    const salary = within(rows[2])
    expect(salary.getByText('Number')).toBeTruthy()
    expect(salary.getByText('98%')).toBeTruthy()
    expect(salary.getByText('979')).toBeTruthy()
    expect(salary.getByText('50047.32')).toBeTruthy()
    expect(salary.getByText('– 119971.65')).toBeTruthy()
    // Only the first three examples are shown.
    expect(within(rows[1]).queryByText('d@x.com')).toBeNull()
  })

  it('explains each kind in a note tied to its button', async () => {
    mockApi({ ...LIMITS, 'POST /api/datasets': () => jsonResponse(201, dataset()) })
    renderPage()
    chooseFile(new File(['x'], 'people.csv'))

    const button = await screen.findByRole('button', { name: 'Why Salary is Number' })
    const note = document.getElementById(button.getAttribute('aria-describedby')!)

    expect(note?.textContent).toContain('can be added up and averaged')
    expect(note?.getAttribute('role')).toBe('tooltip')
    const isOpen = () => note?.classList.contains('infotip__bubble--open')
    expect(isOpen()).toBe(false)

    fireEvent.mouseEnter(button)
    expect(isOpen()).toBe(true)
    fireEvent.mouseLeave(button)
    expect(isOpen()).toBe(false)

    fireEvent.focus(button)
    expect(isOpen()).toBe(true)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(isOpen()).toBe(false)
  })

  it('labels an all-blank column as empty and explains why', async () => {
    const blank = column({
      name: 'Notes',
      semantic_role: 'text',
      non_blank_count: 0,
      fill_rate: 0,
      distinct_count: 0,
      sample_values: [],
      role_note: "All 3 rows are empty in this column, so we can't tell what it's meant to hold.",
    })
    mockApi({
      ...LIMITS,
      'POST /api/datasets': () => jsonResponse(201, dataset({ columns: [blank], column_count: 1 })),
    })
    renderPage()
    chooseFile(new File(['x'], 'people.csv'))

    const button = await screen.findByRole('button', { name: 'Why Notes is empty' })
    expect(screen.getByText('Empty')).toBeTruthy()
    expect(screen.getByText('No values')).toBeTruthy()
    expect(document.getElementById(button.getAttribute('aria-describedby')!)?.textContent).toMatch(
      /All 3 rows are empty/,
    )
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
    renderPage()

    chooseFile(new File(['%PDF'], 'report.pdf'))

    expect((await screen.findByRole('alert')).textContent).toContain("We can't open .pdf files yet")
    expect(screen.getByText('Drop a CSV or Excel file here')).toBeTruthy()
  })

  it('refuses a file over the limit without uploading it', async () => {
    const fetchMock = mockApi({
      'GET /api/upload-limits': () => jsonResponse(200, { max_upload_bytes: 10 }),
    })
    renderPage()
    await screen.findByText(/up to 1 KB/)

    chooseFile(new File(['more than ten bytes'], 'big.csv'))

    expect((await screen.findByRole('alert')).textContent).toContain('over the 1 KB limit')
    expect(fetchMock.mock.calls.some(([url]) => url === '/api/datasets')).toBe(false)
  })

  it('re-reads the file when "First row has column names" is unticked', async () => {
    const fetchMock = mockApi({
      ...LIMITS,
      'POST /api/datasets': () => jsonResponse(201, dataset()),
      'POST /api/datasets/abc123/reingest': () =>
        jsonResponse(
          200,
          dataset({
            header_mode: 'data',
            header_detected: false,
            row_count: 1021,
            columns: [column({ name: 'column_1' })],
            column_count: 1,
          }),
        ),
    })
    renderPage()
    chooseFile(new File(['x'], 'people.csv'))

    const checkbox = await screen.findByRole('checkbox', { name: 'First row has column names' })
    expect((checkbox as HTMLInputElement).checked).toBe(true)
    fireEvent.click(checkbox)

    expect(await screen.findByText('1,021 rows · 1 column')).toBeTruthy()
    expect(screen.getByRole('row', { name: /column_1/ })).toBeTruthy()
    const [, init] = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/reingest'))!
    expect(JSON.parse(String(init?.body))).toEqual({ sheet: null, header: 'data' })
  })

  it('offers a sheet picker only for Excel files with several sheets', async () => {
    const workbook = dataset({
      filename: 'book.xlsx',
      format: 'xlsx',
      sheet_name: 'Summary',
      available_sheets: ['Summary', 'Details'],
    })
    const fetchMock = mockApi({
      ...LIMITS,
      'POST /api/datasets': () => jsonResponse(201, workbook),
      'POST /api/datasets/abc123/reingest': () =>
        jsonResponse(200, { ...workbook, sheet_name: 'Details' }),
    })
    renderPage()
    chooseFile(new File(['x'], 'book.xlsx'))

    const picker = await screen.findByRole('combobox', { name: 'Sheet' })
    fireEvent.change(picker, { target: { value: 'Details' } })

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/reingest'))).toBe(true),
    )
    expect(await screen.findByText(/sheet “Details”/)).toBeTruthy()
  })

  it('has no sheet picker for CSV files', async () => {
    mockApi({ ...LIMITS, 'POST /api/datasets': () => jsonResponse(201, dataset()) })
    renderPage()
    chooseFile(new File(['x'], 'people.csv'))

    await screen.findByRole('heading', { name: 'people.csv' })
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('shows a note for a file with column names but no rows', async () => {
    mockApi({
      ...LIMITS,
      'POST /api/datasets': () => jsonResponse(201, dataset({ row_count: 0 })),
    })
    renderPage()
    chooseFile(new File(['x'], 'people.csv'))

    expect(await screen.findByText(/has column names but no rows yet/)).toBeTruthy()
  })

  it('goes back to the drop zone for a different file', async () => {
    mockApi({ ...LIMITS, 'POST /api/datasets': () => jsonResponse(201, dataset()) })
    renderPage()
    chooseFile(new File(['x'], 'people.csv'))

    fireEvent.click(await screen.findByRole('button', { name: 'Upload a different file' }))

    expect(screen.getByText('Drop a CSV or Excel file here')).toBeTruthy()
  })

  it('tells the user when the server is unreachable', async () => {
    mockApi({ 'GET /api/upload-limits': () => new Response('', { status: 502 }) })

    renderPage()

    expect((await screen.findByRole('alert')).textContent).toMatch(/couldn't reach the server/)
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })
})
