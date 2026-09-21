import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { IssueView, StepView } from '../../api/client'
import {
  askIssue,
  breakdownCard,
  card,
  comparison,
  jsonResponse,
  preview,
  step,
  story,
} from '../../test/fixtures'
import { ComparePage } from './ComparePage'

type Handler = (init?: RequestInit) => Response | Promise<Response>

const DATASET = 'abc123'
const COMPARE = `GET /api/datasets/${DATASET}/compare`
const PREVIEW = `GET /api/datasets/${DATASET}/preview`

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

interface PageOptions {
  aiStory?: ReturnType<typeof story> | null
  recipeKey?: string
  steps?: StepView[]
  issues?: IssueView[]
  onChoose?: (issueId: string, choiceId: string) => void
  onHighlight?: (stepIds: string[]) => void
  onBackToReview?: () => void
}

function renderPage(options: PageOptions = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = render(
    <QueryClientProvider client={client}>
      <ComparePage
        datasetId={DATASET}
        recipeKey={options.recipeKey ?? 'key-1'}
        steps={options.steps ?? [step({ description: 'Replace "N/A" with "0" in "Salary"' })]}
        issues={options.issues ?? []}
        aiStory={options.aiStory ?? null}
        choosing={null}
        onChoose={options.onChoose ?? (() => {})}
        onHighlight={options.onHighlight ?? (() => {})}
        onBackToReview={options.onBackToReview ?? (() => {})}
      />
    </QueryClientProvider>,
  )
  return { ...view, client }
}

