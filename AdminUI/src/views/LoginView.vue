<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
</script>

<template>
  <div class="page-shell">
    <div class="page-wrapper">
      <div class="page-card">
        <div class="login-content">
          <h1 class="login-title"># Pylai</h1>
          <p class="login-subtitle">管理 Pylai 平台</p>

          <NButton
            type="success"
            ghost
            size="large"
            :loading="authStore.starting"
            @click="authStore.startLogin()"
          >
            通过 Pylai 通行证登录
          </NButton>

          <p v-if="authStore.loginError" class="error-msg">{{ authStore.loginError }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 32px;
  text-align: center;
}

.login-title {
  margin: 0;
  font-weight: 600;
  font-size: 32px;
  color: var(--text-primary);
}

.login-subtitle {
  margin: 0;
  font-size: 16px;
  color: var(--text-secondary);
}

@media (max-width: 640px) {
  .login-title {
    font-size: 26px;
  }

  .login-subtitle {
    font-size: 14px;
  }

  .login-content {
    padding: 36px 20px;
  }
}
</style>
