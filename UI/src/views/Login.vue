<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NButton, NInput, NAlert, NIcon, NPopconfirm, NSpin, NDivider } from 'naive-ui'
import { Account } from '@vicons/carbon'
import { apiFetch, useAuthStore } from '@/stores/auth'
import { api, ApiError } from '@/utils/api'
import { SUPPORT_EMAIL, type ScopeInfo } from '@/types/api'
import { getAssertion, createCredential } from '@/utils/webauthn'
import Dock from '@/components/Dock.vue'

interface AuthorizedApp {
  id: string
  clientId: string
  displayName: string
  description?: string | null
  logoUrl?: string | null
  authorizedAt: string
  scopes: ScopeInfo[]
}

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()
const returnUrl = ref('')


function isSafeReturnUrl(url: string): boolean {
  if (url.startsWith('//')) return false
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url)) return false
  return url.startsWith('/')
}

onMounted(() => {
  const ru = route.query.return_url
  if (typeof ru === 'string' && ru && isSafeReturnUrl(ru)) {
    returnUrl.value = ru
  }
  if (typeof route.query.error === 'string') {
    if (route.query.error === 'external_login_requires_account') {
      externalLoginError.value = '该第三方账号未绑定任何 Pylaios 账户，请先使用本地账户登录并绑定。'
    } else if (route.query.error === 'external_failed') {
      externalLoginError.value = '第三方登录失败，请重试。'
    }
  }
  loadExternalProviders()
})

const externalProviders = ref<string[]>([])
const externalLoginError = ref('')

async function loadExternalProviders() {
  try {
    const data = await api('/api/auth/external-login/providers')
    externalProviders.value = (data?.providers as string[]) || []
  } catch {

  }
}


async function startExternalLogin(provider: string) {
  externalLoginError.value = ''
  try {
    const res = await apiFetch('/api/auth/external-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
      redirect: 'manual'
    })
    const location = res.headers.get('location')
    if (location) {
      window.location.href = location
      return
    }
    const data = await res.json().catch(() => null)
    externalLoginError.value = data?.error || '外部登录不可用'
  } catch {
    externalLoginError.value = '网络错误，请重试'
  }
}

const PROVIDER_NAMES: Record<string, string> = {
  github: 'GitHub',
  facebook: 'Facebook',
  microsoft: 'Microsoft'
}

const usernameOrEmail = ref('')
const password = ref('')
const loading = ref(false)
const loginError = ref('')
const rememberMe = ref(true)
const lockedOut = ref(false)
const loginBanId = ref('')
const loginErrorState = ref<'none' | 'locked_out' | 'ip_banned' | 'server_error' | 'network_error'>('none')
const mfaTransactionId = ref('')
const mfaMethods = ref<string[]>([])
const mfaCode = ref('')
const mfaEnrollmentId = ref('')
const mfaSecret = ref('')
const mfaOtpauthUri = ref('')
const mfaError = ref('')
const mfaSetup = ref(false)

const showAppsPanel = ref(false)
const showThirdPartyPanel = ref(false)
const authorizedApps = ref<AuthorizedApp[]>([])
const appsLoading = ref(false)
const appsError = ref('')
const logoFailedSet = ref(new Set<string>())
const expandedScopes = ref(new Set<string>())

function toggleRememberMe() {
  rememberMe.value = !rememberMe.value
}

function handlePasswordKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    handleLogin()
  }
}

function enterManageApps() {
  showAppsPanel.value = true
  loadAuthorizedApps()
}

function leaveManageApps() {
  showAppsPanel.value = false
  appsError.value = ''
}

function enterThirdParty() {
  showThirdPartyPanel.value = true
  loadThirdPartyLogins()
}

function leaveThirdParty() {
  showThirdPartyPanel.value = false
  thirdPartyError.value = ''
}

interface ThirdPartyLogin {
  provider: string
  displayName: string
  boundAt: string
}

const thirdPartyLogins = ref<ThirdPartyLogin[]>([])
const thirdPartyLoading = ref(false)
const thirdPartyError = ref('')

