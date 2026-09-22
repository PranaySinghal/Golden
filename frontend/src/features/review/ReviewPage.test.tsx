import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ReviewPage } from './ReviewPage'
import {
  aiResponse,
  askIssue,
  comparison,
  dataset,
  issue,
  issueList,
  jsonResponse,
  preview,
  recipe,
  recipeOutcome,
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

function renderPage(onStartOver = () => {}, onDataset = () => {}, file = FILE) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ReviewPage dataset={file} onDataset={onDataset} onStartOver={onStartOver} />
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
const AI = `GET /api/datasets/${FILE.id}/ai`

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

    // The figure is on the card and in the story over it; either proves the tab switched.
    expect(await screen.findAllByText('83,151.41')).not.toHaveLength(0)
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

  it('says nothing about AI when no model service is configured', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [AI]: () => jsonResponse(200, aiResponse({ status: 'off' })),
    })

    renderPage()
    await screen.findByRole('heading', { name: /Suggested/ })

    await waitFor(() => expect(screen.queryByText(/Suggested by AI/)).toBeNull())
    expect(screen.queryByText(/couldn.t be fetched/)).toBeNull()
  })

  it('marks a card a model suggested, and leaves it to be reviewed', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [AI]: () =>
        jsonResponse(
          200,
          aiResponse({
            added: [
              issue({
                id: 'issue-ai',
                source: 'ai',
                title: '"Notes" holds two things in one column',
              }),
            ],
          }),
        ),
    })

    renderPage()

    expect(await screen.findByText('Suggested by AI')).toBeTruthy()
    const card = screen
      .getByRole('heading', { name: /holds two things/ })
      .closest('article') as HTMLElement
    expect(within(card).getByRole('button', { name: 'Accept' })).toBeTruthy()
  })

  it('shows better wording in place of the template', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [AI]: () =>
        jsonResponse(
          200,
          aiResponse({
            issue_copy: {
              'issue-likely': {
                title: 'Some names have stray spaces around them',
                explanation: 'Those spaces split one name into two groups when you count.',
              },
            },
          }),
        ),
    })

    renderPage()

    expect(await screen.findByText('Some names have stray spaces around them')).toBeTruthy()
    expect(screen.queryByText(/38 names have extra spaces/)).toBeNull()
  })

  it('mentions a failure quietly, without losing anything', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [AI]: () =>
        jsonResponse(
          200,
          aiResponse({ status: 'failed', note: "Extra suggestions couldn't be fetched just now." }),
        ),
    })

    renderPage()

    expect(await screen.findByText(/Extra suggestions couldn.t be fetched/)).toBeTruthy()
    expect(screen.getByRole('heading', { name: /Needs your decision/ })).toBeTruthy()
    expect(screen.getByRole('heading', { name: /Suggested/ })).toBeTruthy()
  })

  it('carries on when the AI request itself fails', async () => {
    mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [AI]: () => jsonResponse(500, { code: 'unknown_error', message: 'boom' }),
    })

    renderPage()

    expect(await screen.findByRole('heading', { name: /Suggested/ })).toBeTruthy()
    expect(screen.queryByText('boom')).toBeNull()
  })

  it('offers a way back to a different file', async () => {
    const startOver = vi.fn()
    mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })

    renderPage(startOver)
    fireEvent.click(await screen.findByRole('button', { name: 'Upload a different file' }))

    expect(startOver).toHaveBeenCalled()
  })

  it('shows how the file was read behind the columns toggle', async () => {
    mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })
    renderPage()
    await screen.findByRole('heading', { name: /Suggested/ })

    expect(screen.queryByRole('checkbox', { name: 'First row has column names' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'See the columns' }))

    expect(screen.getByRole('checkbox', { name: 'First row has column names' })).toBeTruthy()
    expect(screen.getByRole('row', { name: /Salary/ })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Hide columns' }))
    expect(screen.queryByRole('checkbox', { name: 'First row has column names' })).toBeNull()
  })

  it('looks at the file afresh after it is read again', async () => {
    // The server keeps the id but throws the session away, so nothing cached
    // under that id may be reused — including a reply it already has in hand.
    const reread = dataset({ header_mode: 'data', header_detected: false, row_count: 1021 })
    let issueCalls = 0
    const onDataset = vi.fn()
    // The recipe already has a step, so the panel checks before throwing it away.
    vi.stubGlobal('confirm', vi.fn(() => true))
    mockApi({
      [ISSUES]: () => {
        issueCalls += 1
        return jsonResponse(200, issueList())
      },
      [`POST /api/datasets/${FILE.id}/reingest`]: () => jsonResponse(200, reread),
    })
    renderPage(() => {}, onDataset)
    await screen.findByRole('heading', { name: /Suggested/ })
    fireEvent.click(screen.getByRole('button', { name: 'See the columns' }))
    expect(issueCalls).toBe(1)

    fireEvent.click(screen.getByRole('checkbox', { name: 'First row has column names' }))

    await waitFor(() => expect(onDataset).toHaveBeenCalledWith(reread))
    await waitFor(() => expect(issueCalls).toBe(2))
  })

  it('says so when the file has column names but no rows', async () => {
    mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })

    renderPage(() => {}, () => {}, dataset({ row_count: 0 }))

    expect(await screen.findByText(/has column names but no rows yet/)).toBeTruthy()
  })
  it('says what came of steps that arrived with the file', async () => {
    mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })

    renderPage(
      () => {},
      () => {},
      dataset({ recipe_outcome: recipeOutcome({ steps_applied: 7 }) }),
    )

    const said = await screen.findByRole('status')
    expect(said.textContent).toContain('7 steps')
    expect(said.textContent).toContain('last-month.csv')
  })

  it('gives every reason steps could not be used', async () => {
    mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })
    const refused = recipeOutcome({
      applied: false,
      steps_applied: 0,
      problems: ['This recipe needs a column called "Salary".', 'And one called "Join_Date".'],
    })

    renderPage(() => {}, () => {}, dataset({ recipe_outcome: refused }))

    const alert = await screen.findByRole('alert')
    expect(within(alert).getAllByRole('listitem')).toHaveLength(2)
    expect(alert.textContent).toContain('nothing was changed')
  })

  it('uses steps from a file, once the warning is accepted', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    const replayed = recipe({ steps: [step({ id: 'from-file', description: 'Trim spaces' })] })
    const fetchMock = mockApi({
      [ISSUES]: () => jsonResponse(200, issueList()),
      [`POST /api/datasets/${FILE.id}/recipe/replay`]: () =>
        jsonResponse(200, { outcome: recipeOutcome({ steps_applied: 1 }), recipe: replayed }),
    })
    renderPage()
    await screen.findByRole('heading', { name: /Suggested/ })

    fireEvent.change(screen.getByLabelText('Choose a saved recipe file'), {
      target: { files: [new File(['{}'], 'last-month.tidylab.json')] },
    })

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).endsWith('/recipe/replay')),
      ).toBe(true),
    )
    expect((await screen.findByRole('status')).textContent).toContain('1 step')
  })

  it('leaves the recipe alone when the warning is turned down', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    const fetchMock = mockApi({ [ISSUES]: () => jsonResponse(200, issueList()) })
    renderPage()
    await screen.findByRole('heading', { name: /Suggested/ })

    fireEvent.change(screen.getByLabelText('Choose a saved recipe file'), {
      target: { files: [new File(['{}'], 'last-month.tidylab.json')] },
    })

    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/recipe/replay'))).toBe(false)
  })
})
