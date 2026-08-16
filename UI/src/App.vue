<script setup lang="ts">
import { darkTheme } from 'naive-ui'
import { computed, watch } from 'vue'
import { useThemeStore } from '@/stores/theme'
import { useAuthStore } from '@/stores/auth'

const themeStore = useThemeStore()
const authStore = useAuthStore()

const themeOverrides = {
  common: {
    fontFamily: "'AppFont', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontFamilyMono: "'AppFont', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
  }
}

const userGroup = computed(() => {
  const group = authStore.user?.group?.toLowerCase() ?? ''
  if (group === 'admin' || group === 'max' || group === 'normal') return group
  return authStore.user ? 'normal' : ''
})

watch(
  userGroup,
  (group, prev) => {
    const root = document.documentElement
    if (prev) root.classList.remove(`user-group-${prev}`)
    if (group) root.classList.add(`user-group-${group}`)
  },
  { immediate: true }
)
</script>

<template>
  <NConfigProvider :theme="themeStore.isDark ? darkTheme : null" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <router-view />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