async function loadThirdPartyLogins() {
  thirdPartyLoading.value = true
  thirdPartyError.value = ''
  try {
    const data = await api('/api/auth/account/external-logins')
    thirdPartyLogins.value = (data.logins as ThirdPartyLogin[]) || []
  } catch (err: any) {
    thirdPartyError.value = err?.message || '加载失败，请重试'
  } finally {
    thirdPartyLoading.value = false
  }
}

function onLogoError(id: string) {
  logoFailedSet.value.add(id)
}

function toggleExpanded(id: string) {
  const set = expandedScopes.value
  if (set.has(id)) {
    set.delete(id)
  } else {
    set.add(id)
  }
}

function scopeNames(app: AuthorizedApp) {
  if (app.scopes.length === 0) return '无'
  return app.scopes.map(s => s.displayName).join(' · ')
}

async function loadAuthorizedApps() {
  appsLoading.value = true
  appsError.value = ''
  authorizedApps.value = []
  logoFailedSet.value = new Set()
  expandedScopes.value = new Set()

  try {
    const data = await api('/api/auth/account/authorized-apps')
    if (!data.success) {
      throw new Error(data.error || '加载失败')
    }
    authorizedApps.value = (data.apps as AuthorizedApp[]) || []
  } catch (err: any) {
    appsError.value = err?.message || '加载失败，请重试'
  } finally {
    appsLoading.value = false
  }
}

async function revokeApp(id: string) {
  try {
    await api(`/api/auth/account/authorized-apps/${encodeURIComponent(id)}`, {
      method: 'DELETE'
    })
    await loadAuthorizedApps()
  } catch (err: any) {
    appsError.value = err?.message || '撤销失败，请重试'
  }
}

async function handleLogin() {
  if (loading.value) return
  loading.value = true
  loginError.value = ''
  loginErrorState.value = 'none'
  loginBanId.value = ''

  try {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        usernameOrEmail: usernameOrEmail.value,
        password: password.value,
        rememberMe: rememberMe.value
      })
    })

    if (data.success) {
      finishLogin(data)
    } else {
      loginError.value = data.error || '登录失败，请重试'
    }
  } catch (e) {
    if (e instanceof ApiError && e.status >= 500) {
      loginErrorState.value = 'server_error'
      loginError.value = e.data?.error || '登录服务暂时不可用'
    } else if (e instanceof ApiError && e.errorCode === 'locked_out') {
      lockedOut.value = true
      loginErrorState.value = 'locked_out'
      let msg = e.message || ''
      if (e.data?.lockoutRemaining) {
        msg += ` ${e.data.lockoutRemaining}`
      }
      loginError.value = msg
    } else if (e instanceof ApiError && e.errorCode === 'ip_banned') {
      lockedOut.value = true
      loginErrorState.value = 'ip_banned'
      loginBanId.value = (e.data?.banId as string) || ''
      loginError.value = e.message || ''
    } else if (e instanceof ApiError && (e.errorCode === 'mfa_required' || e.errorCode === 'mfa_setup_required')) {
      mfaTransactionId.value = String(e.data?.mfaTransactionId || '')
      mfaMethods.value = (e.data?.mfaMethods as string[]) || []
      mfaSetup.value = e.errorCode === 'mfa_setup_required'
      mfaError.value = ''
      if (mfaSetup.value && mfaMethods.value.includes('totp')) await beginTotpEnrollment()
    } else if (e instanceof ApiError) {
      loginError.value = e.message || '登录失败，请重试'
    } else {
      loginErrorState.value = 'network_error'
      loginError.value = '网络错误，请重试'
    }
  } finally {
    loading.value = false
  }
}

function finishLogin(data: any) {
  authStore.login({
    uid: data.uid as string,
    name: data.name as string,
    displayName: data.displayName as string,
    group: data.group as string,
    email: data.email as string
  }, rememberMe.value)
  lockedOut.value = false
  if (returnUrl.value) window.location.href = returnUrl.value
  else router.push('/')
}

