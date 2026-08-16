<script setup lang="ts">
import { darkTheme } from 'naive-ui'
import { computed, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import LoginView from '@/views/LoginView.vue'
import AdminLayout from '@/components/AdminLayout.vue'

const authStore = useAuthStore()
const themeStore = useThemeStore()

const themeOverrides = {
  common: {
    fontFamily: "'AppFont', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    fontFamilyMono: "'AppFont', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
  }
}

const userGroup = computed(() => authStore.group)

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
        <template v-if="!authStore.initialized">
          <div class="boot-loading">
            <NSpin />
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
