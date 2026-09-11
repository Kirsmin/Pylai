<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
const authStore = useAuthStore()
</script>

<template>
  <div class="login-shell">
    <div class="login-card animate-fade">
      <div class="login-brand">
        <span class="brand-mark">P</span>
        <div>
          <h1 class="login-title">Pylai 控制台</h1>
          <p class="login-subtitle">管理员登录 · 用户、OAuth2、邀请与安全策略</p>
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

      <p class="login-foot">受多因素认证（MFA）保护</p>
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
  box-shadow: var(--shadow-md);
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
  margin: 0;
  text-align: center;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
