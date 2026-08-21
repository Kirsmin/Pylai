<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const methods = computed(() => authStore.stepUpTicket?.methods ?? [])
</script>

<template>
  <NModal
    :show="authStore.stepUpVisible"
    preset="card"
    style="width: min(92%, 440px);"
    title="敏感操作需要 MFA 验证"
    :mask-closable="false"
  >
    <div class="admin-form-stack">
      <p class="muted">此操作会修改高权限数据。请先完成第二因素验证，验证成功后将自动继续原操作。</p>

      <template v-if="methods.includes('totp')">
        <label class="admin-field">
          <span class="admin-field-label">时间验证码</span>
          <input v-model="authStore.stepUpCode" class="admin-input mono" maxlength="6" placeholder="6 位验证码" />
        </label>
        <NButton type="success" ghost :loading="authStore.stepUpBusy" :disabled="authStore.stepUpCode.length !== 6" @click="authStore.verifyStepUpTotp()">
          验证时间验证码
        </NButton>
      </template>

      <NButton v-if="methods.includes('webauthn')" type="success" dashed :loading="authStore.stepUpBusy" @click="authStore.verifyStepUpWebAuthn()">
        使用通行密钥验证
      </NButton>

      <p v-if="authStore.stepUpError" class="error-msg">{{ authStore.stepUpError }}</p>
      <NButton quaternary :disabled="authStore.stepUpBusy" @click="authStore.cancelMfaStepUp()">取消操作</NButton>
    </div>
  </NModal>
</template>
