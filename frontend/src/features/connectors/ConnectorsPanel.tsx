import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import {
  api,
  type ConnectorView,
  type DatasetConnectors,
  type EnrichmentView,
  type IssueListResponse,
  type LookupRequest,
  type OfferView,
} from '../../api/client'
import { InfoTip } from '../../components/InfoTip'
import { ErrorState, Spinner } from '../../components/states'
import { formatCount } from '../upload/format'

interface ConnectorsPanelProps {
  /** The file being worked on, if one is open. Without one the panel only lists the services. */
  datasetId: string | null
  onClose: () => void
}

type ConnectorId = ConnectorView['id']

/** How each service is shown: a symbol to tell them apart at a glance, and a short name. */
const LOOK: Record<ConnectorId, { symbol: string; name: string }> = {
  postal_geocode: { symbol: '📍', name: 'Map positions' },
  company_ticker: { symbol: '🏢', name: 'Stock symbols' },
  stock_price: { symbol: '💲', name: 'Share prices' },
  ai_fill: { symbol: '✨', name: 'AI fill' },
}

/** A lookup the user asked for and hasn't yet agreed to send. */
interface Pending {
  key: string
  connector: ConnectorView
  column: string
  values: number | null
  request: LookupRequest
}

export function ConnectorsPanel({ datasetId, onClose }: ConnectorsPanelProps) {
  const queryClient = useQueryClient()
  const [pending, setPending] = useState<Pending | null>(null)
  const [countries, setCountries] = useState<Record<string, string>>({})

  const services = useQuery({
    queryKey: ['connectors'],
    queryFn: api.getConnectors,
    enabled: datasetId === null,
  })
  const forFile = useQuery({
    queryKey: ['connectors', datasetId],
    queryFn: () => api.getDatasetConnectors(datasetId ?? ''),
    enabled: datasetId !== null,
  })

  const lookup = useMutation({
    mutationFn: (request: LookupRequest) => api.runConnectorLookup(datasetId ?? '', request),
    onSuccess: (fresh: DatasetConnectors) => {
      setPending(null)
      queryClient.setQueryData(['connectors', datasetId], fresh)
      // A lookup is a recipe step, so the rest of the page has to follow it.
      // Looking up again keeps the recipe's key, so the table is told directly.
      queryClient.setQueryData<IssueListResponse>(['issues', datasetId], (current) =>
        current ? { ...current, recipe: fresh.recipe } : current,
      )
      void queryClient.invalidateQueries({ queryKey: ['issues', datasetId] })
      void queryClient.invalidateQueries({ queryKey: ['canvas', datasetId] })
      void queryClient.invalidateQueries({ queryKey: ['preview', datasetId] })
    },
  })

  const toggle = useMutation({
    mutationFn: (change: { connector: ConnectorId; active: boolean }) =>
      api.setConnectorActive(datasetId ?? '', change.connector, change.active),
    onSuccess: (fresh: DatasetConnectors) => {
      queryClient.setQueryData(['connectors', datasetId], fresh)
    },
  })

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const query = datasetId === null ? services : forFile
  const connectors = (datasetId === null ? services.data : forFile.data?.connectors) ?? []
  const offers = forFile.data?.offers ?? []
  const enrichments = forFile.data?.enrichments ?? []
  const consented = new Set<string>(forFile.data?.consented ?? [])
  const hasWork = (id: ConnectorId) =>
    offers.some((offer) => offer.connector === id) ||
    enrichments.some((enrichment) => enrichment.connector === id)
  // Services with something to do in this file come first; the order is otherwise fixed.
  const ordered = [...connectors].sort((a, b) => Number(hasWork(b.id)) - Number(hasWork(a.id)))

  /** Send straight away if the user already agreed for this connector; otherwise ask first. */
  function ask(next: Pending) {
    lookup.reset()
    if (consented.has(next.connector.id)) lookup.mutate(next.request)
    else setPending(next)
  }

  const runningKey = lookup.isPending && lookup.variables ? keyOf(lookup.variables) : null
  const busy = lookup.isPending || toggle.isPending

  return (
    <aside id="connectors-panel" className="connectors" role="dialog" aria-label="Connectors">
      <header className="connectors__head">
        <h2 className="connectors__title">Connectors</h2>
        <button type="button" className="link-button" onClick={onClose}>
          Close
        </button>
      </header>
      <p className="muted small">
        Add columns by looking values up. Nothing is sent until you say so.
      </p>

      {query.isPending ? (
        <Spinner label="Checking what can be looked up…" />
      ) : query.isError ? (
        <ErrorState
          message={query.error.message}
          onRetry={() => void query.refetch()}
          retrying={query.isFetching}
        />
      ) : (
        <>
          {datasetId === null && <p className="notice">Open a file to use these.</p>}
          <ul className="connectors__list">
            {ordered.map((connector) => {
              const mine = offers.filter((offer) => offer.connector === connector.id)
              const done = enrichments.filter((item) => item.connector === connector.id)
              const idle = datasetId !== null && mine.length === 0 && done.length === 0
              // Nothing in this file for it to work on, so there is nothing to switch on.
              // AI fill is started from the Canvas, so it has no such state.
              const nothingToDo = idle && connector.id !== 'ai_fill'
              return (
                <li
                  key={connector.id}
                  className={`service${idle || !connector.enabled ? ' service--idle' : ''}`}
                  aria-label={LOOK[connector.id].name}
                >
                  <div className="service__head">
                    <span className="service__symbol" aria-hidden="true">
                      {LOOK[connector.id].symbol}
                    </span>
                    <span className="service__name">{LOOK[connector.id].name}</span>
                    <InfoTip
                      label={`About ${LOOK[connector.id].name}`}
                      text={`${connector.adds} Service: ${connector.service}. What is sent: ${connector.sends}`}
                    />
                    <span className="service__switch">
                      {!connector.enabled ? (
                        <span className="chip chip--soft">Not set up</span>
                      ) : datasetId === null ? (
                        <span className="chip chip--soft">Available</span>
                      ) : (
                        <label className="switch">
                          <input
                            type="checkbox"
                            role="switch"
                            checked={!nothingToDo && (connector.active ?? false)}
                            disabled={busy || nothingToDo}
                            aria-label={`Use ${LOOK[connector.id].name} for this file`}
                            onChange={(event) =>
                              toggle.mutate({ connector: connector.id, active: event.target.checked })
                            }
                          />
                          <span className="small">
                            {!nothingToDo && connector.active ? 'On' : 'Off'}
                          </span>
                        </label>
                      )}
                    </span>
                  </div>

                  {datasetId !== null && idle && (
                    <p className="service__status muted small">
                      {connector.id === 'ai_fill'
                        ? 'Use it from Canvas → Ideas for this file'
                        : 'Nothing to look up in this file'}
                    </p>
                  )}

                  {done.map((enrichment) => {
                    const key = `step:${enrichment.step_id}`
                    return (
                      <Enrichment
                        key={key}
                        enrichment={enrichment}
                        usable={connector.enabled && (connector.active ?? false)}
                        busy={busy}
                        running={runningKey === key}
                        onLookUp={() =>
                          ask({
                            key,
                            connector,
                            column: enrichment.column,
                            values: null,
                            request: { step_id: enrichment.step_id, consent: false },
                          })
                        }
                      />
                    )
                  })}

                  {mine.map((offer) => {
                    const key = `new:${offer.connector}:${offer.column}`
                    const country = countries[key] ?? ''
                    return (
                      <Offer
                        key={key}
                        offer={offer}
                        usable={connector.enabled && (connector.active ?? false)}
                        country={country}
                        onCountry={(code) => setCountries({ ...countries, [key]: code })}
                        busy={busy}
                        running={runningKey === key}
                        onEnrich={() =>
                          ask({
                            key,
                            connector,
                            column: offer.column,
                            values: offer.distinct_values,
                            request: {
                              connector: offer.connector,
                              column: offer.column,
                              country: offer.countries.length > 0 ? country : null,
                              consent: false,
                            },
                          })
                        }
                      />
                    )
                  })}

                  {pending?.connector.id === connector.id && (
                    <Consent
                      pending={pending}
                      sending={lookup.isPending}
                      onAgree={() => lookup.mutate({ ...pending.request, consent: true })}
                      onCancel={() => setPending(null)}
                    />
                  )}
                </li>
              )
            })}
          </ul>
          {(lookup.error || toggle.error) && (
            <p className="card__error" role="alert">
              {(lookup.error ?? toggle.error)?.message}
            </p>
          )}
        </>
      )}
    </aside>
  )
}

