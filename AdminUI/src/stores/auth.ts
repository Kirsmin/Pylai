import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { API_BASE, ApiError, parseApiResponse, rawFetch } from '@/utils/http'
import { getAssertion } from '@/utils/webauthn'
import type { AdminCapability, AdminCapabilitiesResponse, AdminCapabilityUser } from '@/types/admin'

interface StepUpTicket {
  transactionId: string
  methods: string[]
}

export const useAuthStore = defineStore('admin-auth', () => {
  const initialized = ref(false)
  const starting = ref(false)
  const user = ref<AdminCapabilityUser | null>(null)
  const capabilities = ref<AdminCapability[]>([])
  const loginError = ref('')
  const csrfToken = ref('')

  const stepUpVisible = ref(false)
  const stepUpTicket = ref<StepUpTicket | null>(null)
  const stepUpCode = ref('')
  const stepUpError = ref('')
  const stepUpBusy = ref(false)
  let stepUpPromise: Promise<void> | null = null
  let stepUpResolve: (() => void) | null = null
  let stepUpReject: ((reason?: unknown) => void) | null = null

  const mfaTotpEnabled = ref(false)
  const mfaWebAuthnCount = ref(0)
  const mfaStepUpSatisfied = ref(false)

  const isAuthenticated = computed(() => user.value !== null)
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
    const url = new URL(`${API_BASE}/api/admin/bff/login`, window.location.origin)
    url.searchParams.set('returnUrl', '/admin/')
    window.location.assign(url.toString())
  }

  async function loadCapabilities(): Promise<boolean> {
    const response = await rawFetch('/api/admin/capabilities')
    if (response.status === 401) {
      user.value = null
      capabilities.value = []
      return false
    }
    const data = await parseApiResponse<AdminCapabilitiesResponse>(response)
    if (!data) throw new Error('无法获取管理能力')
    user.value = data.user ?? null
    capabilities.value = data.capabilities ?? []
    return user.value !== null
  }

  async function ensureCsrf() {
    if (csrfToken.value) return csrfToken.value
    try {
      const data = await parseApiResponse<{ token: string }>(await rawFetch('/api/admin/bff/csrf'))
      if (!data?.token) throw new ApiError('无法建立管理会话', 403, 'csrf_invalid')
      csrfToken.value = data.token
      return csrfToken.value
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        user.value = null
        capabilities.value = []
        throw new ApiError('登录已过期，请重新登录', 401, 'unauthorized')
      }
      throw err
    }
  }

  async function executeOnce<T>(path: string, init: RequestInit = {}): Promise<T | undefined> {
    const method = (init.method || 'GET').toUpperCase()
    const headers = new Headers(init.headers)
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method))
      headers.set('X-CSRF-Token', await ensureCsrf())

    const response = await rawFetch(path, { ...init, headers })
    if (response.status === 401) {
      user.value = null
      capabilities.value = []
    }
    return parseApiResponse<T>(response)
  }

  async function request<T>(path: string, init: RequestInit = {}): Promise<T | undefined> {
    try {
      return await executeOnce<T>(path, init)
    } catch (err) {
      if (err instanceof ApiError && err.errorCode === 'mfa_step_up_required') {
        await requestMfaStepUp()
        return executeOnce<T>(path, init)
      }
      throw err
    }
  }

  async function requestMfaStepUp(): Promise<void> {
    if (stepUpPromise) return stepUpPromise

    stepUpPromise = new Promise<void>((resolve, reject) => {
      stepUpResolve = resolve
      stepUpReject = reject
      void beginMfaStepUp()
    }).finally(() => {
      stepUpPromise = null
      stepUpResolve = null
      stepUpReject = null
      stepUpVisible.value = false
      stepUpTicket.value = null
      stepUpCode.value = ''
      stepUpError.value = ''
    })
    return stepUpPromise
  }

  async function beginMfaStepUp() {
    stepUpBusy.value = true
    stepUpError.value = ''
    try {
      const data = await parseApiResponse<{ transactionId: string; methods: string[] }>(
        await rawFetch('/api/auth/mfa/step-up', { method: 'POST' })
      )
      if (!data?.transactionId) throw new ApiError('无法开始 MFA 验证', 403, 'mfa_invalid')
      stepUpTicket.value = { transactionId: data.transactionId, methods: data.methods || [] }
      stepUpVisible.value = true
    } catch (err) {
      stepUpError.value = err instanceof Error ? err.message : '无法开始 MFA 验证'
      stepUpReject?.(err)
    } finally {
      stepUpBusy.value = false
    }
  }

  async function verifyStepUpTotp() {
    const ticket = stepUpTicket.value
    if (!ticket || stepUpCode.value.length !== 6) return
    stepUpBusy.value = true
    stepUpError.value = ''
    try {
      await parseApiResponse<Record<string, never>>(await rawFetch('/api/auth/mfa/step-up/totp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transactionId: ticket.transactionId, code: stepUpCode.value })
      }))
      mfaStepUpSatisfied.value = true
      stepUpResolve?.()
    } catch (err) {
      stepUpError.value = err instanceof Error ? err.message : 'MFA 验证失败，请重试'
    } finally {
      stepUpBusy.value = false
    }
  }

  async function verifyStepUpWebAuthn() {
    const ticket = stepUpTicket.value
    if (!ticket) return
    stepUpBusy.value = true
    stepUpError.value = ''
    try {
      const options = await parseApiResponse<any>(await rawFetch(
        `/api/auth/mfa/step-up/webauthn/options?transactionId=${encodeURIComponent(ticket.transactionId)}`
      ))
      const response = await getAssertion(options)
      await parseApiResponse<Record<string, never>>(await rawFetch('/api/auth/mfa/step-up/webauthn/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transactionId: ticket.transactionId, response })
      }))
      mfaStepUpSatisfied.value = true
      stepUpResolve?.()
    } catch (err) {
      stepUpError.value = err instanceof Error ? err.message : '通行密钥验证失败，请重试'
    } finally {
      stepUpBusy.value = false
    }
  }

  function cancelMfaStepUp() {
    stepUpReject?.(new ApiError('操作已取消', 403, 'mfa_step_up_cancelled'))
  }

  async function loadMfaStatus() {
    try {
      const data = await parseApiResponse<{
        required: boolean
        totpEnabled: boolean
        webAuthnCount: number
        stepUpSatisfied: boolean
      }>(await rawFetch('/api/auth/mfa/status'))
      if (!data) return
      mfaTotpEnabled.value = data.totpEnabled
      mfaWebAuthnCount.value = data.webAuthnCount
      mfaStepUpSatisfied.value = data.stepUpSatisfied
    } catch {
      mfaTotpEnabled.value = false
      mfaWebAuthnCount.value = 0
      mfaStepUpSatisfied.value = false
    }
  }

  async function logout() {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', credentials: 'include' })
    } catch {
    }
    user.value = null
    capabilities.value = []
    csrfToken.value = ''
    stepUpTicket.value = null
    stepUpVisible.value = false
    window.location.assign(`${API_BASE}/admin/`)
  }

  async function init() {
    const query = new URLSearchParams(window.location.search)
    const oauthError = query.get('error')
    if (oauthError) loginError.value = oauthError === 'access_denied' ? '登录已取消' : '登录失败'

    try {
      if (!oauthError) {
        await loadCapabilities()
        if (user.value) await loadMfaStatus()
      }
      const clean = new URL(window.location.href)
      if (oauthError) {
        clean.search = ''
        window.history.replaceState({}, '', clean.toString())
      }
    } catch (err) {
      loginError.value = err instanceof Error ? err.message : '初始化登录状态失败'
      user.value = null
      capabilities.value = []
    } finally {
      initialized.value = true
      starting.value = false
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
    request,
    logout,
    init,
    stepUpVisible,
    stepUpTicket,
    stepUpCode,
    stepUpError,
    stepUpBusy,
    verifyStepUpTotp,
    verifyStepUpWebAuthn,
    cancelMfaStepUp,
    mfaTotpEnabled,
    mfaWebAuthnCount,
    mfaStepUpSatisfied,
    loadMfaStatus
  }
})
