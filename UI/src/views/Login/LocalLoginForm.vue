<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NInput } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import { api, ApiError } from '@/utils/api'
import { getAssertion, createCredential } from '@/utils/webauthn'
import { loadPublicConfig } from '@/utils/publicConfig'

const props = defineProps<{ returnUrl?: string }>()
const router = useRouter()
const authStore = useAuthStore()
const usernameOrEmail = ref('')
const password = ref('')
const rememberMe = ref(true)
const loading = ref(false)
const lockedOut = ref(false)
const loginError = ref('')
const loginBanId = ref('')
const supportEmail = ref('')
const loginErrorState = ref<'none' | 'locked_out' | 'ip_banned' | 'server_error' | 'network_error'>('none')

const mfaTransactionId = ref('')
const mfaMethods = ref<string[]>([])
const mfaCode = ref('')
const mfaEnrollmentId = ref('')
const mfaSecret = ref('')
const mfaOtpauthUri = ref('')
const mfaError = ref('')
const mfaSetup = ref(false)

onMounted(async () => {
  try { supportEmail.value = (await loadPublicConfig()).supportEmail } catch { /* support text has a safe fallback */ }
  const params = new URLSearchParams(window.location.search)
  if (params.get('error') === 'mfa_required' && params.get('mfa_transaction')) {
    mfaTransactionId.value = String(params.get('mfa_transaction') || '')
    mfaMethods.value = (params.get('mfa_methods') || '').split(',').filter(Boolean)
  }
})

async function handleLogin() {
  if (loading.value || lockedOut.value) return
  loading.value = true
  loginError.value = ''
  loginErrorState.value = 'none'
  loginBanId.value = ''
  try {
    const data = await api<Record<string, unknown>>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ usernameOrEmail: usernameOrEmail.value, password: password.value, rememberMe: rememberMe.value })
    })
    finishLogin(data)
  } catch (e) {
    if (e instanceof ApiError && e.status >= 500) {
      loginErrorState.value = 'server_error'; loginError.value = e.message || '登录服务暂时不可用'
    } else if (e instanceof ApiError && e.errorCode === 'locked_out') {
      lockedOut.value = true; loginErrorState.value = 'locked_out'
      loginError.value = `${e.message || ''}${e.data?.lockoutRemaining ? ` ${e.data.lockoutRemaining}` : ''}`
    } else if (e instanceof ApiError && e.errorCode === 'ip_banned') {
      lockedOut.value = true; loginErrorState.value = 'ip_banned'; loginBanId.value = String(e.data?.banId || ''); loginError.value = e.message
    } else if (e instanceof ApiError && (e.errorCode === 'mfa_required' || e.errorCode === 'mfa_setup_required')) {
      mfaTransactionId.value = String(e.data?.mfaTransactionId || '')
      mfaMethods.value = (e.data?.mfaMethods as string[]) || []
      mfaSetup.value = e.errorCode === 'mfa_setup_required'
      if (mfaSetup.value && mfaMethods.value.includes('totp')) await beginTotpEnrollment()
    } else if (e instanceof ApiError) {
      loginError.value = e.message || '登录失败，请重试'
    } else {
      loginErrorState.value = 'network_error'; loginError.value = '网络错误，请重试'
    }
  } finally { loading.value = false }
}

function finishLogin(data: Record<string, unknown>) {
  authStore.login({
    uid: String(data.uid || ''), name: String(data.name || ''), displayName: String(data.displayName || data.name || ''),
    group: String(data.group || ''), email: String(data.email || '')
  }, rememberMe.value)
  window.location.assign(props.returnUrl || '/')
}

async function beginTotpEnrollment() {
  try {
    const data = await api<Record<string, unknown>>('/api/auth/mfa/totp/enroll', { method: 'POST', body: JSON.stringify({ transactionId: mfaTransactionId.value }) })
    mfaEnrollmentId.value = String(data.enrollmentId || '')
    mfaSecret.value = String(data.secret || '')
    mfaOtpauthUri.value = String(data.otpauthUri || '')
  } catch (e) { mfaError.value = e instanceof Error ? e.message : '无法开始 MFA 设置' }
}

async function verifyMfa() {
  if (!mfaCode.value || !mfaTransactionId.value) return
  loading.value = true; mfaError.value = ''
  try {
    const data = await api<Record<string, unknown>>('/api/auth/mfa/verify', { method: 'POST', body: JSON.stringify({ transactionId: mfaTransactionId.value, code: mfaCode.value }) })
    finishLogin(data)
  } catch (e) { mfaError.value = e instanceof ApiError ? e.message : 'MFA 验证失败，请重试' }
  finally { loading.value = false }
}

async function confirmTotpSetup() {
  if (!mfaEnrollmentId.value || !mfaCode.value) return
  loading.value = true; mfaError.value = ''
  try {
    const data = await api<Record<string, unknown>>('/api/auth/mfa/totp/confirm', { method: 'POST', body: JSON.stringify({ enrollmentId: mfaEnrollmentId.value, code: mfaCode.value }) })
    finishLogin(data)
  } catch (e) { mfaError.value = e instanceof ApiError ? e.message : 'MFA 设置失败，请重试' }
  finally { loading.value = false }
}

async function verifyWebAuthn() {
  loading.value = true; mfaError.value = ''
  try {
    const options = await api<Record<string, unknown>>(`/api/auth/mfa/webauthn/assertion-options?transactionId=${encodeURIComponent(mfaTransactionId.value)}`)
    const response = await getAssertion(options)
    const data = await api<Record<string, unknown>>('/api/auth/mfa/webauthn/verify', { method: 'POST', body: JSON.stringify({ transactionId: mfaTransactionId.value, response }) })
    finishLogin(data)
  } catch (e) { mfaError.value = e instanceof Error ? e.message : 'Passkey 验证失败，请重试' }
  finally { loading.value = false }
}

