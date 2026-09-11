<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const methods = computed(() => authStore.stepUpTicket?.methods ?? [])
const otpValue = computed<string[]>({
  get: () => authStore.stepUpCode.split('').slice(0, 6),
  set: (value) => { authStore.stepUpCode = value.join('') }
})

function allowOtpDigit(value: string) {
  return /^\d$/.test(value)
}
</script>

<template>
  <NModal
    :show="authStore.stepUpVisible"
    preset="card"
    style="width: min(calc(100vw - 24px), 440px);"
    title="敏感操作需要 MFA 验证"
    :mask-closable="false"
    :close-on-esc="false"
  >
    <div class="admin-form-stack">
      <p class="muted mfa-copy">此操作会修改高权限数据。完成第二因素验证后，将自动继续原操作。</p>

      <template v-if="methods.includes('totp')">
        <div class="admin-field">
          <span class="admin-field-label">TOTP 验证码</span>
          <NInputOtp
            v-model:value="otpValue"
            :length="6"
            :allow-input="allowOtpDigit"
            size="large"
            block
            aria-label="六位 TOTP 验证码"
          />
          <span class="field-hint">支持直接粘贴认证器中的 6 位验证码。</span>
        </div>
        <NButton type="primary" :loading="authStore.stepUpBusy" :disabled="authStore.stepUpCode.length !== 6" @click="authStore.verifyStepUpTotp()">
          验证 TOTP
        </NButton>
      </template>

      <NButton v-if="methods.includes('webauthn')" type="primary" secondary :loading="authStore.stepUpBusy" @click="authStore.verifyStepUpWebAuthn()">
        使用 Passkey 验证
      </NButton>

      <p v-if="authStore.stepUpError" class="error-msg">{{ authStore.stepUpError }}</p>
      <NButton quaternary :disabled="authStore.stepUpBusy" @click="authStore.cancelMfaStepUp()">取消操作</NButton>
    </div>
  </NModal>
</template>

<style scoped>
.mfa-copy { margin: 0; }
</style>
