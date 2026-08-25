<script setup lang="ts">
import { darkTheme } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import { computed, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import LoginView from '@/views/LoginView.vue'
import AdminLayout from '@/components/AdminLayout.vue'

const authStore = useAuthStore()
const themeStore = useThemeStore()

const lightPalette = {
  accent: '#16a34a',
  accentHover: '#1fb457',
  accentPressed: '#128a43',
  accentSuppl: '#16a34a',
  error: '#e5484d',
  errorHover: '#ec6367',
  errorPressed: '#cd3a3f',
  warning: '#d9930d',
  info: '#3574e0',
}
const darkPalette = {
  accent: '#34c77b',
  accentHover: '#52d391',
  accentPressed: '#2aaa68',
  accentSuppl: '#34c77b',
  error: '#f2555a',
  errorHover: '#f47377',
  errorPressed: '#d64045',
  warning: '#f0b64a',
  info: '#6b9bff',
}

const themeOverrides = computed<GlobalThemeOverrides>(() => {
  const p = themeStore.isDark ? darkPalette : lightPalette
  return {
    common: {
      fontFamily: 'var(--font-family)',
      fontFamilyMono: 'var(--font-family-mono)',
      borderRadius: '8px',
      borderRadiusSmall: '6px',
      primaryColor: p.accent,
      primaryColorHover: p.accentHover,
      primaryColorPressed: p.accentPressed,
      primaryColorSuppl: p.accentSuppl,
      successColor: p.accent,
      successColorHover: p.accentHover,
      successColorPressed: p.accentPressed,
      successColorSuppl: p.accentSuppl,
      errorColor: p.error,
      errorColorHover: p.errorHover,
      errorColorPressed: p.errorPressed,
      errorColorSuppl: p.error,
      warningColor: p.warning,
      infoColor: p.info,
    },
    Card: {
      borderRadius: '14px',
    },
    Modal: {
      borderRadius: '14px',
    },
    Dialog: {
      borderRadius: '14px',
    },
    Button: {
      borderRadiusMedium: '8px',
      borderRadiusSmall: '7px',
      borderRadiusTiny: '6px',
      fontWeight: '500',
    },
    Input: {
      borderRadius: '8px',
    },
    Select: {
      borderRadius: '8px',
    },
    Tag: {
      borderRadius: '6px',
    },
  }
})

const userGroup = computed(() => authStore.group)

watch(userGroup, (group, prev) => {
  const root = document.documentElement
  if (prev) root.classList.remove(`user-group-${prev}`)
  if (group) root.classList.add(`user-group-${group}`)
}, { immediate: true })
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
  position: fixed; inset: 0;
  display: flex; align-items: center; justify-content: center;
  background: var(--page-bg);
}
.page-enter-active, .page-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.page-enter-from {
  opacity: 0; transform: translateY(6px);
}
.page-leave-to {
  opacity: 0; transform: translateY(-4px);
}
</style>
