<script setup lang="ts">
import { computed } from 'vue'
import { darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import { API_BASE } from '@/utils/http'
import LoginView from '@/views/LoginView.vue'
import AdminLayout from '@/components/AdminLayout.vue'

const authStore = useAuthStore()
const themeStore = useThemeStore()

const themeOverrides = computed<GlobalThemeOverrides>(() => {
  const dark = themeStore.isDark
  const primary = dark ? '#43a56f' : '#19734a'
  const primaryHover = dark ? '#55b27f' : '#125f3d'
  const primaryPressed = dark ? '#378c5f' : '#0d5033'

  return {
    common: {
      fontFamily: 'var(--font-family)',
      fontFamilyMono: 'var(--font-family-mono)',
      borderRadius: '5px',
      borderRadiusSmall: '4px',
      primaryColor: primary,
      primaryColorHover: primaryHover,
      primaryColorPressed: primaryPressed,
      primaryColorSuppl: primary,
      successColor: dark ? '#43a56f' : '#19734a',
      errorColor: dark ? '#e47171' : '#b83f43',
      warningColor: dark ? '#d9a74d' : '#99620e',
      infoColor: dark ? '#729cda' : '#3d69a3',
    },
    Card: { borderRadius: '6px' },
    Modal: { borderRadius: '6px' },
    Dialog: { borderRadius: '6px' },
    Button: {
      borderRadiusMedium: '5px',
      borderRadiusSmall: '4px',
      borderRadiusTiny: '4px',
      fontWeight: '500',
    },
    Input: { borderRadius: '5px' },
    Select: { borderRadius: '5px' },
    Tag: { borderRadius: '4px' },
  }
})
</script>

<template>
  <NConfigProvider :theme="themeStore.isDark ? darkTheme : null" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <template v-if="!authStore.initialized">
          <div class="boot-loading">
            <NSpin size="medium" />
          </div>
        </template>
        <template v-else-if="!authStore.isAuthenticated">
          <LoginView />
        </template>
        <template v-else-if="!authStore.adminAccess">
          <div class="forbidden-page">
            <div class="forbidden-card">
              <span class="forbidden-code">403</span>
              <strong>当前账户没有管理权限</strong>
              <p class="muted">此账户已登录，但不属于 admin / max 用户组，无法访问管理台。如需权限请联系 Max 管理员调整用户组。</p>
              <NButton type="primary" tag="a" :href="`${API_BASE}/`">返回用户中心</NButton>
            </div>
          </div>
        </template>
        <template v-else>
          <AdminLayout>
            <router-view />
          </AdminLayout>
        </template>
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style scoped>
.boot-loading {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--page-bg);
}
.forbidden-page {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: var(--page-bg);
}
.forbidden-card {
  max-width: 420px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md, 8px);
  background: var(--surface, #fff);
}
.forbidden-code { font-size: 34px; font-weight: 800; color: var(--text-tertiary); line-height: 1; }
.forbidden-card strong { font-size: 16px; font-weight: 650; }
.forbidden-card p { margin: 0 0 6px; font-size: 13px; line-height: 1.6; }
</style>
