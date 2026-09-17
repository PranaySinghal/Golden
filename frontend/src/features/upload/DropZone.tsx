import { useRef, useState, type DragEvent } from 'react'

import { formatBytes } from './format'

const ACCEPTED_EXTENSIONS = ['.csv', '.tsv', '.txt', '.xlsx', '.xlsm']

interface DropZoneProps {
  onFile: (file: File) => void
  maxBytes: number | null
  disabled?: boolean
}

export function DropZone({ onFile, maxBytes, disabled = false }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file && !disabled) onFile(file)
  }

  return (
    <div
      className={`dropzone${dragging ? ' dropzone--active' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <p className="dropzone__title">Drop a CSV or Excel file here</p>
      <p className="dropzone__hint">
        or{' '}
        <button
          type="button"
          className="link-button"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
        >
          choose a file
        </button>
        {maxBytes != null && <> · up to {formatBytes(maxBytes)}</>}
      </p>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_EXTENSIONS.join(',')}
        className="visually-hidden"
        aria-label="Choose a file to upload"
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0]
          // Reset so choosing the same file again still triggers a change.
          event.target.value = ''
          if (file) onFile(file)
        }}
      />
    </div>
  )
}
