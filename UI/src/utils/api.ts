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

// Cookie-CSRF（双提交）：经 Pylaios.Auth Cookie 发起的状态修改请求必须附带 X-CSRF-Token，
// token 由 GET /api/auth/csrf 签发（可读 Cookie Pylaios.Csrf）；Bearer UserToken 路径不受影响。
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const CSRF_COOKIE_PATTERN = /(?:^|;\s*)Pylaios\.Csrf=([^;]*)/

function readCsrfToken(): string | null {
  const match = document.cookie.match(CSRF_COOKIE_PATTERN)?.[1]
  return match ? decodeURIComponent(match) : null
}

/** 确保存在 CSRF Cookie（仅在已认证会话下有意义；失败静默，由 403 自愈兜底）。 */
export async function ensureCsrfToken(): Promise<void> {
  try {
    await apiFetch('/api/auth/csrf')
  } catch {
    // 忽略：匿名状态下无需 CSRF token
  }
}

/** 手工构造 fetch（如需自行处理 302）时附带 CSRF 头；匿名状态返回空对象。 */
export function csrfHeaders(): Record<string, string> {
  const token = readCsrfToken()
  return token ? { 'X-CSRF-Token': token } : {}
}

async function performRequest(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers)
  if (init?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (UNSAFE_METHODS.has((init?.method ?? 'GET').toUpperCase())) {
    const token = readCsrfToken()
    if (token) headers.set('X-CSRF-Token', token)
  }
  return apiFetch(path, { ...init, headers })
}

async function isCsrfChallenge(res: Response, method: string | undefined): Promise<boolean> {
  if (res.status !== 403 || !UNSAFE_METHODS.has((method ?? 'GET').toUpperCase())) return false
  const probe = await readEnvelope(res.clone())
  return probe?.errorCode === 'csrf_invalid'
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
  let res = await performRequest(path, init)

  // 自愈：CSRF Cookie 缺失/过期时补签一次并重放（仅一次）
  if (await isCsrfChallenge(res, init?.method)) {
    await ensureCsrfToken()
    res = await performRequest(path, init)
  }

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
