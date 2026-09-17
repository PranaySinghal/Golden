import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
export type DatasetSummary = components['schemas']['DatasetSummary']
export type ColumnProfile = components['schemas']['ColumnProfile']
export type SemanticRole = components['schemas']['SemanticRole']
export type HeaderMode = components['schemas']['HeaderMode']
export type ReingestRequest = components['schemas']['ReingestRequest']
export type UploadLimits = components['schemas']['UploadLimits']
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

export interface UploadOptions {
  sheet?: string | null
  header?: HeaderMode
}

function uploadDataset(file: File, options: UploadOptions = {}): Promise<DatasetSummary> {
  const form = new FormData()
  form.append('file', file)
  if (options.sheet) form.append('sheet', options.sheet)
  if (options.header) form.append('header', options.header)
  // No Content-Type header: the browser sets the multipart boundary itself.
  return request<DatasetSummary>('/api/datasets', { method: 'POST', body: form })
}

function reingestDataset(id: string, body: ReingestRequest): Promise<DatasetSummary> {
  return request<DatasetSummary>(`/api/datasets/${encodeURIComponent(id)}/reingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export const api = {
  getHealth: () => request<HealthResponse>('/api/health'),
  getUploadLimits: () => request<UploadLimits>('/api/upload-limits'),
  getDataset: (id: string) => request<DatasetSummary>(`/api/datasets/${encodeURIComponent(id)}`),
  uploadDataset,
  reingestDataset,
}
