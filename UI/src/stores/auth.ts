import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, apiFetch } from '@/utils/api'

export interface User {
  uid: string
  name: string
  displayName: string
  group: string
  email: string
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const isAuthenticated = computed(() => user.value !== null)

  function persistToSession(u: User) {
    sessionStorage.setItem('pylai_auth_user', JSON.stringify(u))
  }

  function persistToLocal(u: User | null, remember: boolean) {
    if (remember && u) {
      localStorage.setItem('pylai_auth_user', JSON.stringify(u))
    } else {
      localStorage.removeItem('pylai_auth_user')
    }
  }

  function clearStorage() {
    sessionStorage.removeItem('pylai_auth_user')
    localStorage.removeItem('pylai_auth_user')
  }

  function clearSession() {
    user.value = null
    clearStorage()
  }

  function login(userData: User, remember: boolean) {
    user.value = userData
    persistToSession(userData)
    persistToLocal(userData, remember)
  }

  async function logout() {
    try {
      await api('/api/auth/logout', { method: 'POST' })
    } catch (err) {
      // 本地状态仍必须清除，但网络/服务端失败不能静默吞掉。
      console.warn('[Auth] 服务端登出失败，本地会话仍将清除', err)
    } finally {
      clearSession()
    }
  }

  async function validateSession(): Promise<boolean> {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 3000)

    try {
      const res = await apiFetch('/api/auth/account/sessions', {
        signal: controller.signal
      })

      if (!res.ok) {
        clearSession()
        return false
      }

      return true
    } catch (err) {
      // Fail Closed：网络异常、超时或浏览器 fetch 失败都不能当作“会话有效”。
      console.warn('[Auth] 会话校验失败，按未登录处理', err)
      clearSession()
      return false
    } finally {
      clearTimeout(timeoutId)
    }
  }

  async function init() {
    const savedUser =
      sessionStorage.getItem('pylai_auth_user') ??
      localStorage.getItem('pylai_auth_user')

    if (!savedUser) return

    let parsed: User
    try {
      parsed = JSON.parse(savedUser) as User
    } catch (err) {
      console.warn('[Auth] 本地用户缓存损坏，已清除', err)
      clearSession()
      return
    }

    user.value = parsed
    await validateSession()
  }

  return { user, isAuthenticated, login, logout, validateSession, init }
})