function answerCard(labelPart: string | RegExp): HTMLElement {
  return screen.getByRole('heading', { name: labelPart }).closest('article') as HTMLElement
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ComparePage', () => {
  it('says what it is doing while it works the answers out', () => {
    mockApi({ [COMPARE]: () => new Promise(() => {}) })

    renderPage()

    expect(screen.getByRole('status').textContent).toContain('Working out what changed')
  })

  it('explains a failure and offers to try again', async () => {
    mockApi({
      [COMPARE]: () => jsonResponse(500, { code: 'unknown_error', message: 'Something broke.' }),
    })

    renderPage()

    expect(await screen.findByText('Something broke.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('shows a before and after for a headline answer', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage()
    await screen.findByRole('heading', { name: /average "Salary"/ })
    const salary = answerCard(/average "Salary"/)

    expect(within(salary).getByText('85,155.06')).toBeTruthy()
    expect(within(salary).getByText('83,151.41')).toBeTruthy()
    expect(within(salary).getByText('2,003.65 lower (2.4%)')).toBeTruthy()
  })

  it('counts what changed out of what was asked', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage()

    expect(await screen.findByText(/Cleaning changed 2 of your 3 answers/)).toBeTruthy()
  })

  it('keeps the cards in the order they arrive', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage()
    await screen.findByRole('heading', { name: /average "Salary"/ })

    const headings = screen.getAllByRole('heading', { level: 4 }).map((node) => node.textContent)
    expect(headings[0]).toContain('Salary')
    expect(headings[1]).toContain('team')
  })

  it('gives a breakdown the same numbers in a table for anyone who cannot see bars', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage()
    await screen.findByRole('heading', { name: /each "team"/ })
    const team = answerCard(/each "team"/)

    const rows = within(team).getAllByRole('row')
    expect(rows.length).toBeGreaterThan(1)
    expect(within(team).getByRole('columnheader', { name: 'After cleaning' })).toBeTruthy()
  })

  it('says a merged spelling is now counted with another, not that rows went missing', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage()
    await screen.findByRole('heading', { name: /each "team"/ })
    const team = answerCard(/each "team"/)

    expect(within(team).getByText(/is now counted with/)).toBeTruthy()
    expect(within(team).getByText(/“Sales ”/)).toBeTruthy()
  })

  it('explains a group that only exists after cleaning', async () => {
    const appeared = breakdownCard({
      groups: [
        { label: 'North', before: null, after: 12, status: 'appeared' },
        { label: 'South', before: 4, after: 4, status: 'same' },
      ],
      merged: [],
    })
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison({ cards: [appeared] })) })

    renderPage()

    expect(await screen.findByText('“North” wasn’t a group before cleaning.')).toBeTruthy()
  })

  it('does not list every group when the whole breakdown is new', async () => {
    const split = breakdownCard({
      groups: [
        { label: 'North', before: null, after: 12, status: 'appeared' },
        { label: 'South', before: null, after: 8, status: 'appeared' },
      ],
      merged: [],
    })
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison({ cards: [split] })) })

    renderPage()

    expect(await screen.findByText('None of these groups existed before cleaning.')).toBeTruthy()
    expect(screen.queryByText(/weren’t groups/)).toBeNull()
  })

  it('says when a group has no rows left, in the plural too', async () => {
    const gone = breakdownCard({
      groups: [
        { label: 'Left', before: 5, after: 0, status: 'disappeared' },
        { label: 'Gone', before: 3, after: 0, status: 'disappeared' },
        { label: 'Here', before: 10, after: 10, status: 'same' },
      ],
      merged: [],
    })
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison({ cards: [gone] })) })

    renderPage()

    expect(await screen.findByText(/“Left” and “Gone” have no rows left/)).toBeTruthy()
  })

  it('names the steps behind a change and points at them', async () => {
    const highlighted: string[][] = []
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage({ onHighlight: (ids) => highlighted.push(ids) })
    await screen.findByRole('heading', { name: /average "Salary"/ })
    const salary = answerCard(/average "Salary"/)
    fireEvent.click(within(salary).getByRole('button', { name: 'Why?' }))

    expect(within(salary).getByText('Caused by:')).toBeTruthy()
    expect(within(salary).getByRole('button', { name: 'Replace "N/A" with "0" in "Salary"' })).toBeTruthy()
    expect(highlighted.at(-1)).toEqual(['step-1'])
  })

  it('opens the rows a step changed, on request', async () => {
    const fetchMock = mockApi({
      [COMPARE]: () => jsonResponse(200, comparison()),
      [PREVIEW]: () => jsonResponse(200, preview()),
    })

    renderPage()
    await screen.findByRole('heading', { name: /average "Salary"/ })
    const salary = answerCard(/average "Salary"/)
    fireEvent.click(within(salary).getByRole('button', { name: 'Why?' }))
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/preview'))).toBe(false)

    fireEvent.click(within(salary).getByRole('button', { name: /Replace "N\/A"/ }))

    expect(await within(salary).findByText(/38 rows change/)).toBeTruthy()
  })

  it('shows questions the raw file could not answer on their own', async () => {
    const newQuestion = card({
      question_id: 'q-dept',
      label: 'How many rows are there for each "Department"?',
      kind: 'breakdown',
      measure: 'count',
      unlocked: true,
      before: {
        answerable: false,
        value: null,
        note: 'There’s no column called "Department".',
        rows_used: 0,
        rows_skipped: 0,
      },
      groups: [{ label: 'Sales', before: 0, after: 12, status: 'appeared' }],
      change: null,
      relative_change: null,
    })
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison({ unlocked: [newQuestion] })) })

    renderPage()

    expect(await screen.findByRole('heading', { name: /Now you can ask/ })).toBeTruthy()
    expect(screen.getByText('There’s no column called "Department".')).toBeTruthy()
  })

  it('explains what "before" means, on request', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /What does “before” mean/ }))

    expect(screen.getByText(/Every row in the file counts/)).toBeTruthy()
    expect(screen.getByText(/Dates count only when written/)).toBeTruthy()
  })

  it('lists the answers that stayed the same, tucked away', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage()

    expect(await screen.findByText('1 answer came out the same')).toBeTruthy()
    expect(screen.getByText('How many rows are there?')).toBeTruthy()
  })

  // --- nothing to show ---------------------------------------------------------------------

  it('points back to the review when nothing has been applied', async () => {
    const back = vi.fn()
    mockApi({
      [COMPARE]: () =>
        jsonResponse(200, comparison({ cards: [], has_steps: false, unchanged: ['a', 'b'] })),
    })

    renderPage({ onBackToReview: back })
    fireEvent.click(await screen.findByRole('button', { name: 'Back to the review' }))

    expect(screen.getByText('Nothing has been cleaned yet.')).toBeTruthy()
    expect(back).toHaveBeenCalled()
  })

  it('says so plainly when cleaning moved no answers', async () => {
    mockApi({
      [COMPARE]: () =>
        jsonResponse(
          200,
          comparison({ cards: [], unchanged: ['How many rows are there?', 'Total "Qty"?'] }),
        ),
    })

    renderPage()

    expect(await screen.findByText('Your answers came out the same either way.')).toBeTruthy()
    expect(screen.getByText(/We asked 2 questions of your file/)).toBeTruthy()
  })

  // --- the story ---------------------------------------------------------------------------

  it('tells the short version over the cards', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage()

    expect(await screen.findByText(/Your file went from/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '1,071' })).toBeTruthy()
    expect(screen.getByRole('button', { name: '83,151.41' })).toBeTruthy()
  })

  it('takes the reader from a figure to the answer it came from', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })
    const scrolled: string[] = []
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this.id)
    }

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: '83,151.41' }))

    expect(scrolled).toEqual(['answer-q-salary'])
  })

  it('says nothing when there is no story to tell', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison({ story: null })) })

    renderPage()
    await screen.findByRole('heading', { name: /average "Salary"/ })

    expect(screen.queryByText(/Your file went from/)).toBeNull()
  })

  it('prefers the version a model told, when there is one', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage({
      aiStory: story({
        source: 'ai',
        sentences: [
          {
            parts: [
              { text: 'Your customer list lost ', question_id: null },
              { text: '92', question_id: 'q-rows' },
              { text: ' duplicated people.', question_id: null },
            ],
          },
        ],
      }),
    })

    expect(await screen.findByText(/lost/)).toBeTruthy()
    expect(screen.queryByText(/Your file went from/)).toBeNull()
  })

  it('ignores a model story written about a different set of rows', async () => {
    // The model's story is fetched apart from the answers, so it can lag behind
    // a choice the user just changed. Its figures would contradict the cards.
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage({
      aiStory: story({
        source: 'ai',
        recipe_key: 'an-older-key',
        sentences: [{ parts: [{ text: 'Your customer list lost people.', question_id: null }] }],
      }),
    })

    expect(await screen.findByText(/Your file went from/)).toBeTruthy()
    expect(screen.queryByText(/lost people/)).toBeNull()
  })

  // --- changing an answer from here --------------------------------------------------------

  it('offers the answers already given, and asks for a different one', async () => {
    const chose = vi.fn()
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })

    renderPage({
      issues: [askIssue({ state: 'applied', chosen_choice_id: 'missing' })],
      onChoose: chose,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Treat them as zero' }))

    expect(chose).toHaveBeenCalledWith('issue-ask', 'zero')
    expect(
      screen.getByRole('button', { name: 'Treat them as missing' }).getAttribute('aria-pressed'),
    ).toBe('true')
  })

  it('keeps the old answers on screen while the new ones are worked out', async () => {
    mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })
    const { rerender, client } = renderPage()
    await screen.findByRole('heading', { name: /average "Salary"/ })

    // A different recipe means a different key, which is what triggers the refetch.
    mockApi({ [COMPARE]: () => new Promise(() => {}) })
    rerender(
      <QueryClientProvider client={client}>
        <ComparePage
          datasetId={DATASET}
          recipeKey="key-2"
          steps={[step()]}
          issues={[]}
          choosing={null}
          onChoose={() => {}}
          onHighlight={() => {}}
          onBackToReview={() => {}}
        />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(screen.getAllByRole('status').length).toBeGreaterThan(0))
    expect(within(answerCard(/average "Salary"/)).getByText('83,151.41')).toBeTruthy()
  })

  it('asks nothing again when the rows are the ones it already compared', async () => {
    const fetchMock = mockApi({ [COMPARE]: () => jsonResponse(200, comparison()) })
    const { rerender, client } = renderPage()
    await screen.findByRole('heading', { name: /average "Salary"/ })
    const calls = fetchMock.mock.calls.length

    rerender(
      <QueryClientProvider client={client}>
        <ComparePage
          datasetId={DATASET}
          recipeKey="key-1"
          steps={[step()]}
          issues={[]}
          choosing={null}
          onChoose={() => {}}
          onHighlight={() => {}}
          onBackToReview={() => {}}
        />
      </QueryClientProvider>,
    )

    expect(fetchMock.mock.calls.length).toBe(calls)
  })
})
