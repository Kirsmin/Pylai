<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import { createCredential } from '@/utils/webauthn'
import PageHeader from '@/components/PageHeader.vue'
import AppBadge from '@/components/AppBadge.vue'

const authStore = useAuthStore()
const message = useMessage()
const busy = ref(false)
const error = ref('')
const enrollmentId = ref('')
const secret = ref('')
const otpauthUri = ref('')
const code = ref<string[]>([])
const passkeyMessage = ref('')
const insecureContext = !window.isSecureContext

const otpCode = computed(() => code.value.join(''))
const secondFactorCount = computed(() => Number(authStore.mfaTotpEnabled) + authStore.mfaWebAuthnCount)

function allowOtpDigit(value: string) {
  return /^\d$/.test(value)
}

async function load() {
  await authStore.loadMfaStatus()
}

async function beginTotp() {
  busy.value = true
  error.value = ''
  passkeyMessage.value = ''
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
    message.success('TOTP 已启用')
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

onMounted(load)
</script>

<template>
  <section class="admin-page">
    <PageHeader
      title="账户安全"
      subtitle="管理当前管理员账户的第二因素认证。敏感管理操作会使用这里配置的认证方式进行 Step-up 验证。"
    >
      <template #actions>
        <NButton quaternary :loading="busy" @click="load">刷新状态</NButton>
      </template>
    </PageHeader>

    <div class="security-summary admin-panel">
      <div>
        <span class="summary-kicker">MFA 状态</span>
        <strong>{{ secondFactorCount > 0 ? '已配置第二因素' : '尚未配置第二因素' }}</strong>
        <span class="muted">TOTP {{ authStore.mfaTotpEnabled ? '已启用' : '未启用' }} · Passkey {{ authStore.mfaWebAuthnCount }} 个</span>
      </div>
      <AppBadge :tone="secondFactorCount > 0 ? 'success' : 'warning'">
        {{ secondFactorCount > 0 ? '已保护' : '建议配置' }}
      </AppBadge>
    </div>

    <div class="security-grid">
      <article class="admin-panel security-card">
        <div class="security-card-header">
          <div>
            <h3>TOTP 认证器</h3>
            <p>使用支持 RFC 6238 的认证器生成 6 位一次性验证码。</p>
          </div>
          <AppBadge :tone="authStore.mfaTotpEnabled ? 'success' : 'neutral'">
            {{ authStore.mfaTotpEnabled ? '已启用' : '未启用' }}
          </AppBadge>
        </div>

        <template v-if="authStore.mfaTotpEnabled">
          <div class="security-card-body">
            <p class="muted">当前账户已启用 TOTP。高权限操作要求二次认证时，可直接输入认证器中的 6 位验证码。</p>
          </div>
        </template>
        <template v-else>
          <div class="security-card-body">
            <NAlert v-if="insecureContext" type="warning" :show-icon="false">
              当前页面不是安全上下文。请通过 HTTPS 访问后再设置 TOTP。
            </NAlert>
            <NButton v-if="!secret" type="primary" :loading="busy" :disabled="insecureContext" @click="beginTotp">
              开始设置 TOTP
            </NButton>

            <div v-else class="totp-enrollment">
              <div class="qr-wrap">
                <NQrCode :value="otpauthUri" :size="184" :padding="6" type="svg" error-correction-level="H" />
              </div>
              <div class="totp-instructions">
                <div>
                  <span class="field-label">手动输入密钥</span>
                  <div class="secret-row">
                    <code class="mono">{{ secret }}</code>
                    <NButton size="small" quaternary @click="copySecret">复制</NButton>
                  </div>
                </div>
                <div>
                  <span class="field-label">验证一次性验证码</span>
                  <NInputOtp
                    v-model:value="code"
                    :length="6"
                    :allow-input="allowOtpDigit"
                    size="large"
                    block
                    aria-label="六位 TOTP 验证码"
                  />
                  <span class="field-hint">可直接粘贴 6 位验证码。</span>
                </div>
                <NButton type="primary" :loading="busy" :disabled="otpCode.length !== 6" @click="confirmTotp">
                  验证并启用
                </NButton>
              </div>
            </div>
          </div>
        </template>
      </article>

      <article class="admin-panel security-card">
        <div class="security-card-header">
          <div>
            <h3>Passkey / WebAuthn</h3>
            <p>使用硬件安全密钥、系统凭据或生物识别完成强认证。</p>
          </div>
          <AppBadge :tone="authStore.mfaWebAuthnCount > 0 ? 'success' : 'neutral'">
            {{ authStore.mfaWebAuthnCount }} 个
          </AppBadge>
        </div>
        <div class="security-card-body">
          <p class="muted">Passkey 需要浏览器和部署环境支持 WebAuthn。可注册多个凭据，便于在不同设备上使用。</p>
          <NButton type="primary" secondary :loading="busy" :disabled="insecureContext" @click="registerPasskey">
            注册 Passkey
          </NButton>
          <p v-if="insecureContext" class="field-hint">当前页面不是安全上下文，WebAuthn 不可用。</p>
          <p v-if="passkeyMessage" class="success-msg">{{ passkeyMessage }}</p>
        </div>
      </article>
    </div>

    <NAlert v-if="error" type="error" :show-icon="false">{{ error }}</NAlert>
  </section>
</template>

<style scoped>
.security-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 16px 18px;
}
.security-summary > div { display: flex; flex-direction: column; gap: 2px; }
.summary-kicker { color: var(--text-tertiary); font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
.security-summary strong { font-size: 15px; font-weight: 650; }
.security-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--gap); align-items: start; }
.security-card { overflow: hidden; }
.security-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.security-card-header h3 { margin: 0; font-size: 14px; font-weight: 650; }
.security-card-header p { margin: 4px 0 0; color: var(--text-tertiary); font-size: 12px; }
.security-card-body { display: flex; flex-direction: column; gap: 14px; padding: 18px; }
.security-card-body > p { margin: 0; }
.totp-enrollment { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 20px; align-items: start; }
.qr-wrap { width: 204px; display: flex; justify-content: center; padding: 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: #fff; }
.totp-instructions { min-width: 0; display: flex; flex-direction: column; gap: 16px; }
.secret-row { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 8px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); }
.secret-row code { min-width: 0; flex: 1; overflow-wrap: anywhere; font-size: 13px; }
.success-msg { color: var(--success); }
@media (max-width: 900px) { .security-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .totp-enrollment { grid-template-columns: 1fr; } .qr-wrap { width: auto; justify-self: center; } }
</style>
