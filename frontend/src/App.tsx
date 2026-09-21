import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api, type DatasetSummary } from './api/client'
import { SiteNav } from './components/SiteNav'
import { ErrorState, Spinner } from './components/states'
import { LandingPage } from './features/landing/LandingPage'
import { ReviewPage } from './features/review/ReviewPage'

/** The file being worked on is kept in the address, so a refresh doesn't lose it. */
function datasetFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('dataset')
}

function rememberInUrl(id: string | null) {
  const url = new URL(window.location.href)
  if (id) url.searchParams.set('dataset', id)
  else url.searchParams.delete('dataset')
  window.history.replaceState(null, '', url)
}

export default function App() {
  const [chosen, setChosen] = useState<DatasetSummary | null>(null)
  const [wantedId, setWantedId] = useState<string | null>(datasetFromUrl)

  // Only runs when the page was opened with a file already in the address.
  const restored = useQuery({
    queryKey: ['dataset', wantedId],
    queryFn: () => api.getDataset(wantedId ?? ''),
    enabled: wantedId !== null && chosen === null,
    retry: false,
  })
  const dataset = chosen ?? restored.data ?? null

  /** A freshly uploaded file, or the same file read again with new options. */
  function openDataset(next: DatasetSummary) {
    setChosen(next)
    setWantedId(next.id)
    rememberInUrl(next.id)
  }

  function goHome() {
    setChosen(null)
    setWantedId(null)
    rememberInUrl(null)
    window.scrollTo(0, 0)
  }

  // A file named in the address is being fetched: that reader is on their way to
  // the analysis, so don't flash the landing page at them on the way.
  const restoring = wantedId !== null && chosen === null && restored.isPending
  const onLanding = dataset === null && !restoring && !restored.isError

  return (
    <div className="app">
      <SiteNav variant={onLanding ? 'landing' : 'analysis'} onHome={goHome} />
      <main className="page">
        {restored.isError ? (
          <ErrorState message={restored.error.message} onRetry={goHome} />
        ) : restoring ? (
          <Spinner label="Opening your file…" />
        ) : dataset ? (
          <ReviewPage dataset={dataset} onDataset={openDataset} onStartOver={goHome} />
        ) : (
          <LandingPage onUploaded={openDataset} />
        )}
      </main>
    </div>
  )
}
