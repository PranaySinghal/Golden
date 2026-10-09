import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type {
  CanvasResponse,
  DatasetConnectors,
  RecipeResponse,
  Suggestions,
} from '../../api/client'
import { jsonResponse, recipe, step } from '../../test/fixtures'
import { mockApi } from '../../test/mockApi'
import { CanvasPage } from './CanvasPage'

const ID = 'abc'
const CANVAS = `GET /api/datasets/${ID}/canvas`
const IDEAS_QUICK = `GET /api/datasets/${ID}/canvas/suggestions?smart=false`
const IDEAS_SMART = `GET /api/datasets/${ID}/canvas/suggestions?smart=true`
const ADD = `POST /api/datasets/${ID}/canvas/columns`
const CONNECTORS = `GET /api/datasets/${ID}/connectors`
const SWITCH_AI = `PUT /api/datasets/${ID}/connectors/ai_fill`
const PREVIEW_AI = `POST /api/datasets/${ID}/connectors/ai-fill/preview`
const LOOKUP = `POST /api/datasets/${ID}/connectors/lookups`

function connectors(aiEnabled = false, aiActive = false): DatasetConnectors {
  return {
    connectors: [
      {
        id: 'ai_fill',
        title: 'Fill a new column with AI',
        adds: 'Text a model works out from another column.',
        sends: 'Each different value in the column the new one is based on.',
        service: 'Anthropic (Claude)',
        enabled: aiEnabled,
        active: aiActive,
      },
    ],
    offers: [],
    enrichments: [],
    consented: [],
    recipe: recipe(),
  }
}

const INDUSTRY = {
  name: 'Industry',
  reason: 'Lets you group the companies by what they do.',
  placeholder: null,
  source: 'ai' as const,
  live_source: null,
  fill: { based_on: 'Company', kind: 'label' as const, choices: ['Technology', 'Retail'] },
}

function canvas(overrides: Partial<CanvasResponse> = {}): CanvasResponse {
  return {
    columns: [
      { name: 'Company', kind: 'text', step_id: null },
      { name: 'City', kind: 'text', step_id: null },
    ],
    rows: [
      ['Acme Tools', 'Leeds'],
      ['Birch Foods', null],
    ],
    row_count: 40,
    recipe: recipe(),
    ...overrides,
  }
}

function ideas(overrides: Partial<Suggestions> = {}): Suggestions {
  return {
    status: 'off',
    about: null,
    suggestions: [
      {
        name: 'Stock price',
        reason: 'Their current share price can sit beside them.',
        placeholder: null,
        source: 'rules',
        live_source: 'A stock price service',
      },
      {
        name: 'Status',
        reason: 'A place to mark where each row stands.',
        placeholder: 'To review',
        source: 'rules',
        live_source: null,
      },
    ],
    ...overrides,
  }
}

function renderCanvas(
  onRecipe: (recipe: RecipeResponse) => void = () => {},
  onRemove: (stepId: string) => void = () => {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <CanvasPage datasetId={ID} recipeKey="k1" busy={false} onRecipe={onRecipe} onRemove={onRemove} />
    </QueryClientProvider>,
  )
}

