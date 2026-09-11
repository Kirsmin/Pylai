<script setup lang="ts">
/*
 * 兼容旧调用点的 MFA 弹窗。主入口已迁移到 /security 独立页面，
 * 此组件保留供可能的外部引用使用，并统一采用 Naive UI NInputOtp。
 */
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { createCredential } from '@/utils/webauthn'
import { useMessage } from 'naive-ui'

const authStore = useAuthStore()
const message = useMessage()
const visible = ref(false)
const busy = ref(false)
const error = ref('')
const enrollmentId = ref('')
const secret = ref('')
const otpauthUri = ref('')
const code = ref<string[]>([])
const passkeyMessage = ref('')
const insecureContext = !window.isSecureContext
const otpCode = computed(() => code.value.join(''))

function allowOtpDigit(value: string) { return /^\d$/.test(value) }
async function load() { await authStore.loadMfaStatus() }

async function open() {
  error.value = ''
  code.value = []
  secret.value = ''
  enrollmentId.value = ''
  visible.value = true
  await load()
}

async function beginTotp() {
  busy.value = true
  error.value = ''
  try {
    const data = await authStore.request<{ success: boolean; enrollmentId: string; secret: string; otpauthUri: string; error?: string }>(
      '/api/auth/mfa/totp/enroll',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }
    )
    if (!data?.enrollmentId) throw new Error(data?.error || '无法开始 TOTP 设置')
    enrollmentId.value = data.enrollmentId
    secret.value = data.secret
    otpauthUri.value = data.otpauthUri
    code.value = []
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无法开始 TOTP 设置'
  } finally {
    busy.value = false
  }
}

async function confirmTotp() {
  if (otpCode.value.length !== 6 || !enrollmentId.value) return
  busy.value = true
  error.value = ''
  try {
    await authStore.request('/api/auth/mfa/totp/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enrollmentId: enrollmentId.value, code: otpCode.value })
    })
    secret.value = ''
    otpauthUri.value = ''
    enrollmentId.value = ''
    code.value = []
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'TOTP 验证失败'
  } finally {
    busy.value = false
  }
}

async function copySecret() {
  try {
    await navigator.clipboard.writeText(secret.value)
    message.success('密钥已复制')
  } catch {
    message.error('复制失败，请手动复制')
  }
}

async function registerPasskey() {
  busy.value = true
  error.value = ''
  passkeyMessage.value = ''
  try {
    const data = await authStore.request<{ success: boolean; registrationId: string; options: any; error?: string }>(
      '/api/auth/mfa/webauthn/registration-options',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }
    )
    if (!data?.registrationId) throw new Error(data?.error || '无法开始 Passkey 注册')
    const response = await createCredential(data.options)
    await authStore.request('/api/auth/mfa/webauthn/registration', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ registrationId: data.registrationId, response })
    })
    passkeyMessage.value = 'Passkey 已注册。'
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Passkey 注册失败'
  } finally {
    busy.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <NModal v-model:show="visible" preset="card" style="width: min(calc(100vw - 24px), 520px);" title="账户安全与 MFA">
    <div class="admin-form-stack">
      <div class="admin-line-card">
        <div class="admin-line-main">
          <strong>TOTP 认证器</strong>
          <span class="muted">{{ authStore.mfaTotpEnabled ? '已启用' : insecureContext ? '未启用（需 HTTPS 部署才能设置）' : '未启用' }}</span>
        </div>
        <NButton v-if="!authStore.mfaTotpEnabled && !secret" size="tiny" type="primary" :loading="busy" :disabled="insecureContext" @click="beginTotp">设置</NButton>
      </div>

      <div class="admin-line-card">
        <div class="admin-line-main">
          <strong>Passkey / WebAuthn</strong>
          <span class="muted">已注册 {{ authStore.mfaWebAuthnCount }} 个</span>
        </div>
        <NButton size="tiny" type="primary" secondary :loading="busy" :disabled="insecureContext" @click="registerPasskey">注册 Passkey</NButton>
      </div>

      <div v-if="secret" class="mfa-secret-box">
        <p>请使用手机认证器扫描下方二维码，或手动输入密钥：</p>
        <div class="qr-wrap">
          <NQrCode :value="otpauthUri" :size="180" :padding="4" type="svg" error-correction-level="H" />
        </div>
        <div class="secret-manual">
          <span class="muted">密钥</span>
          <code class="mono">{{ secret }}</code>
          <NButton size="tiny" quaternary @click="copySecret">复制</NButton>
        </div>
        <NInputOtp v-model:value="code" :length="6" :allow-input="allowOtpDigit" size="large" block />
        <NButton type="primary" :loading="busy" :disabled="otpCode.length !== 6" @click="confirmTotp">确认 TOTP</NButton>
      </div>

      <p v-if="passkeyMessage" class="success-msg">{{ passkeyMessage }}</p>
      <p v-if="error" class="error-msg">{{ error }}</p>
      <NButton quaternary @click="visible = false">关闭</NButton>
    </div>
  </NModal>
</template>

<style scoped>
.mfa-secret-box { display: flex; flex-direction: column; gap: 12px; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.mfa-secret-box p { margin: 0; }
.qr-wrap { display: flex; justify-content: center; padding: 8px; background: #fff; border-radius: var(--radius-sm); align-self: center; }
.secret-manual { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.secret-manual code { flex: 1 1 auto; overflow-wrap: anywhere; font-size: 14px; color: var(--text-primary); }
.success-msg { margin: 0; color: var(--success); }
</style>
