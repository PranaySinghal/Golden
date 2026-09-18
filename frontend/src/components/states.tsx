import type { ReactNode } from 'react'

export function Spinner({ label }: { label: string }) {
  return (
    <p className="status" role="status">
      {label}
    </p>
  )
}

export function ErrorState({
  message,
  onRetry,
  retrying,
}: {
  message: string
  onRetry?: () => void
  retrying?: boolean
}) {
  return (
    <div className="alert" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button
          type="button"
          className="button button--secondary"
          onClick={onRetry}
          disabled={retrying}
        >
          {retrying ? 'Trying…' : 'Try again'}
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {children}
    </div>
  )
}
