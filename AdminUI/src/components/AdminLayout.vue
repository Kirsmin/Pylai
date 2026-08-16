<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Component } from 'vue'
import { Apps, FileSearch, Logout, MoonStars, ShieldCheck, Sun, Ticket, Users } from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

const authStore = useAuthStore()
const themeStore = useThemeStore()
const route = useRoute()
const router = useRouter()

const icons: Record<string, Component> = {
  users: Users,
  inviteCodes: Ticket,
  bans: ShieldCheck,
  auditLogs: FileSearch,
  clients: Apps
}

const themeIcon = computed(() => (themeStore.isDark ? MoonStars : Sun))
const themeIconClass = computed(() => (themeStore.isDark ? 'theme-icon-moon' : 'theme-icon-sun'))
const navItems = computed(() => authStore.capabilities)

function isActive(routePath: string): boolean {
  return route.path === routePath || route.path.startsWith(`${routePath}/`)
}

function groupTone(group: string): 'success' | 'info' | 'purple' | 'neutral' {
  if (group === 'normal') return 'success'
  if (group === 'admin') return 'info'
  if (group === 'max') return 'purple'
  return 'neutral'
}
</script>

<template>
  <div class="admin-shell">
    <header class="admin-dock">
      <div class="dock-brand" @click="router.push('/')">
        <span class="brand-mark"># Pylai</span>
        <span class="brand-divider">/</span>
        <span class="brand-manage">管理台</span>
      </div>

      <div class="dock-spacer">
        <span class="dock-user" :title="authStore.user?.name || ''">{{ authStore.displayName }}</span>
        <span class="app-badge group-badge" :class="`tone-${groupTone(authStore.group)}`">
          <i class="app-badge-dot" />
          {{ authStore.group || 'unknown' }}
        </span>
      </div>

      <button class="dock-icon" type="button" title="切换主题" @click="themeStore.toggle()">
        <NIcon :class="['theme-icon', themeIconClass]" :component="themeIcon" />
      </button>
      <button class="dock-icon" type="button" title="退出登录" @click="authStore.logout()">
        <NIcon :component="Logout" />
      </button>
    </header>

    <div class="admin-body">
      <aside v-if="navItems.length > 0" class="side-card">
        <nav class="side-nav">
          <button
            v-for="item in navItems"
            :key="item.key"
            type="button"
            class="nav-item"
            :class="{ active: isActive(item.route) }"
            @click="router.push(item.route)"
          >
            <span class="nav-icon"><NIcon :component="icons[item.key]" /></span>
            <span class="nav-copy">
              <span class="nav-text">{{ item.name }}</span>
              <span class="nav-desc">{{ item.description }}</span>
            </span>
          </button>
        </nav>
      </aside>

      <main class="content-card">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.admin-shell {
  min-height: 100vh;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: var(--admin-gap);
  background: var(--page-bg);
  box-sizing: border-box;
}

.admin-dock {
  width: 100%;
  max-width: var(--admin-shell-max);
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 16px;
  background: var(--card-bg);
  backdrop-filter: blur(24px) saturate(1.1);
  -webkit-backdrop-filter: blur(24px) saturate(1.1);
  border: 1px solid var(--card-border);
  box-shadow: var(--card-shadow);
  box-sizing: border-box;
}

.dock-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 10px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background 0.2s ease, color 0.2s ease;
  user-select: none;
}

.dock-brand:hover {
  background: var(--dock-item-hover);
  color: var(--text-primary);
}

.brand-mark {
  font-family: var(--font-family-mono);
  font-weight: 700;
  font-size: 16px;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.brand-divider {
  color: var(--text-tertiary);
  font-family: var(--font-family-mono);
}

.brand-manage {
  font-size: 14px;
  font-weight: 600;
}

.dock-spacer {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  overflow: hidden;
  font-size: 14px;
  font-weight: 500;
}

.dock-user {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
}

.group-badge {
  padding: 2px 10px;
  font-family: var(--font-family-mono);
  font-size: 12px;
  font-weight: 700;
}

.dock-icon {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 20px;
  transition: background 0.2s ease, color 0.2s ease;
}

.dock-icon:hover {
  background: var(--dock-item-hover);
  color: var(--text-primary);
}

.theme-icon {
  font-size: 20px;
  transition: transform 0.2s ease, color 0.2s ease;
}

.theme-icon-sun {
  color: #fbbf24;
}

.theme-icon-moon {
  color: #93c5fd;
}

.admin-body {
  flex: 1;
  width: 100%;
  max-width: var(--admin-shell-max);
  margin: 0 auto;
  display: flex;
  align-items: flex-start;
  gap: var(--admin-gap);
  min-height: 0;
}

.side-card,
.content-card {
  border-radius: var(--admin-radius-md);
  background: var(--card-bg);
  backdrop-filter: blur(24px) saturate(1.1);
  -webkit-backdrop-filter: blur(24px) saturate(1.1);
  border: 1px solid var(--card-border);
  box-shadow: var(--card-shadow);
  box-sizing: border-box;
}

.side-card {
  flex: 0 0 var(--admin-side-width);
  padding: 10px;
  position: sticky;
  top: 12px;
}

.side-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  text-align: left;
  transition: background 0.2s ease, color 0.2s ease;
}

.nav-item:hover {
  background: var(--dock-item-hover);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--success-color-soft);
  color: var(--success-color);
}

.nav-icon {
  display: inline-flex;
  flex: 0 0 auto;
  font-size: 18px;
}

.nav-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-text {
  font-size: 14px;
  font-weight: 600;
}

.nav-desc {
  font-size: 11px;
  line-height: 1.4;
  opacity: 0.72;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}

.content-card {
  flex: 1;
  min-width: 0;
  padding: var(--admin-content-padding);
}

@media (max-width: 860px) {
  .admin-shell {
    padding: 10px;
  }

  .admin-body {
    flex-direction: column;
  }

  .side-card {
    position: static;
    width: 100%;
  }

  .side-nav {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .nav-item {
    width: auto;
    min-width: 150px;
    white-space: nowrap;
  }

  .nav-desc {
    display: none;
  }

  .dock-user {
    max-width: 120px;
  }
}
</style>
