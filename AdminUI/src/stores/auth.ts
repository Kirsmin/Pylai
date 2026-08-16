import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { API_BASE, ApiError, ADMIN_REDIRECT_URI, parseApiResponse, rawFetch } from '@/utils/http'
import { randomString, sha256Base64Url } from '@/utils/pkce'
import type { AdminCapability, AdminCapabilitiesResponse, AdminCapabilityUser } from '@/types/admin'

const CLIENT_ID = 'pylai-admin'
const SCOPE = 'openid profile:basic profile:mail profile:role offline_access'
const SESSION_KEY = 'pylai_admin_session'
const OAUTH_KEY = 'pylai_admin_oauth'

interface StoredSession {
  accessToken: string
  refreshToken: string
  expiresAt: number
}

interface StoredOAuth {
  state: string
  verifier: string
}

function readSession(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    return raw ? JSON.parse(raw) as StoredSession : null
  } catch {
    return null
  }
}

function writeSession(session: StoredSession) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

function clearSessionStorage() {
  sessionStorage.removeItem(SESSION_KEY)
  sessionStorage.removeItem(OAUTH_KEY)
}

export const useAuthStore = defineStore('admin-auth', () => {
  const initialized = ref(false)
  const starting = ref(false)
  const accessToken = ref('')
  const refreshToken = ref('')
  const expiresAt = ref(0)
  const user = ref<AdminCapabilityUser | null>(null)
  const capabilities = ref<AdminCapability[]>([])
  const loginError = ref('')

  const isAuthenticated = computed(() => user.value !== null && accessToken.value !== '')
  const firstCapability = computed(() => capabilities.value[0] ?? null)
  const displayName = computed(() => user.value?.displayName || user.value?.name || '')
  const group = computed(() => user.value?.group?.toLowerCase() ?? '')

  function hasCapability(key: string): boolean {
    return capabilities.value.some((c) => c.key === key)
  }

  function capability(key: string): AdminCapability | null {
    return capabilities.value.find((c) => c.key === key) ?? null
  }

  function startLogin() {
    if (starting.value) return
    starting.value = true
    loginError.value = ''

    try {
      const state = randomString(16)
      const verifier = randomString(64)
      const nonce = randomString(16)
      sessionStorage.setItem(OAUTH_KEY, JSON.stringify({ state, verifier } as StoredOAuth))

      const params = new URLSearchParams({
        response_type: 'code',
        client_id: CLIENT_ID,
        redirect_uri: ADMIN_REDIRECT_URI,
        scope: SCOPE,
        state,
        nonce,
        code_challenge_method: 'S256'
      })

      sha256Base64Url(verifier).then((challenge) => {
        params.set('code_challenge', challenge)
        window.location.assign(`${API_BASE}/connect/authorize?${params.toString()}`)
      }).catch(() => {
        loginError.value = '当前浏览器无法生成安全登录参数'
        starting.value = false
      })
    } catch {
      loginError.value = '无法发起登录，请刷新后重试'
      starting.value = false
    }
  }

  async function applyTokenData(data: any) {
    accessToken.value = data?.access_token as string
    refreshToken.value = data?.refresh_token as string
    expiresAt.value = Date.now() + Number(data?.expires_in ?? 3600) * 1000
    writeSession({
      accessToken: accessToken.value,
      refreshToken: refreshToken.value,
      expiresAt: expiresAt.value
    })
  }

  async function exchangeToken(params: URLSearchParams): Promise<boolean> {
    const res = await rawFetch('/connect/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: params.toString()
    })
    const data = await res.json().catch(() => null)
    if (!res.ok || !data?.access_token) {
      throw new Error(data?.error_description || data?.error || '通过 Pylai 通行证登录失败')
    }
    await applyTokenData(data)
    return true
  }

  async function handleCallback(code: string, state: string): Promise<boolean> {
    let stored: StoredOAuth | null = null
    try {
      stored = JSON.parse(sessionStorage.getItem(OAUTH_KEY) || 'null') as StoredOAuth | null
    } catch {
      stored = null
    }
    sessionStorage.removeItem(OAUTH_KEY)

    if (!stored || !state || stored.state !== state) {
      loginError.value = '登录回调校验失败，请重新登录'
      return false
    }

    const params = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: CLIENT_ID,
      code,
      redirect_uri: ADMIN_REDIRECT_URI,
      code_verifier: stored.verifier
    })

    await exchangeToken(params)
    await loadCapabilities()
    return true
  }

  async function refreshAccessToken(): Promise<boolean> {
    if (!refreshToken.value) return false
    try {
      const params = new URLSearchParams({
        grant_type: 'refresh_token',
        client_id: CLIENT_ID,
        refresh_token: refreshToken.value
      })
      await exchangeToken(params)
      return true
    } catch {
      clearLocal()
      return false
    }
  }

  async function loadCapabilities() {
    if (!accessToken.value) throw new ApiError('未登录', 401, 'unauthorized')
    const data = await request<AdminCapabilitiesResponse>('/api/admin/capabilities')
    if (!data?.success) {
      throw new Error(data?.error || '无法获取管理能力')
    }
    user.value = data.user ?? null
    capabilities.value = data.capabilities ?? []
  }

  async function request<T>(path: string, init: RequestInit = {}): Promise<T | undefined> {
    if (!accessToken.value && refreshToken.value) {
      await refreshAccessToken()
    }
    if (!accessToken.value) {
      throw new ApiError('请先登录', 401, 'unauthorized')
    }
    return requestWithRetry<T>(path, init)
  }

  async function requestWithRetry<T>(path: string, init: RequestInit = {}): Promise<T | undefined> {
    const res = await rawFetch(path, {
      ...init,
      headers: {
        ...(init.headers || {}),
        'Authorization': `Bearer ${accessToken.value}`
      }
    })

    if (res.status === 401 && refreshToken.value) {
      const refreshed = await refreshAccessToken()
      if (refreshed) {
        const retry = await rawFetch(path, {
          ...init,
          headers: {
            ...(init.headers || {}),
            'Authorization': `Bearer ${accessToken.value}`
          }
        })
        return parseApiResponse<T>(retry)
      }
    }

    return parseApiResponse<T>(res)
  }

  function clearLocal() {
    accessToken.value = ''
    refreshToken.value = ''
    expiresAt.value = 0
    user.value = null
    capabilities.value = []
    clearSessionStorage()
  }

  function logout() {
    clearLocal()
    const url = new URL(`${API_BASE}/connect/logout`, window.location.origin)
    url.searchParams.set('post_logout_redirect_uri', ADMIN_REDIRECT_URI)
    window.location.assign(url.toString())
  }

  async function init() {
    const query = new URLSearchParams(window.location.search)
    const code = query.get('code')
    const state = query.get('state')
    const oauthError = query.get('error')

    try {
      if (oauthError) {
        loginError.value = oauthError === 'access_denied' ? '授权已取消' : '授权失败'
      } else if (code) {
        if (state) {
          await handleCallback(code, state)
        } else {
          loginError.value = '登录回调缺少 state，已拒绝'
        }
      } else {
        const session = readSession()
        if (session) {
          accessToken.value = session.accessToken
          refreshToken.value = session.refreshToken
          expiresAt.value = session.expiresAt

          if (!accessToken.value || expiresAt.value - Date.now() < 30000) {
            await refreshAccessToken()
          }
          if (accessToken.value) {
            await loadCapabilities()
          }
        }
      }

      if (oauthError || code) {
        const clean = new URL(window.location.href)
        clean.search = ''
        window.history.replaceState({}, '', clean.toString())
      }
    } catch (err) {
      loginError.value = err instanceof Error ? err.message : '初始化登录状态失败'
      clearLocal()
    } finally {
      initialized.value = true
    }
  }

  return {
    initialized,
    starting,
    loginError,
    isAuthenticated,
    user,
    capabilities,
    firstCapability,
    displayName,
    group,
    hasCapability,
    capability,
    startLogin,
    init,
    request,
    refreshAccessToken,
    logout
  }
})
