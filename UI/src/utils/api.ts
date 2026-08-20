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
  success: boolean
  error?: string
  errorCode?: string
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
  const data = await readEnvelope(res)

  if (!res.ok) {
    throw new ApiError(
      data?.error || `请求失败 (${res.status})`,
      res.status,
      data?.errorCode,
      data ?? undefined
    )
  }

  return data as T
}