async function setupWebAuthn() {
  loading.value = true; mfaError.value = ''
  try {
    const data = await api<Record<string, any>>('/api/auth/mfa/webauthn/registration-options', { method: 'POST', body: JSON.stringify({ transactionId: mfaTransactionId.value }) })
    const response = await createCredential(data.options)
    await api('/api/auth/mfa/webauthn/registration', { method: 'POST', body: JSON.stringify({ transactionId: mfaTransactionId.value, registrationId: data.registrationId, response }) })
    await verifyWebAuthn()
  } catch (e) { mfaError.value = e instanceof Error ? e.message : 'Passkey 设置失败，请重试' }
  finally { loading.value = false }
}

function resetMfa() {
  mfaTransactionId.value = ''; mfaCode.value = ''; mfaError.value = ''; mfaSecret.value = ''; mfaEnrollmentId.value = ''
}
</script>

<template>
  <template v-if="mfaTransactionId">
    <NAlert type="warning" :bordered="false" class="wide-alert">
      <template #header>{{ mfaSetup ? '高权限账户需要设置 MFA' : '需要完成 MFA 验证' }}</template>
      {{ mfaSetup ? '请完成第二因素设置后继续登录。' : '密码验证已完成，请继续验证第二因素。' }}
    </NAlert>
    <div v-if="mfaSetup && mfaSecret" class="mfa-box">
      <span>使用认证器添加此密钥：</span><code>{{ mfaSecret }}</code><small>{{ mfaOtpauthUri }}</small>
      <NInput v-model:value="mfaCode" maxlength="6" placeholder="认证器验证码" />
      <NButton type="success" :loading="loading" :disabled="mfaCode.length !== 6" @click="confirmTotpSetup">确认 TOTP</NButton>
    </div>
    <template v-else-if="!mfaSetup && mfaMethods.includes('totp')">
      <NInput v-model:value="mfaCode" maxlength="6" placeholder="认证器验证码" class="login-input" />
      <NButton type="success" :loading="loading" :disabled="mfaCode.length !== 6" @click="verifyMfa">验证 TOTP</NButton>
    </template>
    <NButton v-if="mfaMethods.includes('webauthn')" type="success" dashed :loading="loading" @click="mfaSetup ? setupWebAuthn() : verifyWebAuthn()">
      {{ mfaSetup ? '设置 Passkey' : '使用 Passkey' }}
    </NButton>
    <p v-if="mfaError" class="error-msg">{{ mfaError }}</p>
    <NButton quaternary :disabled="loading" @click="resetMfa">返回登录</NButton>
  </template>

  <template v-else>
    <NAlert v-if="loginError && loginErrorState === 'none'" type="warning" :bordered="false" class="wide-alert">{{ loginError }}</NAlert>
    <p v-if="loginErrorState === 'network_error'" class="error-msg">{{ loginError }}</p>
    <form class="login-form" autocomplete="on" @submit.prevent="handleLogin">
      <NInput v-model:value="usernameOrEmail" type="text" size="large" placeholder="用户名 / 邮箱" class="underline-input" :disabled="lockedOut" :input-props="{ name: 'username', autocomplete: 'username' }" />
      <NInput v-model:value="password" type="password" size="large" placeholder="密码" class="underline-input" :disabled="lockedOut" :input-props="{ name: 'password', autocomplete: 'current-password' }" />
      <NButton attr-type="button" :type="rememberMe ? 'success' : 'default'" dashed :disabled="lockedOut" @click="rememberMe = !rememberMe">
        {{ rememberMe ? '保持登录（仅 HttpOnly Cookie）' : '本次会话登录' }}
      </NButton>
      <NButton attr-type="submit" type="success" size="large" circle class="submit-btn" :loading="loading" :disabled="!usernameOrEmail || !password || lockedOut">-&gt;</NButton>
    </form>
    <NButton v-if="!loading && !lockedOut" quaternary type="success" size="small" @click="router.push('/ForgetPassword')">忘记密码？</NButton>

    <NAlert v-if="['ip_banned', 'server_error', 'locked_out'].includes(loginErrorState)" :type="loginErrorState === 'locked_out' ? 'warning' : 'error'" :bordered="false" class="wide-alert">
      <template #header>{{ loginErrorState === 'ip_banned' ? '登录暂时受限' : loginErrorState === 'locked_out' ? '账号已被锁定' : '登录服务故障' }}</template>
      <template v-if="loginErrorState === 'ip_banned'">
        <p>关闭此页面，更换网络环境以重试。如有疑问，请将编码 <code>{{ loginBanId }}</code> 发送至 {{ supportEmail || '站点管理员' }}。</p>
      </template>
      <template v-else><p>{{ loginError }}</p><p v-if="loginErrorState === 'server_error'">请联系 {{ supportEmail || '站点管理员' }}。</p></template>
    </NAlert>
  </template>
</template>

<style scoped>
.login-form { display: flex; flex-direction: column; align-items: center; gap: 12px; width: 100%; }
.login-input, .wide-alert { width: 100%; max-width: 420px; }
.wide-alert { text-align: left; }
.mfa-box { display: flex; flex-direction: column; gap: 10px; width: 100%; max-width: 420px; padding: 14px; border: 1px solid var(--input-border); border-radius: 12px; text-align: left; }
.mfa-box code, .mfa-box small { overflow-wrap: anywhere; }
.error-msg { color: var(--error-color); margin: 0; }
</style>
