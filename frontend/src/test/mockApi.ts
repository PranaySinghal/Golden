import { vi } from 'vitest'

export type Handler = (init?: RequestInit) => Response | Promise<Response>

/**
 * Serves canned answers keyed by "METHOD /url", and throws on anything a test
 * didn't plan for, so an unexpected request fails loudly instead of hanging.
 */
export function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${String(input)}`
    const handler = routes[key] ?? routes[key.split('?')[0]]
    if (!handler) throw new Error(`Unexpected request: ${key}`)
    return handler(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
