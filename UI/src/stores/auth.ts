import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/utils/api'






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

  function login(userData: User, remember: boolean) {
    user.value = userData
    persistToSession(userData)
    persistToLocal(userData, remember)
  }


  async function logout() {
    try {
      await api('/api/auth/logout', { method: 'POST' })
    } catch {

    }
    user.value = null
    clearStorage()
  }


  async function validateSession(): Promise<boolean> {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 3000)
    try {
      const res = await apiFetch('/api/auth/account/sessions', {
        signal: controller.signal
      })
      return res.ok
    } catch {


      return true
    } finally {
      clearTimeout(timeoutId)
    }
  }


  async function init() {
    let savedUser: string | null = null


    savedUser = sessionStorage.getItem('pylai_auth_user')


    if (!savedUser) {
      savedUser = localStorage.getItem('pylai_auth_user')
    }

    if (!savedUser) return


    let parsed: User
    try {
      parsed = JSON.parse(savedUser)
    } catch {
      clearStorage()
      return
    }


    user.value = parsed


    const valid = await validateSession()
    if (!valid) {

      user.value = null
      clearStorage()
    }
  }

  return { user, isAuthenticated, login, logout, init }
})
