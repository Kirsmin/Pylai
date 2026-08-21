<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
const authStore = useAuthStore()
</script>

<template>
  <div class="login-shell">
    <div class="login-card animate-fade">
      <h1 class="login-title">Pylai 管理后台</h1>
      <p class="login-subtitle">管理控制台</p>
      <NButton v-if="authStore.loginError" type="error" text class="login-error">
        {{ authStore.loginError }}
      </NButton>
      <NButton
        type="success"
        size="large"
        style="width:100%;margin-top:8px;"
        :loading="authStore.starting"
        @click="authStore.startLogin"
      >
        登录
      </NButton>
    </div>
  </div>
</template>

<style scoped>
.login-shell {
  position: fixed; inset: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--page-bg);
  padding: 20px;
}
.login-card {
  width: min(92%, 360px);
  padding: 36px 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.login-title {
  margin: 0;
  font-family: var(--font-family-mono);
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
}
.login-subtitle {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--text-tertiary);
}
.login-error {
  justify-content: center;
  font-size: 13px;
}
</style>