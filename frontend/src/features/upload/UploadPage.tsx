import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api, type DatasetSummary, type ReingestRequest } from '../../api/client'
import { DatasetOverview } from './DatasetOverview'
import { DropZone } from './DropZone'
import { formatBytes } from './format'

interface UploadPageProps {
  dataset: DatasetSummary | null
  onDataset: (dataset: DatasetSummary | null) => void
  onReview: () => void
}

export function UploadPage({ dataset, onDataset, onReview }: UploadPageProps) {
  const [tooLarge, setTooLarge] = useState<string | null>(null)

  const limits = useQuery({ queryKey: ['upload-limits'], queryFn: api.getUploadLimits })
  const maxBytes = limits.data?.max_upload_bytes ?? null

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDataset(file),
    onSuccess: onDataset,
  })
  const reread = useMutation({
    mutationFn: ({ id, request }: { id: string; request: ReingestRequest }) =>
      api.reingestDataset(id, request),
    onSuccess: onDataset,
  })

  function handleFile(file: File) {
    upload.reset()
    // Checked here too so a big file isn't sent only to be turned away.
    if (maxBytes != null && file.size > maxBytes) {
      setTooLarge(
        `This file is ${formatBytes(file.size)}, which is over the ${formatBytes(maxBytes)} ` +
          'limit. Try a smaller file or split it up.',
      )
      return
    }
    setTooLarge(null)
    upload.mutate(file)
  }

  function startOver() {
    onDataset(null)
    setTooLarge(null)
    upload.reset()
    reread.reset()
  }

  if (dataset) {
    return (
      <DatasetOverview
        dataset={dataset}
        rereading={reread.isPending}
        rereadError={reread.error?.message ?? null}
        onReread={(request) => reread.mutate({ id: dataset.id, request })}
        onUploadAnother={startOver}
        onReview={onReview}
      />
    )
  }

  const error = tooLarge ?? upload.error?.message ?? null
  return (
    <section className="upload" aria-labelledby="upload-title">
      <h2 id="upload-title" className="visually-hidden">
        Upload a file
      </h2>
      <DropZone onFile={handleFile} maxBytes={maxBytes} disabled={upload.isPending} />
      {upload.isPending && (
        <p className="status" role="status">
          Reading your file…
        </p>
      )}
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {limits.isError && !error && (
        <div className="alert" role="alert">
          <p>{limits.error.message}</p>
          <button type="button" className="button button--secondary" onClick={() => void limits.refetch()}>
            Try again
          </button>
        </div>
      )}
    </section>
  )
}
