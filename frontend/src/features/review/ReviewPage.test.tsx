import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReviewPage } from './ReviewPage'
import {
  askIssue,
  comparison,
  dataset,
  issue,
  issueList,
  jsonResponse,
  preview,
  recipe,
  step,
} from '../../test/fixtures'

type Handler = (init?: RequestInit) => Response | Promise<Response>

const FILE = dataset()

function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(input)}`
    const handler = routes[key] ?? routes[key.split('?')[0]]
    if (!handler) throw new Error(`Unexpected request: ${key}`)
    return handler(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage(onStartOver = () => {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ReviewPage dataset={FILE} onStartOver={onStartOver} />
    </QueryClientProvider>,
  )
}

const ISSUES = `GET /api/datasets/${FILE.id}/issues`
const ACCEPT_LIKELY = `POST /api/datasets/${FILE.id}/issues/issue-likely/accept`
const REJECT_LIKELY = `POST /api/datasets/${FILE.id}/issues/issue-likely/reject`
const ACCEPT_ASK = `POST /api/datasets/${FILE.id}/issues/issue-ask/accept`
const PREVIEW = `GET /api/datasets/${FILE.id}/preview`
const TOGGLE = `PATCH /api/datasets/${FILE.id}/recipe/steps/step-1`
const REMOVE = `DELETE /api/datasets/${FILE.id}/recipe/steps/step-1`
const UNDO = `POST /api/datasets/${FILE.id}/recipe/undo`
const COMPARE = `GET /api/datasets/${FILE.id}/compare`

function card(title: string | RegExp): HTMLElement {
  return screen.getByRole('heading', { name: title }).closest('article') as HTMLElement
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ReviewPage', () => {
  it('says what it is doing while it looks through the file', () => {
    mockApi({ [ISSUES]: () => new Promise(() => {}) })

    renderPage()

    expect(screen.getByRole('status').textContent).toContain('Looking through your file')
  })

  it('explains a failure and offers to try again', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(404, { code: 'dataset_not_found', message: 'File has expired.' }),
    })

    renderPage()

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('File has expired.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('says so when a file is already tidy', async () => {
    mockApi({
      [ISSUES]: () =>
        jsonResponse(200, issueList({ issues: [], counts: {}, needs_decision: 0 })),
    })

    renderPage()

    expect(await screen.findByText(/already tidy/)).toBeTruthy()
  })

  it('groups what it found and counts what needs deciding', async () => {
    mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })

    renderPage()

    expect(await screen.findByRole('heading', { name: /Needs your decision/ })).toBeTruthy()
    expect(screen.getByRole('heading', { name: /Suggested/ })).toBeTruthy()
    expect(screen.getByText(/1 to decide/)).toBeTruthy()
  })

  it('shows what is already done without asking', async () => {
    mockApi({
      [ISSUES]: () =>
        jsonResponse(
          200,
          issueList({
            issues: [issue({ id: 'issue-safe', tier: 'safe', state: 'applied', ask: null })],
          }),
        ),
    })

    renderPage()

    expect(await screen.findByRole('heading', { name: /Already fixed/ })).toBeTruthy()
    expect(screen.getByText('Done')).toBeTruthy()
  })

  it('accepts a suggestion and follows the new recipe', async () => {
    let accepted = false
    const applied = recipe({ steps: [step(), step({ id: 'step-2' })], can_undo: true })
    mockApi({
      [ISSUES]: () =>
        jsonResponse(
          200,
          accepted
            ? issueList({ issues: [issue({ state: 'applied' })], recipe: applied })
            : issueList(),
        ),
      [ACCEPT_LIKELY]: () => {
        accepted = true
        return jsonResponse(200, applied)
      },
    })

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }))

    expect(await screen.findByText('Done')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Undo last change' }).hasAttribute('disabled')).toBe(
      false,
    )
  })

  it('only sends an answer once one is picked', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [ACCEPT_ASK]: () => jsonResponse(200, recipe({ can_undo: true })),
    })

    renderPage()
    await screen.findByRole('heading', { name: /Needs your decision/ })
    const question = card(/N\/A/)
    const apply = within(question).getByRole('button', { name: 'Use this answer' })
    expect(apply.hasAttribute('disabled')).toBe(true)

    fireEvent.click(within(question).getByRole('radio', { name: /Treat them as zero/ }))

    await waitFor(() => expect(apply.hasAttribute('disabled')).toBe(false))
  })

  it('shows the answer that was chosen', async () => {
    mockApi({
      [ISSUES]: () =>
        jsonResponse(
          200,
          issueList({
            issues: [askIssue({ state: 'applied', chosen_choice_id: 'zero' })],
            needs_decision: 0,
          }),
        ),
    })

    renderPage()

    expect(await screen.findByText('Treat them as zero')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Change my answer' })).toBeTruthy()
  })

  it('reports a failed action on the card it came from', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [ACCEPT_LIKELY]: () =>
        jsonResponse(422, { code: 'invalid_step', message: "This step can't run." }),
    })

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }))

    const failing = await screen.findByText("This step can't run.")
    expect(failing).toBeTruthy()
  })

  it('turns a suggestion down', async () => {
    let rejected = false
    mockApi({
      [ISSUES]: () =>
        jsonResponse(
          200,
          rejected ? issueList({ issues: [issue({ state: 'rejected' })] }) : issueList(),
        ),
      [REJECT_LIKELY]: () => {
        rejected = true
        return jsonResponse(200, recipe())
      },
    })

    renderPage()
    await screen.findByRole('heading', { name: /Suggested/ })
    fireEvent.click(within(card(/extra spaces/)).getByRole('button', { name: 'Not this one' }))

    expect(await screen.findByText('Not doing this')).toBeTruthy()
  })

  it('only asks for example rows when they are wanted', async () => {
    const fetchMock = mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [PREVIEW]: () => jsonResponse(200, preview()),
    })

    renderPage()
    await screen.findByRole('heading', { name: /Suggested/ })
    const suggestion = card(/extra spaces/)
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/preview'))).toBe(false)

    fireEvent.click(within(suggestion).getByRole('button', { name: 'Show me' }))

    expect(await within(suggestion).findByText(/38 rows change/)).toBeTruthy()
    // The name as it is now, and as it would be after trimming.
    expect(within(suggestion).getAllByText('Ann')).toHaveLength(2)
  })

  it('marks rows that would be set aside', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [PREVIEW]: () =>
        jsonResponse(
          200,
          preview({
            rows: [
              {
                row_id: 9,
                cells: { First_Name: { before: 'Ann', after: 'Ann', changed: false } },
                set_aside: true,
              },
            ],
            changed_rows: 1,
            set_aside_rows: 1,
          }),
        ),
    })

    renderPage()
    await screen.findByRole('heading', { name: /Suggested/ })
    fireEvent.click(within(card(/extra spaces/)).getByRole('button', { name: 'Show me' }))

    expect(await screen.findByText('set aside')).toBeTruthy()
  })

  it('shows each step in the recipe with what it did', async () => {
    mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })

    renderPage()

    const panel = await screen.findByRole('complementary', { name: "What we're doing" })
    expect(within(panel).getByText('Read "Salary" as numbers')).toBeTruthy()
    expect(within(panel).getByText('24 values changed')).toBeTruthy()
    expect(within(panel).getByText('1,020 rows kept')).toBeTruthy()
  })

  it('explains a step that cannot run instead of its counts', async () => {
    mockApi({
      [ISSUES]: () =>
        jsonResponse(
          200,
          issueList({
            recipe: recipe({
              steps: [
                step({
                  status: 'blocked',
                  reason: 'It depends on an earlier step that\'s turned off.',
                }),
              ],
            }),
          }),
        ),
    })

    renderPage()

    expect(await screen.findByText(/depends on an earlier step/)).toBeTruthy()
  })

  it('turns a step off', async () => {
    const fetchMock = mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [TOGGLE]: () => jsonResponse(200, recipe({ steps: [step({ enabled: false })] })),
    })

    renderPage()
    fireEvent.click(await screen.findByRole('checkbox', { name: 'Use this step' }))

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ enabled: false })
    })
  })

  it('removes a step', async () => {
    const fetchMock = mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [REMOVE]: () => jsonResponse(200, recipe({ steps: [] })),
    })

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /^Remove:/ }))

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'DELETE')).toBe(true)
    })
  })

  it('only offers undo when there is something to undo', async () => {
    const fetchMock = mockApi({
      [ISSUES]: () => jsonResponse(200, issueList({ recipe: recipe({ can_undo: true }) })),
      [UNDO]: () => jsonResponse(200, recipe({ can_undo: false })),
    })

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Undo last change' }))

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/undo'))).toBe(true)
    })
  })

  it('leaves the comparison alone until it is asked for', async () => {
    const fetchMock = mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [COMPARE]: () => jsonResponse(200, comparison()),
    })

    renderPage()
    await screen.findByRole('heading', { name: /Suggested/ })

    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/compare'))).toBe(false)
  })

  it('shows what changed on the other tab, with the recipe still in view', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [COMPARE]: () => jsonResponse(200, comparison()),
    })

    renderPage()
    fireEvent.click(await screen.findByRole('tab', { name: 'What changed' }))

    expect(await screen.findByText('83,151.41')).toBeTruthy()
    const panel = screen.getByRole('complementary', { name: "What we're doing" })
    expect(within(panel).getByText('Read "Salary" as numbers')).toBeTruthy()
    expect(screen.queryByRole('heading', { name: /Suggested/ })).toBeNull()
  })

  it('offers both downloads', async () => {
    const fetchMock = mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [`GET /api/datasets/${FILE.id}/export`]: () =>
        new Response('id,name\n1,Ann\n', {
          status: 200,
          headers: {
            'Content-Type': 'text/csv',
            'Content-Disposition': "attachment; filename*=UTF-8''people%20(tidied).csv",
          },
        }),
    })
    const clicks: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicks.push(this.download)
    })
    vi.stubGlobal('URL', { ...URL, createObjectURL: () => 'blob:x', revokeObjectURL: () => {} })

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Download cleaned file' }))

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes('format=csv'))).toBe(true)
    })
    await waitFor(() => expect(clicks).toEqual(['people (tidied).csv']))
  })

  it('says so when a download fails', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [`GET /api/datasets/${FILE.id}/export`]: () =>
        jsonResponse(404, { code: 'dataset_not_found', message: 'File has expired.' }),
    })

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Download the steps' }))

    expect(await screen.findByText('File has expired.')).toBeTruthy()
  })

  it('offers a way back to a different file', async () => {
    const startOver = vi.fn()
    mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })

    renderPage(startOver)
    fireEvent.click(await screen.findByRole('button', { name: 'Upload a different file' }))

    expect(startOver).toHaveBeenCalled()
  })
})
