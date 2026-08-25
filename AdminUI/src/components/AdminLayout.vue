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

const avatarLetter = computed(() => {
  const name = authStore.displayName || authStore.group || '?'
  return name.trim().charAt(0) || '?'
})

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
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
        <span class="brand-mark">#</span>
        <span class="brand-name">Pylai</span>
        <span class="brand-tag">ADMIN</span>
      </div>

      <nav class="sidebar-nav">
        <span class="nav-section-label">管理功能</span>
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
        <div class="user-card">
          <span class="user-avatar">{{ avatarLetter }}</span>
          <div class="user-meta">
            <span class="user-name truncate">{{ authStore.displayName }}</span>
            <span class="user-group" :style="{ color: `var(--${groupTone(authStore.group)})` }">
              {{ authStore.group }}
            </span>
          </div>
        </div>
        <div class="footer-actions">
          <button class="icon-btn" title="切换主题" @click="themeStore.toggle()">
            <NIcon :component="themeIcon" />
          </button>
          <button class="icon-btn" title="MFA 设置" @click="mfaSettingsRef?.open()">
            <NIcon :component="ShieldLock" />
          </button>
          <button class="icon-btn" title="退出登录" @click="authStore.logout()">
            <NIcon :component="Logout" />
          </button>
        </div>
      </div>
    </aside>

    <div class="admin-main">
      <header class="admin-header">
        <div class="header-left">
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
