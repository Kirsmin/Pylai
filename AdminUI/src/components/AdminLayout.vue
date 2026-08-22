<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Component } from 'vue'
import {
  Apps, FileSearch, Logout, Menu2, MoonStars,
  ShieldCheck, ShieldLock, Sun, Ticket, Users, X
} from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import MfaSettingsModal from '@/components/MfaSettingsModal.vue'
import MfaStepUpModal from '@/components/MfaStepUpModal.vue'

const authStore = useAuthStore()
const themeStore = useThemeStore()
const route = useRoute()
const router = useRouter()
const mfaSettingsRef = ref<InstanceType<typeof MfaSettingsModal> | null>(null)
const sidebarOpen = ref(false)

const icons: Record<string, Component> = {
  users: Users,
  inviteCodes: Ticket,
  bans: ShieldCheck,
  auditLogs: FileSearch,
  clients: Apps
}

const themeIcon = computed(() => themeStore.isDark ? MoonStars : Sun)

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(`${path}/`)
}

function navTo(path: string) {
  sidebarOpen.value = false
  router.push(path)
}

function groupTone(group: string): string {
  if (group === 'normal') return 'success'
  if (group === 'admin') return 'info'
  if (group === 'max') return 'purple'
  return 'neutral'
}
</script>

<template>
  <div class="admin-shell">
    <aside :class="['admin-sidebar', { open: sidebarOpen }]">
      <div class="sidebar-brand" @click="navTo('/')">
        <span># Pylai</span>
      </div>

      <nav class="sidebar-nav">
        <button
          v-for="item in authStore.capabilities"
          :key="item.key"
          type="button"
          :class="['nav-item', 'animate-slide', { active: isActive(item.route) }]"
          :style="{ animationDelay: `${Math.min(authStore.capabilities.indexOf(item) * 40, 300)}ms` }"
          @click="navTo(item.route)"
        >
          <span class="nav-icon"><NIcon :component="icons[item.key]" /></span>
          <span class="truncate">{{ item.name }}</span>
        </button>
      </nav>

      <div class="sidebar-footer">
        <div class="user-pill">
          <span class="truncate" style="flex:1">{{ authStore.displayName }}</span>
          <span
            class="mono"
            style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;"
            :style="{
              background: `var(--${groupTone(authStore.group)}-soft)`,
              color: `var(--${groupTone(authStore.group)})`
            }"
          >{{ authStore.group }}</span>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="icon-btn" title="切换主题" @click="themeStore.toggle()">
            <NIcon :component="themeIcon" />
          </button>
          <button class="icon-btn" title="MFA 设置" @click="mfaSettingsRef?.open()">
            <NIcon :component="ShieldLock" />
          </button>
          <button class="icon-btn" title="退出" @click="authStore.logout()">
            <NIcon :component="Logout" />
          </button>
        </div>
      </div>
    </aside>

    <div class="admin-main">
      <header class="admin-header">
        <div style="display:flex;align-items:center;gap:10px;">
          <button class="icon-btn mobile-menu-btn" @click="sidebarOpen = !sidebarOpen">
            <NIcon :component="sidebarOpen ? X : Menu2" />
          </button>
          <h1 class="header-title">{{ route.meta.title as string || 'Pylai' }}</h1>
        </div>
        <div class="header-actions">
          <slot name="actions" />
        </div>
      </header>
      <main class="admin-content">
        <slot />
      </main>
    </div>

    <div v-if="sidebarOpen" class="mobile-overlay" @click="sidebarOpen = false" />

    <MfaSettingsModal ref="mfaSettingsRef" />
    <MfaStepUpModal />
  </div>
</template>

<style scoped>
.mobile-overlay {
  position: fixed; inset: 0; z-index: 45;
  background: rgba(0,0,0,0.3);
  backdrop-filter: blur(2px);
}
</style>