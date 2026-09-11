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
</style>