async function beginTotpEnrollment() {
  try {
    const data = await api('/api/auth/mfa/totp/enroll', {
      method: 'POST',
      body: JSON.stringify({ transactionId: mfaTransactionId.value })
    })
    mfaEnrollmentId.value = String(data.enrollmentId)
    mfaSecret.value = String(data.secret)
    mfaOtpauthUri.value = String(data.otpauthUri)
  } catch (e) {
    mfaError.value = e instanceof Error ? e.message : '无法开始 MFA 设置'
  }
}

async function verifyMfa() {
  if (!mfaCode.value || !mfaTransactionId.value) return
  mfaError.value = ''
  loading.value = true
  try {
    const data = await api('/api/auth/mfa/verify', {
      method: 'POST',
      body: JSON.stringify({ transactionId: mfaTransactionId.value, code: mfaCode.value })
    })
    finishLogin(data)
  } catch (e) {
    mfaError.value = e instanceof ApiError ? e.message : 'MFA 验证失败，请重试'
  } finally {
    loading.value = false
  }
}

async function confirmTotpSetup() {
  if (!mfaEnrollmentId.value || !mfaCode.value) return
  mfaError.value = ''
  loading.value = true
  try {
    const data = await api('/api/auth/mfa/totp/confirm', {
      method: 'POST',
      body: JSON.stringify({ enrollmentId: mfaEnrollmentId.value, code: mfaCode.value })
    })
    finishLogin(data)
  } catch (e) {
    mfaError.value = e instanceof ApiError ? e.message : 'MFA 设置失败，请重试'
  } finally {
    loading.value = false
  }
}

async function verifyWebAuthn() {
  mfaError.value = ''
  loading.value = true
  try {
    const options = await api(`/api/auth/mfa/webauthn/assertion-options?transactionId=${encodeURIComponent(mfaTransactionId.value)}`)
    const response = await getAssertion(options)
    const data = await api('/api/auth/mfa/webauthn/verify', {
      method: 'POST',
      body: JSON.stringify({ transactionId: mfaTransactionId.value, response })
    })
    finishLogin(data)
  } catch (e) {
    mfaError.value = e instanceof Error ? e.message : 'Passkey 验证失败，请重试'
  } finally {
    loading.value = false
  }
}

