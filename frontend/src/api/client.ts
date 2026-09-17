import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
type ErrorResponse = components['schemas']['ErrorResponse']

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

const NETWORK_MESSAGE = "We couldn't reach the server. Check that it's running and try again."
const UNKNOWN_MESSAGE = 'Something went wrong on our side. Please try again.'
const UNREACHABLE_STATUSES = new Set([502, 503, 504])

function isErrorResponse(body: unknown): body is ErrorResponse {
  if (typeof body !== 'object' || body === null) return false
  const candidate = body as Record<string, unknown>
  return typeof candidate.code === 'string' && typeof candidate.message === 'string'
}

async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // Proxies and crashed servers return HTML or nothing; fall through to a generic message.
    body = null
  }
  if (isErrorResponse(body)) {
    return new ApiError(response.status, body.code, body.message)
  }
  // The dev proxy and hosting gateways answer 502-504 when the backend is down,
  // which is a connection problem rather than a server bug.
  if (UNREACHABLE_STATUSES.has(response.status)) {
    return new ApiError(response.status, 'network_error', NETWORK_MESSAGE)
  }
  return new ApiError(response.status, 'unknown_error', UNKNOWN_MESSAGE)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError(0, 'network_error', NETWORK_MESSAGE)
  }
  if (!response.ok) {
    throw await toApiError(response)
  }
  return (await response.json()) as T
}

export const api = {
  getHealth: () => request<HealthResponse>('/api/health'),
}
