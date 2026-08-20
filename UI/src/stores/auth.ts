import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api, ApiError } from '@/utils/api'






export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/+$/, '') ?? ''





export function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${input}`, {
    ...init,
    credentials: 'include',
    redirect: 'manual'
  })
}

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

  function login(userData: User) {
    user.value = userData
  }

  async function logout() {
    try {
      await api('/api/auth/logout', { method: 'POST' })
    } catch {

    }
    user.value = null
  }

  async function validateSession(): Promise<boolean> {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 3000)
    try {
      const res = await apiFetch('/api/auth/account/sessions', {
        signal: controller.signal
      })
      if (res.status === 401 || res.status === 403) {
        user.value = null
      }
      return res.ok
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        user.value = null
      }
      return false
    } finally {
      clearTimeout(timeoutId)
    }
  }

  async function init() {
    try {
      const data = await api<{ authenticated?: boolean; name?: string; displayName?: string; uid?: string; group?: string; email?: string }>('/')
      if (data.authenticated) {
        user.value = {
          uid: data.uid ?? '',
          name: data.name ?? '',
          displayName: data.displayName ?? data.name ?? '',
          group: data.group ?? '',
          email: data.email ?? ''
        }
        return
      }
    } catch {
    }
    user.value = null
  }

  return { user, isAuthenticated, login, logout, init }
})
