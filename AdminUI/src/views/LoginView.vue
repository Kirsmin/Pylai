<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
const authStore = useAuthStore()
const appVersion = __APP_VERSION__
</script>

<template>
  <div class="login-shell">
    <div class="login-card animate-fade">
      <div class="login-brand">
        <span class="brand-mark">P</span>
        <div>
          <h1 class="login-title">Pylai Admin</h1>
          <p class="login-subtitle">管理控制台</p>
        </div>
      </div>

      <div v-if="authStore.loginError" class="login-error" role="alert">
        {{ authStore.loginError }}
      </div>

      <NButton
        type="primary"
        size="large"
        block
        :loading="authStore.starting"
        @click="authStore.startLogin"
      >
        登录
      </NButton>

      <div class="login-foot"><span>管理员会话受 MFA 与 CSRF 保护</span><span class="mono">v{{ appVersion }}</span></div>
    </div>
  </div>
</template>

<style scoped>
.login-shell {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: var(--page-bg);
}
.login-card {
  width: min(100%, 380px);
  padding: 36px 32px 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: none;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.login-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 2px;
}
.brand-mark {
  width: 40px;
  height: 40px;
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-sunken);
  color: var(--text-primary);
  font-family: var(--font-family-mono);
  font-size: 17px;
  font-weight: 700;
  flex-shrink: 0;
}
.login-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}
.login-subtitle {
  margin: 3px 0 0;
  font-size: 13px;
  color: var(--text-tertiary);
  line-height: 1.5;
}
.login-error {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 13px;
  line-height: 1.5;
}
.login-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 11px;
  color: var(--text-tertiary);
}
</style>
