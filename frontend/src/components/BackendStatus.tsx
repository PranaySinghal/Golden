import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'

export function BackendStatus() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.getHealth, retry: false })

  if (health.isPending) {
    return (
      <p className="status" role="status">
        Checking the connection…
      </p>
    )
  }
  if (health.isError) {
    return (
      <div className="status status--error" role="alert">
        <p>{health.error.message}</p>
        <button type="button" onClick={() => void health.refetch()}>
          Try again
        </button>
      </div>
    )
  }
  return (
    <p className="status status--ok" role="status">
      Connected and ready.
    </p>
  )
}
