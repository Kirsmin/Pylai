<script setup lang="ts">
import { ref } from 'vue'
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
const code = ref('')
const passkeyMessage = ref('')
// 浏览器安全上下文限制：HTTP 部署下 TOTP 注册被后端拒绝、Passkey API 不可用
const insecureContext = !window.isSecureContext

async function load() {
  await authStore.loadMfaStatus()
}

async function open() {
  error.value = ''
  code.value = ''
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
    code.value = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无法开始 TOTP 设置'
  } finally {
    busy.value = false
  }
}

async function confirmTotp() {
  if (code.value.length !== 6 || !enrollmentId.value) return
  busy.value = true
  error.value = ''
  try {
    await authStore.request('/api/auth/mfa/totp/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enrollmentId: enrollmentId.value, code: code.value })
    })
    secret.value = ''
    otpauthUri.value = ''
    enrollmentId.value = ''
    code.value = ''
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
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
  <NModal v-model:show="visible" preset="card" style="width: min(92%, 480px);" title="账户安全与 MFA">
    <div class="admin-form-stack">
      <div class="admin-line-card">
        <div class="admin-line-main">
          <strong>TOTP 认证器</strong>
          <span class="muted">{{ authStore.mfaTotpEnabled ? '已启用' : insecureContext ? '未启用（需 HTTPS 部署才能设置）' : '未启用' }}</span>
        </div>
        <NButton v-if="!authStore.mfaTotpEnabled && !secret" size="tiny" type="success" ghost :loading="busy" :disabled="insecureContext" @click="beginTotp">设置</NButton>
      </div>

      <div class="admin-line-card">
        <div class="admin-line-main">
          <strong>Passkey / WebAuthn</strong>
          <span class="muted">已注册 {{ authStore.mfaWebAuthnCount }} 个</span>
        </div>
        <NButton size="tiny" type="success" dashed :loading="busy" @click="registerPasskey">注册 Passkey</NButton>
      </div>

      <div v-if="secret" class="mfa-secret-box">
        <p>请使用手机认证器扫描下方二维码，或手动输入密钥：</p>
        <div class="qr-wrap">
          <NQRCode
            :value="otpauthUri"
            :size="160"
            :padding="4"
            type="svg"
          />
        </div>
        <div class="secret-manual">
          <span class="muted">密钥</span>
          <code class="mono">{{ secret }}</code>
          <NButton size="tiny" quaternary @click="copySecret">复制</NButton>
        </div>
        <small class="muted">{{ otpauthUri }}</small>
        <input v-model="code" class="admin-input mono" maxlength="6" placeholder="输入认证器显示的6位验证码" />
        <NButton type="success" ghost :loading="busy" :disabled="code.length !== 6" @click="confirmTotp">确认 TOTP</NButton>
      </div>

      <p v-if="passkeyMessage" class="success-msg">{{ passkeyMessage }}</p>
      <p v-if="error" class="error-msg">{{ error }}</p>
      <NButton quaternary @click="visible = false">关闭</NButton>
    </div>
  </NModal>
</template>

<style scoped>
.mfa-secret-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--success-color);
  border-radius: 12px;
  background: var(--badge-bg);
}

.mfa-secret-box code {
  overflow-wrap: anywhere;
  font-size: 16px;
  color: var(--text-primary);
}

.qr-wrap {
  display: flex;
  justify-content: center;
  padding: 8px;
  background: #fff;
  border-radius: 8px;
  align-self: center;
}

.secret-manual {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.secret-manual code {
  flex: 1 1 auto;
  overflow-wrap: anywhere;
  font-size: 16px;
  color: var(--text-primary);
}

.success-msg {
  margin: 0;
  color: var(--success-color);
}
</style>
