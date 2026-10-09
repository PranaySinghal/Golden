import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type {
  ConnectorView,
  DatasetConnectors,
  EnrichmentView,
  OfferView,
} from '../../api/client'
import { jsonResponse, recipe } from '../../test/fixtures'
import { mockApi } from '../../test/mockApi'
import { ConnectorsPanel } from './ConnectorsPanel'

const ID = 'abc'
const SERVICES = 'GET /api/connectors'
const FOR_FILE = `GET /api/datasets/${ID}/connectors`
const SWITCH = `PUT /api/datasets/${ID}/connectors/postal_geocode`
const LOOKUP = `POST /api/datasets/${ID}/connectors/lookups`

function services(enabled = true, active = enabled): ConnectorView[] {
  return [
    {
      id: 'postal_geocode',
      title: 'Map positions from postal codes',
      adds: 'A latitude and a longitude for each postal code.',
      sends: 'Each different postal code and the country you choose. Nothing else.',
      service: 'Zippopotam.us',
      enabled,
      active,
    },
    {
      id: 'stock_price',
      title: 'Latest share prices from stock symbols',
      adds: 'The latest price for each stock symbol.',
      sends: 'Each different stock symbol. Nothing else.',
      service: 'Finnhub',
      enabled,
      active,
    },
  ]
}

function offer(overrides: Partial<OfferView> = {}): OfferView {
  return {
    connector: 'postal_geocode',
    column: 'Area',
    title: 'Add map positions from "Area"',
    distinct_values: 412,
    countries: [
      { code: 'US', name: 'United States' },
      { code: 'DE', name: 'Germany' },
    ],
    enabled: true,
    ...overrides,
  }
}

function enrichment(overrides: Partial<EnrichmentView> = {}): EnrichmentView {
  return {
    step_id: 'step-7',
    connector: 'stock_price',
    column: 'Ticker',
    into: ['Price', 'Price as of'],
    looked_up: true,
    counts: { found: 38, 'not found': 2 },
    examples: { 'not found': ['ZZZZ'] },
    remaining: 0,
    as_of: '2026-10-08 09:31 ET',
    out_of_date: false,
    enabled: true,
    ...overrides,
  }
}

function forFile(overrides: Partial<DatasetConnectors> = {}): DatasetConnectors {
  return {
    connectors: services(),
    offers: [offer()],
    enrichments: [],
    consented: [],
    recipe: recipe(),
    ...overrides,
  }
}

function renderPanel(datasetId: string | null = ID, onClose = () => {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ConnectorsPanel datasetId={datasetId} onClose={onClose} />
    </QueryClientProvider>,
  )
}

