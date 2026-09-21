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
      <svg
        className="dropzone__icon"
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <path
          d="M6 4.5h13.5L26 11v16.5H6V4.5Z"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <path d="M19 4.5V11h6.5M11 17h10M11 22h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
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
      <p className="dropzone__formats">{ACCEPTED_EXTENSIONS.join(' · ')}</p>
      <p className="dropzone__note">
        An Excel workbook opens one sheet at a time — you can switch sheets once it is open.
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
