export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/+$/, '') ?? ''

export function rawFetch(input: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${input}`, {
    ...init,
    credentials: 'include'
  })
}

export class ApiError extends Error {
  status: number
  errorCode?: string
  data?: any

  constructor(message: string, status: number, errorCode?: string, data?: any) {
    super(message)
    this.status = status
    this.errorCode = errorCode
    this.data = data
  }
}

export async function parseApiResponse<T>(res: Response): Promise<T | undefined> {
  if (res.status === 204) return undefined
  const data = await res.json().catch(() => null)
  // 后端 ApiEnvelopeResultFilter 会从 /api 响应中剥离顶层 success 字段，
  // 这里在内存中补齐（不可枚举），与各视图按 data.success 判定的兼容层保持一致。
  if (data && typeof data === 'object' && !Object.prototype.hasOwnProperty.call(data, 'success')) {
    Object.defineProperty(data, 'success', { value: true, enumerable: false, configurable: true })
  }
  if (!res.ok) {
    throw new ApiError(
      data?.error || `请求失败（${res.status}）`,
      res.status,
      data?.errorCode,
      data
    )
  }
  return data as T
}

// 用户侧 Cookie-CSRF（双提交）：/api 下非 /admin 路径的写请求由后端 CookieCsrfMiddleware 校验，
// token 由 GET /api/auth/csrf 签发（可读 Cookie Pylaios.Csrf），与 /api/admin 的 Admin BFF token 相互独立。
const USER_CSRF_COOKIE_PATTERN = /(?:^|;\s*)Pylaios\.Csrf=([^;]*)/

export function readUserCsrfToken(): string | null {
  const match = document.cookie.match(USER_CSRF_COOKIE_PATTERN)?.[1]
  return match ? decodeURIComponent(match) : null
}

export async function ensureUserCsrfToken(): Promise<void> {
  if (!readUserCsrfToken()) {
    await rawFetch('/api/auth/csrf').catch(() => undefined)
  }
}

export function userCsrfHeaders(): Record<string, string> {
  const token = readUserCsrfToken()
  return token ? { 'X-CSRF-Token': token } : {}
}

async function isCsrfChallenge(res: Response): Promise<boolean> {
  if (res.status !== 403) return false
  const probe = await res.clone().json().catch(() => null)
  return probe?.errorCode === 'csrf_invalid'
}

/** 用户侧写请求：自动附带 X-CSRF-Token；CSRF 挑战时补签重放一次。 */
export async function userCsrfFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const send = async (): Promise<Response> => {
    await ensureUserCsrfToken()
    const headers = new Headers(init.headers)
    for (const [key, value] of Object.entries(userCsrfHeaders())) headers.set(key, value)
    return rawFetch(input, { ...init, headers })
  }
  const response = await send()
  if (!(await isCsrfChallenge(response))) return response
  await rawFetch('/api/auth/csrf').catch(() => undefined)
  const headers = new Headers(init.headers)
  for (const [key, value] of Object.entries(userCsrfHeaders())) headers.set(key, value)
  return rawFetch(input, { ...init, headers })
}
