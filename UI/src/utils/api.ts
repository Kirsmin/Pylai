export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/+$/, '') ?? ''

export class ApiError extends Error {
  status: number
  errorCode?: string
  data?: ApiEnvelope

  constructor(message: string, status: number, errorCode?: string, data?: ApiEnvelope) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errorCode = errorCode
    this.data = data
  }
}

export interface ApiEnvelope {
  error?: string
  errorCode?: string
  /** @deprecated Compatibility-only; successful api() calls synthesize true in memory. */
  success?: boolean
  [key: string]: unknown
}

export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    redirect: 'manual'
  })
}

async function readEnvelope(res: Response): Promise<ApiEnvelope | null> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text) as ApiEnvelope
  } catch (err) {
    console.warn('[API] 响应不是有效 JSON', { status: res.status, err })
    return null
  }
}

export async function api<T = ApiEnvelope>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await apiFetch(path, { ...init, headers })

  // Keep explicit redirect semantics for OAuth/external-login flows when fetch() uses redirect=manual.
  if (res.type === 'opaqueredirect' || (res.status >= 300 && res.status < 400)) {
    const location = res.headers.get('location') ?? ''
    throw new ApiError('需要重定向', res.status, 'redirect_required', { location })
  }

  const data = await readEnvelope(res)

  // HTTP status is the single transport-level success/failure signal.
  if (!res.ok) {
    throw new ApiError(
      data?.error || `请求失败 (${res.status})`,
      res.status,
      data?.errorCode,
      data ?? undefined
    )
  }

  // Transitional source compatibility for views not migrated in this change. The value is never
  // received from the wire and is deliberately non-enumerable.
  if (data && typeof data === 'object' && !Object.prototype.hasOwnProperty.call(data, 'success')) {
    Object.defineProperty(data, 'success', { value: true, enumerable: false, configurable: true })
  }
  return data as T
}
