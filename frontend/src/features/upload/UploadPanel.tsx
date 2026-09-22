import { useMutation, useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'

import { api, type DatasetSummary } from '../../api/client'
import { DropZone } from './DropZone'
import { formatBytes } from './format'

interface UploadPanelProps {
  onUploaded: (dataset: DatasetSummary) => void
}

export function UploadPanel({ onUploaded }: UploadPanelProps) {
  const [tooLarge, setTooLarge] = useState<string | null>(null)
  // Picked before the file, because choosing the file starts the upload.
  const [recipe, setRecipe] = useState<File | null>(null)
  const recipeInput = useRef<HTMLInputElement>(null)

  const limits = useQuery({ queryKey: ['upload-limits'], queryFn: api.getUploadLimits })
  const maxBytes = limits.data?.max_upload_bytes ?? null

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDataset(file, { recipe }),
    onSuccess: onUploaded,
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

  const error = tooLarge ?? upload.error?.message ?? null
  return (
    <section className="upload" aria-labelledby="upload-title">
      <h2 id="upload-title" className="visually-hidden">
        Upload a file
      </h2>
      <DropZone onFile={handleFile} maxBytes={maxBytes} disabled={upload.isPending} />
      <p className="upload__recipe">
        {recipe ? (
          <>
            Using the steps in <strong>{recipe.name}</strong>{' '}
            <button
              type="button"
              className="link-button"
              disabled={upload.isPending}
              onClick={() => setRecipe(null)}
            >
              Remove
            </button>
          </>
        ) : (
          <button
            type="button"
            className="link-button"
            disabled={upload.isPending}
            onClick={() => recipeInput.current?.click()}
          >
            Cleaned a file like this before? Use those steps again
          </button>
        )}
        <input
          ref={recipeInput}
          type="file"
          accept=".json"
          className="visually-hidden"
          aria-label="Choose a saved recipe file"
          disabled={upload.isPending}
          onChange={(event) => {
            const chosen = event.target.files?.[0] ?? null
            // Reset so picking the same file again still counts.
            event.target.value = ''
            setRecipe(chosen)
          }}
        />
      </p>
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