async function setupWebAuthn() {
  mfaError.value = ''
  loading.value = true
  try {
    const data = await api('/api/auth/mfa/webauthn/registration-options', {
      method: 'POST',
      body: JSON.stringify({ transactionId: mfaTransactionId.value })
    })
    const response = await createCredential(data.options)
    await api('/api/auth/mfa/webauthn/registration', {
      method: 'POST',
      body: JSON.stringify({ transactionId: mfaTransactionId.value, registrationId: data.registrationId, response })
    })
    await verifyWebAuthn()
  } catch (e) {
    mfaError.value = e instanceof Error ? e.message : 'Passkey 设置失败，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page-shell">
    <div class="page-wrapper">
      <div class="page-card">
        <div class="login-content" :class="{ 'manage-content': showAppsPanel || showThirdPartyPanel }">
        <template v-if="!authStore.isAuthenticated">
          <h1 class="login-title">Pylai!</h1>
          <p class="login-subtitle">登录</p>

          <p v-if="loginError && loginErrorState === 'network_error'" class="error-msg">{{ loginError }}</p>

          <template v-if="mfaTransactionId">
            <NAlert type="warning" :show-icon="true" :bordered="false" style="width: 100%; max-width: 420px; text-align: left;">
              <template #header>{{ mfaSetup ? '高权限账户需要设置 MFA' : '需要完成 MFA 验证' }}</template>
              <p v-if="mfaSetup" style="margin: 4px 0;">请完成第二因素设置后继续登录。</p>
              <p v-else style="margin: 4px 0;">密码验证已完成，请继续验证第二因素。</p>
            </NAlert>
            <template v-if="mfaSetup">
              <div v-if="mfaSecret" class="mfa-box">
                <p>使用认证器添加此密钥：</p>
                <code>{{ mfaSecret }}</code>
                <small>{{ mfaOtpauthUri }}</small>
                <NInput v-model:value="mfaCode" maxlength="6" placeholder="认证器验证码" />
                <NButton type="success" :loading="loading" :disabled="mfaCode.length !== 6" @click="confirmTotpSetup">确认 TOTP</NButton>
              </div>
              <NButton v-if="mfaMethods.includes('webauthn')" type="success" dashed :loading="loading" @click="setupWebAuthn">设置 Passkey</NButton>
            </template>
            <template v-else>
              <NInput v-if="mfaMethods.includes('totp')" v-model:value="mfaCode" maxlength="6" placeholder="认证器验证码" />
              <NButton v-if="mfaMethods.includes('totp')" type="success" :loading="loading" :disabled="mfaCode.length !== 6" @click="verifyMfa">验证 TOTP</NButton>
              <NButton v-if="mfaMethods.includes('webauthn')" type="success" dashed :loading="loading" @click="verifyWebAuthn">使用 Passkey</NButton>
            </template>
            <p v-if="mfaError" class="error-msg">{{ mfaError }}</p>
            <NButton quaternary :disabled="loading" @click="mfaTransactionId = ''; mfaCode = ''; mfaError = ''">返回登录</NButton>
          </template>

          <template v-else>

          <NAlert
            v-if="loginError && loginErrorState === 'none'"
            type="warning"
            :show-icon="true"
            :bordered="false"
            style="width: 100%; max-width: 420px; text-align: left;"
          >
            <template #header>
              <span style="font-weight: 600;">{{ loginError }}</span>
            </template>
          </NAlert>

          <form
            class="login-form"
            autocomplete="on"
            @submit.prevent="handleLogin"
          >
            <NInput
              v-model:value="usernameOrEmail"
              type="text"
              size="large"
              placeholder="用户名 / 邮箱"
              class="underline-input"
              :disabled="lockedOut"
              :input-props="{
                name: 'username',
                autocomplete: 'off',
                onKeydown: handlePasswordKeydown
              }"
            />

            <NInput
              v-model:value="password"
              type="password"
              size="large"
              placeholder="密码"
              class="underline-input"
              :disabled="lockedOut"
              :input-props="{
                name: 'password',
                autocomplete: 'current-password',
                onKeydown: handlePasswordKeydown
              }"
            />

            <NButton
              v-if="!rememberMe"
              attr-type="button"
              dashed
              :disabled="lockedOut"
              @click="toggleRememberMe"
            >
              *不保存*登录凭据
            </NButton>
            <NButton
              v-else
              attr-type="button"
              type="success"
              dashed
              :disabled="lockedOut"
              @click="toggleRememberMe"
            >
              *保存*登录凭据
            </NButton>

            <NButton
              v-if="usernameOrEmail && password && !loading && !lockedOut"
              attr-type="submit"
              type="success"
              size="large"
              circle
              class="submit-btn"
            >
              ->
            </NButton>
            <NButton
              v-else-if="loading"
              attr-type="submit"
              type="success"
              size="large"
              circle
              class="submit-btn"
              loading
            />
          </form>

          <NButton
            v-if="!loading && !lockedOut"
            quaternary
            type="success"
            size="small"
            @click="$router.push('/ForgetPassword')"
          >
            忘记密码？
          </NButton>

          <template v-if="externalProviders.length > 0">
            <NDivider style="margin: 8px 0;">或使用第三方账号登录</NDivider>
            <div class="external-row">
              <NButton
                v-for="p in externalProviders"
                :key="p"
                quaternary
                dashed
                :disabled="loading || lockedOut"
                @click="startExternalLogin(p)"
              >
                {{ PROVIDER_NAMES[p] || p }}
              </NButton>
            </div>
            <p v-if="externalLoginError" class="error-msg">{{ externalLoginError }}</p>
          </template>

          <template v-if="loginErrorState === 'ip_banned' || loginErrorState === 'server_error' || loginErrorState === 'locked_out'">
            <NAlert
              :type="loginErrorState === 'locked_out' ? 'warning' : 'error'"
              :show-icon="true"
              :bordered="false"
              style="width: 100%; max-width: 420px; text-align: left;"
            >
              <template #header>
                <span style="font-weight: 600;">
                  {{ loginErrorState === 'ip_banned' ? '登录暂时受限' : loginErrorState === 'locked_out' ? '账号已被锁定' : '登录服务故障' }}
                </span>
              </template>
              <template v-if="loginErrorState === 'ip_banned'">
                <p style="margin: 4px 0;">关闭此页面，更换网络环境以重试。</p>
                <p style="margin: 4px 0;">如有疑问，请将编码</p>
                <code style="display: inline-block; margin: 4px 0; font-family: inherit; background: transparent; word-break: break-all;">{{ loginBanId }}</code>
                <p style="margin: 4px 0;">发送至 {{ SUPPORT_EMAIL || '站点管理员' }} 以获得支持。</p>
              </template>
              <template v-else-if="loginErrorState === 'locked_out'">
                <p style="margin: 4px 0;">账号因多次登录失败已被临时锁定。</p>
                <p style="margin: 4px 0;">{{ loginError }}</p>
                <p style="margin: 4px 0;">请等待锁定解除后再试。</p>
              </template>
              <template v-else>
                <p style="margin: 4px 0;">由于登录服务故障，暂时无法完成登录。</p>
                <p style="margin: 4px 0;">此错误由服务端引起，请等待修复。</p>
                <p style="margin: 4px 0;">请将此页面错误信息发送至 {{ SUPPORT_EMAIL || '站点管理员' }} 以获得支持。</p>
              </template>
            </NAlert>
          </template>
          </template>
        </template>

        <template v-else>
          <template v-if="!showAppsPanel && !showThirdPartyPanel">
            <div class="login-title">
              <NIcon class="login-title-icon" :component="Account" />
              <span>&lt; Pylai &gt;</span>
            </div>
            <p class="login-subtitle" style="color: var(--text-tertiary);">管理 Pylai 通行证</p>

            <NButton
              type="success"
              dashed
              @click="enterManageApps"
            >
              管理已授权应用
            </NButton>

            <NButton type="success" dashed @click="enterThirdParty">
              第三方登录方式
            </NButton>

            <NButton
              type="success"
              dashed
              @click="$router.push('/login/ResetPassword')"
            >
              修改登录密码
            </NButton>

            <NButton quaternary @click="authStore.logout()">
              退出登录
            </NButton>

            <NButton
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="$router.push('/')"
            >
              ->
            </NButton>
          </template>

          <template v-else-if="showAppsPanel">
            <div class="manage-header">
              <NButton quaternary size="small" @click="leaveManageApps">
                &lt;- 返回
              </NButton>
              <span class="manage-title">管理已授权应用</span>
            </div>

            <div class="manage-list">
              <div v-if="appsLoading" class="apps-loading">
                <NSpin />
              </div>
              <NAlert
                v-else-if="appsError"
                type="error"
                :show-icon="true"
                :bordered="false"
                style="width: 100%; text-align: left;"
              >
                <template #header>
                  <span style="font-weight: 600;">加载失败</span>
                </template>
                <p style="margin: 4px 0;">{{ appsError }}</p>
              </NAlert>
              <div v-else-if="authorizedApps.length === 0" class="apps-empty">
                暂无已授权应用
              </div>
              <div v-else class="apps-scroll">
                <div
                  v-for="app in authorizedApps"
                  :key="app.id"
                  class="app-card"
                >
                  <div class="app-row">
                    <span class="app-label">应用</span>
                    <img
                      v-if="app.logoUrl && !logoFailedSet.has(app.id)"
                      :src="app.logoUrl"
                      alt=""
                      class="app-logo"
                      @error="onLogoError(app.id)"
                    />
                    <span class="app-name" :title="app.displayName">{{ app.displayName }}</span>
                    <NPopconfirm
                      positive-text="确定"
                      negative-text="取消"
                      @positive-click="revokeApp(app.id)"
                    >
                      <template #trigger>
                        <NButton type="error" dashed size="small">
                          撤销授权
                        </NButton>
                      </template>
                      <template #default>
                        <span style="white-space: nowrap;">此操作无法撤销，确定吗？</span>
                      </template>
                    </NPopconfirm>
                  </div>
                  <div class="app-time">{{ app.authorizedAt }}</div>
                  <div class="app-desc">
                    {{ app.description || '暂无应用描述' }}
                  </div>
                  <div
                    class="app-scopes"
                    :class="{ expanded: expandedScopes.has(app.id) }"
                    @click="toggleExpanded(app.id)"
                  >
                    <span class="scope-label">授权：</span>
                    <span class="scope-line">{{ scopeNames(app) }}</span>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="showThirdPartyPanel">
            <div class="manage-header">
              <NButton quaternary size="small" @click="leaveThirdParty">
                &lt;- 返回
              </NButton>
              <span class="manage-title">第三方登录方式</span>
            </div>
            <div class="manage-list">
              <div v-if="thirdPartyLoading" class="apps-loading">
                <NSpin />
              </div>
              <p v-else-if="thirdPartyError" class="error-msg">{{ thirdPartyError }}</p>
              <template v-else-if="thirdPartyLogins.length > 0">
                <div v-for="l in thirdPartyLogins" :key="l.provider" class="app-item">
                  <div class="app-info">
                    <div class="app-name">{{ l.displayName }}</div>
                    <div class="app-desc">绑定于 {{ l.boundAt }}</div>
                  </div>
                </div>
              </template>
              <div v-else class="apps-empty">暂无第三方登录方式</div>
            </div>
          </template>
        </template>
      </div>
    </div>
    <Dock />
  </div>
