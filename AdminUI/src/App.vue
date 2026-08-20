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
    fontFamily: "'AppFont', system-ui, -apple-system, sans-serif",
    fontFamilyMono: "'AppFont', ui-monospace, monospace",
    primaryColor: '#18a058',
    primaryColorHover: '#0e7a3d',
    primaryColorPressed: '#0a5c2e',
  }
}

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
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.page-enter-from {
  opacity: 0; transform: translateY(6px);
}
.page-leave-to {
  opacity: 0; transform: translateY(-4px);
}
</style>