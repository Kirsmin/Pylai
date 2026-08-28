import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, ensureCsrfToken, ApiError } from '@/utils/api'
export { API_BASE, apiFetch } from '@/utils/api'

export interface User {
  uid: string
  name: string
  displayName: string
  group: string
  email: string
}

interface CurrentAccountResponse {
  user: User
}

export const useAuthStore = defineStore('auth', () => {
  // Identity data is intentionally memory-only. The authoritative session is the HttpOnly cookie.
  const user = ref<User | null>(null)
  const isAuthenticated = computed(() => user.value !== null)

  function clearSession() {
    user.value = null
  }

  // Keep the legacy second argument for source compatibility; remember-me is enforced server-side
  // by the authentication cookie and never by local/sessionStorage.
  function login(userData: User, _remember = false) {
    user.value = userData
    void ensureCsrfToken()
  }

  async function logout() {
    try {
      await api('/api/auth/logout', { method: 'POST' })
    } catch (err) {
      console.warn('[Auth] 服务端登出失败，本地内存状态仍将清除', err)
    } finally {
      clearSession()
    }
  }

  async function validateSession(): Promise<boolean> {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 3000)
    try {
      const data = await api<CurrentAccountResponse>('/api/auth/account', {
        signal: controller.signal
      })
      user.value = data.user
      await ensureCsrfToken()
      return true
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // 正常未登录，静默处理
      } else if (err instanceof Error && err.name === 'AbortError') {
        // 超时，静默处理
      } else {
        console.warn('[Auth] 会话校验异常', err)
      }
      clearSession()
      return false
    } finally {
      clearTimeout(timeoutId)
    }
  }

  async function init() {
    await validateSession()
  }

  return { user, isAuthenticated, login, logout, validateSession, init }
})