const ready = {
  [CONNECTORS]: () => jsonResponse(200, connectors()),
  [CANVAS]: () => jsonResponse(200, canvas()),
  [IDEAS_QUICK]: () => jsonResponse(200, ideas()),
  [IDEAS_SMART]: () => jsonResponse(200, ideas()),
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('CanvasPage', () => {
  it('says what it is doing while the table loads', () => {
    mockApi({ ...ready, [CANVAS]: () => new Promise(() => {}) })

    renderCanvas()

    expect(screen.getByRole('status').textContent).toContain('Laying out your table')
  })

  it('explains a failure and offers to try again', async () => {
    mockApi({
      ...ready,
      [CANVAS]: () => jsonResponse(404, { code: 'dataset_not_found', message: 'File has expired.' }),
    })

    renderCanvas()

    expect(await screen.findByText('File has expired.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('shows the table, with blanks marked', async () => {
    mockApi(ready)

    renderCanvas()

    expect(await screen.findByRole('columnheader', { name: 'Company' })).toBeTruthy()
    expect(screen.getByText('Acme Tools')).toBeTruthy()
    expect(screen.getByText('(blank)')).toBeTruthy()
    expect(screen.getByText('Showing the first 2 of 40 rows.')).toBeTruthy()
  })

  it('says in one line what the canvas is for', async () => {
    mockApi(ready)

    renderCanvas()

    expect(
      await screen.findByText(
        'Alter sheet - update values. Each step is undoable and the file downloadable.',
      ),
    ).toBeTruthy()
  })

  it('says so when the table has no columns', async () => {
    mockApi({ ...ready, [CANVAS]: () => jsonResponse(200, canvas({ columns: [], rows: [] })) })

    renderCanvas()

    expect(await screen.findByText('This table has no columns yet.')).toBeTruthy()
  })

  it('offers ideas in a list, and picking one fills in the form and says why', async () => {
    mockApi(ready)

    renderCanvas()
    const list = await screen.findByLabelText('Ideas for this file')
    await within(list).findByRole('option', { name: 'Status' })
    fireEvent.change(list, { target: { value: 'Status' } })

    expect((screen.getByLabelText('Column name') as HTMLInputElement).value).toBe('Status')
    expect((screen.getByLabelText(/Text to show in every row/) as HTMLInputElement).value).toBe(
      'To review',
    )
    expect(screen.getByText('A place to mark where each row stands.')).toBeTruthy()
  })

  it('says where a column could be filled from, and where to look that up', async () => {
    mockApi(ready)

    renderCanvas()
    const list = await screen.findByLabelText('Ideas for this file')
    await within(list).findByRole('option', { name: 'Stock price' })
    fireEvent.change(list, { target: { value: 'Stock price' } })

    expect(screen.getByText(/Could be filled in from: a stock price service/)).toBeTruthy()
    expect(screen.getByText(/see Connectors at the top of the page/)).toBeTruthy()
  })

  it("shows a model's ideas once they arrive, marked as such", async () => {
    mockApi({
      ...ready,
      [IDEAS_SMART]: () =>
        jsonResponse(
          200,
          ideas({
            status: 'ready',
            about: 'A list of companies and where they are based.',
            suggestions: [
              { name: 'Revenue', reason: 'Shows how big each is.', source: 'ai', placeholder: null, live_source: null },
            ],
          }),
        ),
    })

    renderCanvas()

    expect(await screen.findByText('A list of companies and where they are based.')).toBeTruthy()
    const list = screen.getByLabelText('Ideas for this file')
    fireEvent.change(list, { target: { value: 'Revenue' } })
    expect(screen.getByText('Suggested by AI')).toBeTruthy()
  })

  it('still lets you add your own column when ideas cannot be loaded', async () => {
    const failed = () => jsonResponse(500, { code: 'x', message: 'Broken.' })
    mockApi({ ...ready, [IDEAS_QUICK]: failed, [IDEAS_SMART]: failed })

    renderCanvas()

    expect(await screen.findByText(/Ideas couldn’t be loaded/)).toBeTruthy()
    expect(screen.getByLabelText('Column name')).toBeTruthy()
  })

  it('says when extra ideas could not be fetched', async () => {
    mockApi({ ...ready, [IDEAS_SMART]: () => jsonResponse(200, ideas({ status: 'failed' })) })

    renderCanvas()

    expect(await screen.findByText(/Extra ideas couldn’t be fetched/)).toBeTruthy()
  })

  it('adds a column and passes the new recipe up', async () => {
    const added = canvas({
      columns: [
        { name: 'Company', kind: 'text', step_id: null },
        { name: 'Notes', kind: 'text', step_id: 'step-9' },
        { name: 'City', kind: 'text', step_id: null },
      ],
      rows: [['Acme Tools', 'TBC', 'Leeds']],
      recipe: recipe({ recipe_key: 'k2', steps: [step({ id: 'step-9', type: 'add_column' })] }),
    })
    const fetchMock = mockApi({ ...ready, [ADD]: () => jsonResponse(200, added) })
    const onRecipe = vi.fn()

    renderCanvas(onRecipe)
    fireEvent.change(await screen.findByLabelText('Column name'), { target: { value: 'Notes' } })
    fireEvent.change(screen.getByLabelText(/Text to show in every row/), { target: { value: 'TBC' } })
    fireEvent.change(screen.getByLabelText('Where it goes'), { target: { value: 'Company' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add column' }))

    await waitFor(() => expect(onRecipe).toHaveBeenCalledWith(added.recipe))
    const sent = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(sent?.[1]?.body))).toEqual({
      name: 'Notes',
      value: 'TBC',
      insert_after: 'Company',
    })
    expect((screen.getByLabelText('Column name') as HTMLInputElement).value).toBe('')
  })

  it('cannot add a column without a name', async () => {
    mockApi(ready)

    renderCanvas()

    const button = (await screen.findByRole('button', { name: 'Add column' })) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })

  it('explains why a column could not be added', async () => {
    mockApi({
      ...ready,
      [ADD]: () =>
        jsonResponse(422, {
          code: 'invalid_step',
          message: 'There\'s already a column called "City". Pick a different name.',
        }),
    })

    renderCanvas()
    fireEvent.change(await screen.findByLabelText('Column name'), { target: { value: 'City' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add column' }))

    expect((await screen.findByRole('alert')).textContent).toContain('already a column called "City"')
  })

  it('says why a looked-up cell is empty and when prices were true', async () => {
    mockApi({
      ...ready,
      [CANVAS]: () =>
        jsonResponse(
          200,
          canvas({
            columns: [
              { name: 'Ticker', kind: 'text', step_id: null },
              { name: 'Price', kind: 'text', step_id: null, label: 'Prices as of 2026-10-08 09:31 ET' },
            ],
            rows: [
              ['AAPL', '$261.74'],
              ['ZZZZ', null],
              [null, null],
            ],
            reasons: { Price: [null, 'not found', null] },
          }),
        ),
    })

    renderCanvas()

    // The time is one hover away on the column's heading, not a column of its own.
    expect(await screen.findByRole('button', { name: 'About the column Price' })).toBeTruthy()
    expect(screen.getByText('(not found)')).toBeTruthy()
    // A cell that was simply empty in the file still reads as blank.
    expect(screen.getAllByText('(blank)')).toHaveLength(2)
  })

  it('offers to fill an idea in with AI only when a model service is set up', async () => {
    const withIdea = () =>
      jsonResponse(200, ideas({ status: 'ready', suggestions: [INDUSTRY] }))
    mockApi({ ...ready, [IDEAS_QUICK]: withIdea, [IDEAS_SMART]: withIdea })

    renderCanvas()
    const list = await screen.findByLabelText('Ideas for this file')
    await within(list).findByRole('option', { name: 'Industry' })
    fireEvent.change(list, { target: { value: 'Industry' } })

    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(screen.getByRole('button', { name: 'Add column' })).toBeTruthy()
  })

  it('asks before sending, shows a few answers, and only then fills the column', async () => {
    const withIdea = () =>
      jsonResponse(200, ideas({ status: 'ready', suggestions: [INDUSTRY] }))
    const filled = { ...connectors(true, true), recipe: recipe({ recipe_key: 'k2' }) }
    const fetchMock = mockApi({
      ...ready,
      [CONNECTORS]: () => jsonResponse(200, connectors(true)),
      [IDEAS_QUICK]: withIdea,
      [IDEAS_SMART]: withIdea,
      [SWITCH_AI]: () => jsonResponse(200, connectors(true, true)),
      [PREVIEW_AI]: () =>
        jsonResponse(200, {
          rows: [
            { value: 'Acme Tools', answer: 'Retail', reason: null },
            { value: 'Zzyx', answer: null, reason: 'not sure' },
          ],
          total_values: 412,
        }),
      [LOOKUP]: () => jsonResponse(200, filled),
    })
    const onRecipe = vi.fn()
    const posts = () =>
      fetchMock.mock.calls
        .filter(([, init]) => init?.method === 'POST' || init?.method === 'PUT')
        .map(([url]) => String(url))

    renderCanvas(onRecipe)
    const list = await screen.findByLabelText('Ideas for this file')
    await within(list).findByRole('option', { name: 'Industry' })
    fireEvent.change(list, { target: { value: 'Industry' } })
    const tick = (await screen.findByRole('checkbox')) as HTMLInputElement
    expect(tick.checked).toBe(true)
    expect(screen.getByText(/Fill it in with AI, from “Company”/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Add and fill with AI' }))

    // First, what will be sent. Nothing has gone anywhere yet.
    const prompt = screen.getByRole('alertdialog', { name: 'Before anything is sent' })
    expect(prompt.textContent).toContain(
      'AI detects “Industry” for each different value in “Company”.',
    )
    expect(prompt.textContent).toContain('Values could be unverified.')
    // Which service, and exactly what goes to it, is one hover away.
    expect(within(prompt).getByRole('button', { name: 'What is sent, and to whom' })).toBeTruthy()
    expect(posts()).toEqual([])

    fireEvent.click(within(prompt).getByRole('button', { name: 'Send and show a few answers' }))

    // Then a few answers to judge, with the unsure one left blank and saying so.
    const check = await screen.findByRole('region', { name: 'A few answers to check' })
    expect(within(check).getByText('Retail')).toBeTruthy()
    expect(within(check).getByText('(not sure)')).toBeTruthy()
    expect(posts()).toEqual([
      `/api/datasets/${ID}/connectors/ai_fill`,
      `/api/datasets/${ID}/connectors/ai-fill/preview`,
    ])
    expect(onRecipe).not.toHaveBeenCalled()

    fireEvent.click(within(check).getByRole('button', { name: 'Fill all 412 values' }))

    await waitFor(() => expect(onRecipe).toHaveBeenCalledWith(filled.recipe))
    const sent = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/lookups'))
    expect(JSON.parse(String(sent?.[1]?.body))).toEqual({
      connector: 'ai_fill',
      consent: true,
      fill: {
        name: 'Industry',
        based_on: 'Company',
        instruction: 'Industry. Lets you group the companies by what they do.',
        kind: 'label',
        choices: ['Technology', 'Retail'],
        context: [],
      },
    })
  })

  it('adds nothing when the user backs out of an AI fill', async () => {
    const withIdea = () =>
      jsonResponse(200, ideas({ status: 'ready', suggestions: [INDUSTRY] }))
    const fetchMock = mockApi({
      ...ready,
      [CONNECTORS]: () => jsonResponse(200, connectors(true, true)),
      [IDEAS_QUICK]: withIdea,
      [IDEAS_SMART]: withIdea,
    })

    renderCanvas()
    const list = await screen.findByLabelText('Ideas for this file')
    await within(list).findByRole('option', { name: 'Industry' })
    fireEvent.change(list, { target: { value: 'Industry' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Add and fill with AI' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false)
  })

  it('adds a plain empty column when the AI box is unticked', async () => {
    const withIdea = () =>
      jsonResponse(200, ideas({ status: 'ready', suggestions: [INDUSTRY] }))
    const fetchMock = mockApi({
      ...ready,
      [CONNECTORS]: () => jsonResponse(200, connectors(true, true)),
      [IDEAS_QUICK]: withIdea,
      [IDEAS_SMART]: withIdea,
      [ADD]: () => jsonResponse(200, canvas()),
    })

    renderCanvas()
    const list = await screen.findByLabelText('Ideas for this file')
    await within(list).findByRole('option', { name: 'Industry' })
    fireEvent.change(list, { target: { value: 'Industry' } })
    fireEvent.click(await screen.findByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'Add column' }))

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/canvas/columns'))).toBe(
        true,
      ),
    )
  })

  it('marks a column you added and lets you take it back out', async () => {
    mockApi({
      ...ready,
      [CANVAS]: () =>
        jsonResponse(
          200,
          canvas({
            columns: [
              { name: 'Company', kind: 'text', step_id: null },
              { name: 'Notes', kind: 'text', step_id: 'step-9' },
            ],
            rows: [['Acme Tools', null]],
          }),
        ),
    })
    const onRemove = vi.fn()

    renderCanvas(undefined, onRemove)
    fireEvent.click(await screen.findByRole('button', { name: 'Remove the column Notes' }))

    expect(onRemove).toHaveBeenCalledWith('step-9')
  })
})
