<script setup lang="ts">
import { computed } from 'vue'
import { darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import LoginView from '@/views/LoginView.vue'
import AdminLayout from '@/components/AdminLayout.vue'

const authStore = useAuthStore()
const themeStore = useThemeStore()

const themeOverrides = computed<GlobalThemeOverrides>(() => {
  const dark = themeStore.isDark
  const primary = dark ? '#36ad6a' : '#18a058'
  const primaryHover = dark ? '#4fb87d' : '#0e7a3d'
  const primaryPressed = dark ? '#2b9258' : '#096b34'

  return {
    common: {
      fontFamily: 'var(--font-family)',
      fontFamilyMono: 'var(--font-family-mono)',
      borderRadius: '6px',
      borderRadiusSmall: '5px',
      primaryColor: primary,
      primaryColorHover: primaryHover,
      primaryColorPressed: primaryPressed,
      primaryColorSuppl: primary,
      successColor: primary,
      successColorHover: primaryHover,
      successColorPressed: primaryPressed,
      successColorSuppl: primary,
      errorColor: dark ? '#ef7474' : '#c94b4b',
      warningColor: dark ? '#e0b15a' : '#a96d12',
      infoColor: dark ? '#7ba5e7' : '#416fae',
    },
    Card: { borderRadius: '8px' },
    Modal: { borderRadius: '8px' },
    Dialog: { borderRadius: '8px' },
    Button: {
      borderRadiusMedium: '6px',
      borderRadiusSmall: '5px',
      borderRadiusTiny: '4px',
      fontWeight: '500',
    },
    Input: { borderRadius: '6px' },
    Select: { borderRadius: '6px' },
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
        <template v-else>
          <AdminLayout>
            <router-view v-slot="{ Component }">
              <transition name="page" mode="out-in">
                <component :is="Component" />
              </transition>
            </router-view>
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
.page-enter-active,
.page-leave-active {
  transition: opacity 0.12s ease;
}
.page-enter-from,
.page-leave-to {
  opacity: 0;
}
</style>
