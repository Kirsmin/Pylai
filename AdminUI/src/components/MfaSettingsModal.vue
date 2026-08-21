<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { createCredential } from '@/utils/webauthn'

const authStore = useAuthStore()
const visible = ref(false)
const busy = ref(false)
const error = ref('')
const enrollmentId = ref('')
const secret = ref('')
const otpauthUri = ref('')
const code = ref('')
const passkeyMessage = ref('')

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
    const data = await authStore.request<{ enrollmentId: string; secret: string; otpauthUri: string; error?: string }>(
      '/api/auth/mfa/totp/enroll',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }
    )
    if (!data?.enrollmentId) throw new Error(data?.error || '无法开始设置时间验证码')
    enrollmentId.value = data.enrollmentId
    secret.value = data.secret
    otpauthUri.value = data.otpauthUri
    code.value = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无法开始设置时间验证码'
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
    error.value = err instanceof Error ? err.message : '时间验证码验证失败'
  } finally {
    busy.value = false
  }
}

async function registerPasskey() {
  busy.value = true
  error.value = ''
  passkeyMessage.value = ''
  try {
    const data = await authStore.request<{ registrationId: string; options: any; error?: string }>(
      '/api/auth/mfa/webauthn/registration-options',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }
    )
    if (!data?.registrationId) throw new Error(data?.error || '无法开始注册通行密钥')
    const response = await createCredential(data.options)
    await authStore.request('/api/auth/mfa/webauthn/registration', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ registrationId: data.registrationId, response })
    })
    passkeyMessage.value = '通行密钥已注册。'
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '通行密钥注册失败'
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
          <strong>时间验证码认证器</strong>
          <span class="muted">{{ authStore.mfaTotpEnabled ? '已启用' : '未启用' }}</span>
        </div>
        <NButton v-if="!authStore.mfaTotpEnabled && !secret" size="tiny" type="success" ghost :loading="busy" @click="beginTotp">设置</NButton>
      </div>

      <div class="admin-line-card">
        <div class="admin-line-main">
          <strong>通行密钥 / WebAuthn</strong>
          <span class="muted">已注册 {{ authStore.mfaWebAuthnCount }} 个</span>
        </div>
        <NButton size="tiny" type="success" dashed :loading="busy" @click="registerPasskey">注册通行密钥</NButton>
      </div>

      <div v-if="secret" class="mfa-secret-box">
        <p>请立即在认证器中添加此密钥：</p>
        <code class="mono">{{ secret }}</code>
        <small class="muted">{{ otpauthUri }}</small>
        <input v-model="code" class="admin-input mono" maxlength="6" placeholder="认证器验证码" />
        <NButton type="success" ghost :loading="busy" :disabled="code.length !== 6" @click="confirmTotp">确认时间验证码</NButton>
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

.success-msg {
  margin: 0;
  color: var(--success-color);
}
</style>
