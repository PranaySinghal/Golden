import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api, type DatasetSummary } from './api/client'
import { ErrorState, Spinner } from './components/states'
import { ReviewPage } from './features/review/ReviewPage'
import { UploadPage } from './features/upload/UploadPage'

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
  // A file in the address means the reader was already past the summary.
  const [reviewing, setReviewing] = useState(datasetFromUrl() !== null)

  // Only runs when the page was opened with a file already in the address.
  const restored = useQuery({
    queryKey: ['dataset', wantedId],
    queryFn: () => api.getDataset(wantedId ?? ''),
    enabled: wantedId !== null && chosen === null,
    retry: false,
  })
  const dataset = chosen ?? restored.data ?? null

  function choose(next: DatasetSummary | null) {
    setChosen(next)
    setWantedId(next?.id ?? null)
    setReviewing(false)
    rememberInUrl(next?.id ?? null)
  }

  return (
    <div className="app">
      <header className="masthead">
        <h1 className="masthead__title">TidyLab</h1>
        <p className="masthead__tagline">Tidy your data. See what it was hiding.</p>
      </header>
      <main className="page">
        {restored.isFetching && <Spinner label="Opening your file…" />}
        {restored.isError && (
          <ErrorState message={restored.error.message} onRetry={() => choose(null)} />
        )}
        {dataset && reviewing ? (
          <ReviewPage dataset={dataset} onStartOver={() => choose(null)} />
        ) : (
          <UploadPage
            dataset={dataset}
            onDataset={choose}
            onReview={() => setReviewing(true)}
          />
        )}
      </main>
    </div>
  )
}
