import type { components } from './schema'

export type HealthResponse = components['schemas']['HealthResponse']
export type DatasetSummary = components['schemas']['DatasetSummary']
export type ColumnProfile = components['schemas']['ColumnProfile']
export type SemanticRole = components['schemas']['SemanticRole']
export type HeaderMode = components['schemas']['HeaderMode']
export type ReingestRequest = components['schemas']['ReingestRequest']
export type UploadLimits = components['schemas']['UploadLimits']
export type IssueListResponse = components['schemas']['IssueListResponse']
export type IssueView = components['schemas']['IssueView']
export type AskQuestion = components['schemas']['AskQuestion']
export type Choice = components['schemas']['Choice']
export type Tier = components['schemas']['Tier']
export type RecipeResponse = components['schemas']['RecipeResponse']
export type StepView = components['schemas']['StepView']
export type Preview = components['schemas']['Preview']
export type ComparisonResponse = components['schemas']['ComparisonResponse']
export type AnswerCardView = components['schemas']['AnswerCardView']
export type GroupChangeView = components['schemas']['GroupChangeView']
export type MergedNote = components['schemas']['MergedNote']
export type WhyView = components['schemas']['WhyView']
export type Measure = components['schemas']['Measure']
export type PreviewRow = components['schemas']['PreviewRow']
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

function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

function datasetPath(id: string, rest = ''): string {
  return `/api/datasets/${encodeURIComponent(id)}${rest}`
}

export interface PreviewQuery {
  issueId?: string
  choiceId?: string
  stepId?: string
  limit?: number
}

function getPreview(id: string, query: PreviewQuery): Promise<Preview> {
  const params = new URLSearchParams()
  if (query.issueId) params.set('issue_id', query.issueId)
  if (query.choiceId) params.set('choice_id', query.choiceId)
  if (query.stepId) params.set('step_id', query.stepId)
  if (query.limit) params.set('limit', String(query.limit))
  return request<Preview>(datasetPath(id, `/preview?${params.toString()}`))
}

export interface DownloadedFile {
  blob: Blob
  filename: string
}

async function download(path: string): Promise<DownloadedFile> {
  let response: Response
  try {
    response = await fetch(path)
  } catch {
    throw new ApiError(0, 'network_error', NETWORK_MESSAGE)
  }
  if (!response.ok) throw await toApiError(response)
  return { blob: await response.blob(), filename: filenameFrom(response) }
}

/** The name the server asked us to save it as, percent-encoded per RFC 5987. */
function filenameFrom(response: Response): string {
  const header = response.headers.get('content-disposition') ?? ''
  const match = /filename\*=UTF-8''([^;]+)/i.exec(header)
  return match ? decodeURIComponent(match[1]) : 'tidylab-download'
}

export const api = {
  getHealth: () => request<HealthResponse>('/api/health'),
  getUploadLimits: () => request<UploadLimits>('/api/upload-limits'),
  getDataset: (id: string) => request<DatasetSummary>(datasetPath(id)),
  uploadDataset,
  reingestDataset,
  getIssues: (id: string) => request<IssueListResponse>(datasetPath(id, '/issues')),
  acceptIssue: (id: string, issueId: string, choiceId?: string | null) =>
    send<RecipeResponse>(datasetPath(id, `/issues/${encodeURIComponent(issueId)}/accept`), 'POST', {
      choice_id: choiceId ?? null,
    }),
  rejectIssue: (id: string, issueId: string) =>
    send<RecipeResponse>(datasetPath(id, `/issues/${encodeURIComponent(issueId)}/reject`), 'POST'),
  getRecipe: (id: string) => request<RecipeResponse>(datasetPath(id, '/recipe')),
  setStepEnabled: (id: string, stepId: string, enabled: boolean) =>
    send<RecipeResponse>(datasetPath(id, `/recipe/steps/${encodeURIComponent(stepId)}`), 'PATCH', {
      enabled,
    }),
  removeStep: (id: string, stepId: string) =>
    send<RecipeResponse>(datasetPath(id, `/recipe/steps/${encodeURIComponent(stepId)}`), 'DELETE'),
  undoRecipe: (id: string) => send<RecipeResponse>(datasetPath(id, '/recipe/undo'), 'POST'),
  getPreview,
  getComparison: (id: string) => request<ComparisonResponse>(datasetPath(id, '/compare')),
  exportDataset: (id: string, format: 'csv' | 'recipe') => download(datasetPath(id, `/export?format=${format}`)),
}
