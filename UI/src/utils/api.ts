import { API_BASE } from '@/stores/auth'

export class ApiError extends Error {
  status: number
  errorCode?: string
  data?: ApiEnvelope

  constructor(message: string, status: number, errorCode?: string, data?: ApiEnvelope) {
    super(message)
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

export async function api<T = ApiEnvelope>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: 'include',
    redirect: 'manual'
  })

  const data = (await res.json().catch(() => null)) as ApiEnvelope | null
  if (!res.ok) {
    throw new ApiError(data?.error || `请求失败 (${res.status})`, res.status, data?.errorCode, data ?? undefined)
  }
  return data as T
}