</div>
</template>


<style scoped>
.mfa-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  max-width: 420px;
  padding: 14px;
  border: 1px solid var(--input-border);
  border-radius: 12px;
  text-align: left;
}

.mfa-box code {
  overflow-wrap: anywhere;
  font-size: 15px;
}

.mfa-box small {
  overflow-wrap: anywhere;
  color: var(--text-tertiary);
}




.login-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 32px;
  text-align: center;
}

.login-title {
  margin: 0;
  font-weight: 600;
  font-size: 32px;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.login-title-icon {
  font-size: 32px;
  color: var(--text-primary);
}

.login-subtitle {
  margin: 0;
  font-size: 16px;
  color: var(--text-secondary);
}

.manage-content {
  align-items: stretch;
  text-align: left;
  gap: 16px;
}

.manage-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.manage-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.manage-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.apps-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
}

.apps-empty {
  text-align: center;
  font-size: 14px;
  color: var(--text-tertiary);
  padding: 32px 0;
}

.apps-scroll {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-right: 4px;
}

.app-card {
  border: 1px dashed var(--success-color);
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: transparent;
}

.app-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  font-size: 13px;
  line-height: 1.5;
}

.app-label {
  flex-shrink: 0;
  font-size: 13px;
  color: var(--text-tertiary);
}

.app-logo {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border-radius: 4px;
  object-fit: contain;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
}

.app-name {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  color: var(--text-primary);
}

.app-time {
  font-size: 12px;
  color: var(--text-tertiary);
}

.app-desc {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-secondary);
  word-break: break-word;
}

.app-scopes {
  display: flex;
  align-items: baseline;
  gap: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  cursor: pointer;
  min-width: 0;
}

.app-scopes .scope-label {
  flex-shrink: 0;
  color: var(--text-tertiary);
}

.app-scopes .scope-line {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.app-scopes.expanded .scope-line,
.app-scopes:hover .scope-line {
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
}

.login-form {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.external-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  width: 100%;
}

</style>
