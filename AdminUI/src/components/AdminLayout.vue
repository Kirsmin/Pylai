<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Component } from 'vue'
import {
  Apps, FileSearch, Gauge, Logout, Menu2, MoonStars,
  ShieldCheck, ShieldLock, Sun, Ticket, Users, X
} from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import MfaStepUpModal from '@/components/MfaStepUpModal.vue'

const authStore = useAuthStore()
const themeStore = useThemeStore()
const route = useRoute()
const router = useRouter()
const sidebarOpen = ref(false)

const icons: Record<string, Component> = {
  users: Users,
  inviteCodes: Ticket,
  bans: ShieldCheck,
  auditLogs: FileSearch,
  clients: Apps
}

const identityKeys = new Set(['users', 'inviteCodes', 'clients'])
const governanceKeys = new Set(['bans', 'auditLogs'])
const identityCapabilities = computed(() => authStore.capabilities.filter((item) => identityKeys.has(item.key)))
const governanceCapabilities = computed(() => authStore.capabilities.filter((item) => governanceKeys.has(item.key)))
const uncategorizedCapabilities = computed(() => authStore.capabilities.filter((item) => !identityKeys.has(item.key) && !governanceKeys.has(item.key)))

const themeIcon = computed(() => themeStore.isDark ? MoonStars : Sun)
const avatarLetter = computed(() => {
  const name = authStore.displayName || authStore.group || '?'
  return name.trim().charAt(0) || '?'
})
const headerTitle = computed(() => String(route.meta.pageTitle || '概览'))
const appVersion = __APP_VERSION__

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path === path || route.path.startsWith(`${path}/`)
}

function navTo(path: string) {
  sidebarOpen.value = false
  void router.push(path)
}
</script>

<template>
  <div class="admin-shell">
    <aside :class="['admin-sidebar', { open: sidebarOpen }]">
      <button type="button" class="sidebar-brand" aria-label="返回管理概览" @click="navTo('/')">
        <span class="brand-mark">P</span>
        <span class="brand-copy">
          <span class="brand-name">Pylai Admin</span>
          <span class="brand-subtitle">ADMIN CONSOLE</span>
        </span>
      </button>

      <nav class="sidebar-nav" aria-label="管理导航">
        <span class="nav-section-label">工作台</span>
        <button type="button" :class="['nav-item', { active: isActive('/') }]" @click="navTo('/')">
          <span class="nav-icon"><NIcon :component="Gauge" /></span>
          <span>概览</span>
        </button>

        <template v-if="identityCapabilities.length">
          <span class="nav-section-label nav-section-spaced">身份与接入</span>
          <button
            v-for="item in identityCapabilities"
            :key="item.key"
            type="button"
            :class="['nav-item', { active: isActive(item.route) }]"
            @click="navTo(item.route)"
          >
            <span class="nav-icon"><NIcon :component="icons[item.key]" /></span>
            <span class="truncate">{{ item.key === 'clients' ? 'OAuth2 客户端' : item.name }}</span>
          </button>
        </template>

        <template v-if="governanceCapabilities.length || uncategorizedCapabilities.length">
          <span class="nav-section-label nav-section-spaced">安全与治理</span>
          <button
            v-for="item in [...governanceCapabilities, ...uncategorizedCapabilities]"
            :key="item.key"
            type="button"
            :class="['nav-item', { active: isActive(item.route) }]"
            @click="navTo(item.route)"
          >
            <span class="nav-icon"><NIcon :component="icons[item.key] || ShieldCheck" /></span>
            <span class="truncate">{{ item.name }}</span>
          </button>
        </template>

        <span class="nav-section-label nav-section-spaced">当前账户</span>
        <button type="button" :class="['nav-item', { active: isActive('/security') }]" @click="navTo('/security')">
          <span class="nav-icon"><NIcon :component="ShieldLock" /></span>
          <span>账户安全</span>
        </button>
      </nav>

      <div class="sidebar-footer">
        <div class="user-card">
          <span class="user-avatar">{{ avatarLetter }}</span>
          <div class="user-meta">
            <span class="user-name truncate">{{ authStore.displayName || authStore.user?.name || '管理员' }}</span>
            <span class="user-group truncate">{{ authStore.group || 'admin' }}</span>
          </div>
        </div>
        <div class="footer-row">
          <span class="footer-version">v{{ appVersion }}</span>
          <div class="footer-actions">
            <button class="icon-btn" type="button" title="切换主题" @click="themeStore.toggle()">
              <NIcon :component="themeIcon" />
            </button>
            <button class="icon-btn" type="button" title="退出登录" @click="authStore.logout()">
              <NIcon :component="Logout" />
            </button>
          </div>
        </div>
      </div>
    </aside>

    <div class="admin-main">
      <header class="admin-header">
        <div class="header-left">
          <button class="icon-btn mobile-menu-btn" type="button" title="打开导航" @click="sidebarOpen = !sidebarOpen">
            <NIcon :component="sidebarOpen ? X : Menu2" />
          </button>
          <h1 class="header-title">{{ headerTitle }}</h1>
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
    <MfaStepUpModal />
  </div>
</template>
