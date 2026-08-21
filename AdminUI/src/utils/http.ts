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