function sent(fetchMock: ReturnType<typeof mockApi>): unknown[] {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method === 'POST')
    .map(([, init]) => JSON.parse(String(init?.body)))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ConnectorsPanel', () => {
  it('lists the services and asks for a file when none is open', async () => {
    mockApi({ [SERVICES]: () => jsonResponse(200, services(false)) })

    renderPanel(null)

    expect(await screen.findByText('Map positions')).toBeTruthy()
    expect(screen.getByText('Share prices')).toBeTruthy()
    expect(screen.getAllByText('Not set up')).toHaveLength(2)
    expect(screen.getByText('Open a file to use these.')).toBeTruthy()
    // What a service adds and sends is one hover away, not spelled out on the page.
    expect(screen.getByRole('button', { name: 'About Share prices' })).toBeTruthy()
    expect(screen.queryByRole('switch')).toBeNull()
  })

  it('says what it is doing while it checks, and explains a failure', async () => {
    mockApi({ [FOR_FILE]: () => jsonResponse(404, { code: 'x', message: 'File has expired.' }) })

    renderPanel()

    expect(screen.getByRole('status').textContent).toContain('Checking what can be looked up')
    expect(await screen.findByText('File has expired.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('keeps each service, its state for this file and its action in one card', async () => {
    mockApi({ [FOR_FILE]: () => jsonResponse(200, forFile()) })

    renderPanel()
    const maps = await screen.findByRole('listitem', { name: 'Map positions' })
    const prices = screen.getByRole('listitem', { name: 'Share prices' })

    // The one with something to do in this file comes first, with its switch and action.
    expect(screen.getAllByRole('listitem')[0]).toBe(maps)
    expect(within(maps).getByText('Found in “Area” · 412 values')).toBeTruthy()
    expect(within(maps).getByRole('switch', { name: 'Use Map positions for this file' })).toBeTruthy()
    expect(within(maps).getByRole('button', { name: 'Enrich' })).toBeTruthy()
    // The other says there is nothing for it here, and offers nothing to press.
    expect(within(prices).getByText('Nothing to look up in this file')).toBeTruthy()
    expect(within(prices).queryByRole('button', { name: 'Enrich' })).toBeNull()
    // With nothing to work on, it reads Off and can't be switched on, even though
    // the server reports it as on for this file.
    const flip = within(prices).getByRole('switch') as HTMLInputElement
    expect(flip.checked).toBe(false)
    expect(flip.disabled).toBe(true)
    expect((within(maps).getByRole('switch') as HTMLInputElement).disabled).toBe(false)
  })

  it('starts every service off for a file and switches one on when asked', async () => {
    const off = forFile({ connectors: services(true, false) })
    const fetchMock = mockApi({
      [FOR_FILE]: () => jsonResponse(200, off),
      [SWITCH]: () => jsonResponse(200, forFile()),
    })

    renderPanel()
    const enrich = (await screen.findByRole('button', { name: 'Enrich' })) as HTMLButtonElement
    const flip = screen.getByRole('switch', {
      name: 'Use Map positions for this file',
    }) as HTMLInputElement

    expect(flip.checked).toBe(false)
    expect(enrich.disabled).toBe(true)
    // The country question waits until the service is on.
    expect(screen.queryByLabelText('Country of these postal codes')).toBeNull()

    fireEvent.click(flip)

    await waitFor(() => expect(flip.checked).toBe(true))
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ active: true })
    // Switching on is not a lookup: nothing was sent.
    expect(sent(fetchMock)).toEqual([])
  })

  it('will not look up postal codes until a country is chosen', async () => {
    mockApi({ [FOR_FILE]: () => jsonResponse(200, forFile()) })

    renderPanel()
    const enrich = (await screen.findByRole('button', { name: 'Enrich' })) as HTMLButtonElement
    const country = screen.getByLabelText('Country of these postal codes') as HTMLSelectElement

    expect(country.value).toBe('')
    expect(enrich.disabled).toBe(true)
    fireEvent.change(country, { target: { value: 'DE' } })
    expect(enrich.disabled).toBe(false)
  })

  it('shows what will be sent and sends nothing until the user agrees', async () => {
    const done = forFile({ offers: [], consented: ['postal_geocode'] })
    const fetchMock = mockApi({
      [FOR_FILE]: () => jsonResponse(200, forFile()),
      [LOOKUP]: () => jsonResponse(200, done),
    })

    renderPanel()
    fireEvent.change(await screen.findByLabelText('Country of these postal codes'), {
      target: { value: 'US' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Enrich' }))

    // The prompt opens inside the card it belongs to, in one short sentence.
    const maps = screen.getByRole('listitem', { name: 'Map positions' })
    const prompt = within(maps).getByRole('alertdialog', { name: 'Before anything is sent' })
    expect(prompt.textContent).toContain('Looks up 412 values in “Area” with Zippopotam.us.')
    expect(within(prompt).getByRole('button', { name: 'What is sent, and to whom' })).toBeTruthy()
    expect(sent(fetchMock)).toEqual([])

    fireEvent.click(within(prompt).getByRole('button', { name: 'Send and look up' }))

    await waitFor(() =>
      expect(sent(fetchMock)).toEqual([
        { connector: 'postal_geocode', column: 'Area', country: 'US', consent: true },
      ]),
    )
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull())
  })

  it('sends nothing when the user cancels', async () => {
    const fetchMock = mockApi({ [FOR_FILE]: () => jsonResponse(200, forFile()) })

    renderPanel()
    fireEvent.change(await screen.findByLabelText('Country of these postal codes'), {
      target: { value: 'US' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Enrich' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(sent(fetchMock)).toEqual([])
  })

  it('does not ask twice for a connector already agreed to on this file', async () => {
    const fetchMock = mockApi({
      [FOR_FILE]: () =>
        jsonResponse(
          200,
          forFile({ consented: ['postal_geocode'], offers: [offer({ countries: [] })] }),
        ),
      [LOOKUP]: () => jsonResponse(200, forFile({ offers: [] })),
    })

    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: 'Enrich' }))

    await waitFor(() => expect(sent(fetchMock)).toHaveLength(1))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('shows an offer it cannot run when the connector is not set up', async () => {
    mockApi({
      [FOR_FILE]: () =>
        jsonResponse(
          200,
          forFile({ connectors: services(false), offers: [offer({ enabled: false, countries: [] })] }),
        ),
    })

    renderPanel()
    const enrich = (await screen.findByRole('button', { name: 'Enrich' })) as HTMLButtonElement

    expect(enrich.disabled).toBe(true)
    expect(screen.getAllByText('Not set up')).toHaveLength(2)
    expect(screen.queryByRole('switch')).toBeNull()
  })

  it('says what came of a lookup and when prices were true', async () => {
    mockApi({
      [FOR_FILE]: () => jsonResponse(200, forFile({ offers: [], enrichments: [enrichment()] })),
    })

    renderPanel()
    const prices = await screen.findByRole('listitem', { name: 'Share prices' })

    expect(prices.textContent).toContain('Added “Price” and “Price as of” from “Ticker”')
    expect(prices.textContent).toContain('38 found, 2 not found')
    expect(within(prices).getByText(/As of 2026-10-08 09:31 ET/)).toBeTruthy()
    // Which values had no answer is one hover away.
    expect(within(prices).getByRole('button', { name: 'Values without an answer' })).toBeTruthy()
    // Nothing left to do, so there is nothing to press.
    expect(screen.queryByRole('button', { name: /Look up|Refresh/ })).toBeNull()
  })

  it('marks prices from before the market opened and refreshes only on a click', async () => {
    const fetchMock = mockApi({
      [FOR_FILE]: () =>
        jsonResponse(
          200,
          forFile({
            offers: [],
            consented: ['stock_price'],
            enrichments: [enrichment({ out_of_date: true })],
          }),
        ),
      [LOOKUP]: () =>
        jsonResponse(200, forFile({ offers: [], enrichments: [enrichment()] })),
    })

    renderPanel()

    expect(await screen.findByText('Out of date')).toBeTruthy()
    expect(sent(fetchMock)).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'Refresh prices' }))
    await waitFor(() => expect(sent(fetchMock)).toEqual([{ step_id: 'step-7', consent: false }]))
    await waitFor(() => expect(screen.queryByText('Out of date')).toBeNull())
  })

  it('offers to carry on when a lookup stopped at its limit', async () => {
    mockApi({
      [FOR_FILE]: () =>
        jsonResponse(
          200,
          forFile({
            offers: [],
            enrichments: [
              enrichment({
                counts: { found: 100, 'not looked up yet': 312 },
                examples: {},
                remaining: 312,
              }),
            ],
          }),
        ),
    })

    renderPanel()

    expect(await screen.findByRole('button', { name: 'Look up the rest (312)' })).toBeTruthy()
  })

  it('asks before filling in steps that came from another file', async () => {
    mockApi({
      [FOR_FILE]: () =>
        jsonResponse(
          200,
          forFile({
            offers: [],
            enrichments: [enrichment({ looked_up: false, counts: {}, examples: {}, as_of: null })],
          }),
        ),
    })

    renderPanel()
    expect(await screen.findByText(/not looked up yet/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }))

    expect(screen.getByRole('alertdialog').textContent).toContain('Finnhub')
  })

  it('explains why a lookup could not run', async () => {
    mockApi({
      [FOR_FILE]: () =>
        jsonResponse(200, forFile({ consented: ['postal_geocode'], offers: [offer({ countries: [] })] })),
      [LOOKUP]: () =>
        jsonResponse(409, { code: 'connector_off', message: "This connector isn't set up." }),
    })

    renderPanel()
    fireEvent.click(await screen.findByRole('button', { name: 'Enrich' }))

    expect((await screen.findByRole('alert')).textContent).toContain("isn't set up")
  })

  it('closes on its button and on Escape', async () => {
    mockApi({ [FOR_FILE]: () => jsonResponse(200, forFile()) })
    const onClose = vi.fn()

    renderPanel(ID, onClose)
    fireEvent.click(await screen.findByRole('button', { name: 'Close' }))
    fireEvent.keyDown(window, { key: 'Escape' })

    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