function keyOf(request: LookupRequest): string {
  return request.step_id
    ? `step:${request.step_id}`
    : `new:${request.connector ?? ''}:${request.column ?? ''}`
}

interface OfferProps {
  offer: OfferView
  /** Set up on the server and switched on for this file. */
  usable: boolean
  country: string
  onCountry: (code: string) => void
  busy: boolean
  running: boolean
  onEnrich: () => void
}

function Offer({ offer, usable, country, onCountry, busy, running, onEnrich }: OfferProps) {
  const needsCountry = offer.countries.length > 0
  return (
    <div className="service__work">
      <p className="service__status small">
        Found in “{offer.column}” · {different(offer.distinct_values)}
      </p>
      {usable && needsCountry && (
        <label className="service__country small">
          <span>Country of these postal codes</span>
          <select value={country} disabled={busy} onChange={(e) => onCountry(e.target.value)}>
            <option value="">Choose…</option>
            {offer.countries.map((option) => (
              <option key={option.code} value={option.code}>
                {option.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <button
        type="button"
        className="button"
        disabled={busy || !usable || (needsCountry && !country)}
        title={usable ? undefined : 'Switch this service on first'}
        onClick={onEnrich}
      >
        {running ? 'Looking up…' : 'Enrich'}
      </button>
    </div>
  )
}

interface EnrichmentProps {
  enrichment: EnrichmentView
  usable: boolean
  busy: boolean
  running: boolean
  onLookUp: () => void
}

function Enrichment({ enrichment, usable, busy, running, onLookUp }: EnrichmentProps) {
  const counts = Object.entries(enrichment.counts ?? {})
  const examples = Object.entries(enrichment.examples ?? {})
  const isAi = enrichment.connector === 'ai_fill'
  const action = !enrichment.looked_up
    ? 'Look up'
    : enrichment.out_of_date
      ? 'Refresh prices'
      : enrichment.remaining > 0
        ? `${isAi ? 'Fill in' : 'Look up'} the rest (${formatCount(enrichment.remaining)})`
        : null
  // Which values had no answer, by reason. Kept one hover away, not on the page.
  const detail = examples
    .map(([reason, values]) => {
      const more = (enrichment.counts?.[reason] ?? 0) > values.length ? ', …' : ''
      return `${capitalise(reason)}: ${values.join(', ')}${more}`
    })
    .join('. ')

  return (
    <div className="service__work">
      <p className="service__status small">
        Added {enrichment.into.map((name) => `“${name}”`).join(' and ')} from “{enrichment.column}”
        {enrichment.looked_up ? (
          <>
            {' · '}
            {counts.map(([reason, count]) => `${formatCount(count)} ${reason}`).join(', ')}
            {detail && <InfoTip label="Values without an answer" text={detail} />}
          </>
        ) : (
          ' · not looked up yet'
        )}
      </p>
      {enrichment.connector === 'stock_price' && enrichment.as_of && (
        <p className="muted small">
          As of {enrichment.as_of}
          {enrichment.out_of_date && <span className="chip chip--soft">Out of date</span>}
        </p>
      )}
      {action && (
        <button
          type="button"
          className="button button--secondary"
          disabled={busy || !usable}
          title={usable ? undefined : 'Switch this service on first'}
          onClick={onLookUp}
        >
          {running ? 'Looking up…' : action}
        </button>
      )}
    </div>
  )
}

interface ConsentProps {
  pending: Pending
  sending: boolean
  onAgree: () => void
  onCancel: () => void
}

function Consent({ pending, sending, onAgree, onCancel }: ConsentProps) {
  const { connector, column, values } = pending
  return (
    <div className="connectors__consent" role="alertdialog" aria-label="Before anything is sent">
      <p className="connectors__name">
        Before anything is sent
        <InfoTip
          label="What is sent, and to whom"
          text={`Service: ${connector.service}. What is sent: ${connector.sends} You’re asked once per service and file.`}
        />
      </p>
      <p className="small">
        Looks up {values === null ? 'the values' : different(values)} in “{column}” with{' '}
        {connector.service}.
      </p>
      <div className="card__actions">
        <button type="button" className="button" disabled={sending} onClick={onAgree}>
          {sending ? 'Looking up…' : 'Send and look up'}
        </button>
        <button type="button" className="button button--secondary" disabled={sending} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}

function different(count: number): string {
  return count === 1 ? 'one value' : `${formatCount(count)} values`
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
