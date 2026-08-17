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
