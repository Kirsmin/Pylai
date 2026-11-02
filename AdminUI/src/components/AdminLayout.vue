<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { Component } from 'vue'
import { useMessage } from 'naive-ui'
import {
  Apps, CaretDown, ChevronLeft, ChevronRight, FileSearch, Gauge,
  Logout, Menu2, MoonStars, QuestionMark, Search, ShieldCheck,
  ShieldLock, Sun, Ticket, Users, X
} from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import MfaStepUpModal from '@/components/MfaStepUpModal.vue'

const authStore = useAuthStore()
const themeStore = useThemeStore()
const route = useRoute()
const router = useRouter()
const message = useMessage()

/* ── 导航模型（与 capability 分组一致） ─────────────────────── */
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

const navGroups = computed(() => [
  { key: 'workspace', label: '工作台', items: [{ key: 'home', name: '概览', route: '/' }] },
  {
    key: 'identity',
    label: '身份与接入',
    items: identityCapabilities.value.map((item) => ({
      key: item.key,
      name: item.key === 'clients' ? 'OAuth2 客户端' : item.name,
      route: item.route
    }))
  },
  {
    key: 'governance',
    label: '安全与治理',
    items: [...governanceCapabilities.value, ...uncategorizedCapabilities.value].map((item) => ({
      key: item.key,
      name: item.name,
      route: item.route
    }))
  },
  { key: 'account', label: '当前账户', items: [{ key: 'security', name: '账户安全', route: '/security' }] }
].filter((group) => group.items.length > 0))

const flatNavItems = computed(() =>
  navGroups.value.flatMap((group) =>
    group.items.map((item) => ({ label: item.name, value: item.route, group: group.label }))
  )
)

function isActive(path: string): boolean {
  if (path === '/') return route.path === '/'
  return route.path === path || route.path.startsWith(`${path}/`)
}

function navTo(path: string) {
  closeDrawer()
  searchText.value = ''
  void router.push(path)
}

/* ── 侧栏折叠（桌面） ────────────────────────────────────── */
const COLLAPSE_STORAGE_KEY = 'admin.sidebarCollapsed'
const collapsed = ref(localStorage.getItem(COLLAPSE_STORAGE_KEY) === '1')
function toggleCollapse() {
  collapsed.value = !collapsed.value
  localStorage.setItem(COLLAPSE_STORAGE_KEY, collapsed.value ? '1' : '0')
}

/* ── 面包屑 / 标题 ───────────────────────────────────────── */
const breadcrumbItems = computed(() => [
  { title: '管理台' },
  { title: String(route.meta.pageTitle || '概览') }
])

/* ── 全局搜索（页面快速跳转） ─────────────────────────────── */
const searchText = ref('')
const searchOptions = computed(() => {
  const query = searchText.value.trim()
  if (!query) return []
  return flatNavItems.value
    .filter((item) => item.label.toLowerCase().includes(query.toLowerCase()))
    .map((item) => ({ label: `${item.group} / ${item.label}`, value: item.value }))
})
function onSearchSelect(value: string) {
  navTo(value)
}

/* ── 用户菜单 ────────────────────────────────────────────── */
const themeIcon = computed(() => (themeStore.isDark ? Sun : MoonStars))
const avatarLetter = computed(() => {
  const name = authStore.displayName || authStore.group || '?'
  return name.trim().charAt(0) || '?'
})
const userMenuOptions = computed(() => [
  { label: '账户安全', key: 'security' },
  { label: themeStore.isDark ? '切换为浅色' : '切换为深色', key: 'theme' },
  { type: 'divider' as const, key: 'divider' },
  { label: '退出登录', key: 'logout' }
])
async function onUserMenuSelect(key: string) {
  if (key === 'security') {
    navTo('/security')
  } else if (key === 'theme') {
    themeStore.toggle()
  } else if (key === 'logout') {
    try {
      await authStore.logout()
    } catch {
      message.error('登出失败，请重试')
    }
  }
}

const appVersion = __APP_VERSION__

/* ── 移动端 Drawer（真正的对话框语义 + 焦点圈定） ─────────────── */
const MOBILE_MEDIA = '(max-width: 768px)'
const isMobile = ref(window.matchMedia(MOBILE_MEDIA).matches)
const drawerOpen = ref(false)
const asideRef = ref<HTMLElement | null>(null)
let lastTrigger: HTMLElement | null = null
let mediaQuery: MediaQueryList | null = null

function onMediaChange(event: MediaQueryListEvent) {
  isMobile.value = event.matches
  if (!event.matches) closeDrawer()
}

function openDrawer(event: MouseEvent) {
  if (!isMobile.value) return
  lastTrigger = (event.currentTarget as HTMLElement) || null
  drawerOpen.value = true
}

function closeDrawer() {
  if (!drawerOpen.value) return
  drawerOpen.value = false
}

/* 打开后焦点移入 Drawer，关闭后还原到触发按钮 */
watch(drawerOpen, async (open) => {
  document.documentElement.style.overflow = open ? 'hidden' : ''
  document.body.style.paddingRight = ''
  if (open) {
    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth
    if (scrollbarWidth > 0) document.body.style.paddingRight = `${scrollbarWidth}px`
    await nextTick()
    const closeButton = asideRef.value?.querySelector<HTMLElement>('.drawer-close')
    closeButton?.focus()
  } else {
    await nextTick()
    lastTrigger?.focus()
    lastTrigger = null
  }
})

/* 焦点圈定 + Esc 关闭（Tab 在 Drawer 内循环） */
function onAsideKeydown(event: KeyboardEvent) {
  if (!isMobile.value || !drawerOpen.value) return
  if (event.key === 'Escape') {
    event.stopPropagation()
    closeDrawer()
    return
  }
  if (event.key !== 'Tab' || !asideRef.value) return
  const focusables = Array.from(
    asideRef.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
    )
  ).filter((el) => el.offsetParent !== null)
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (!first || !last) return
  const active = document.activeElement
  if (event.shiftKey && (active === first || !asideRef.value.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => {
  mediaQuery = window.matchMedia(MOBILE_MEDIA)
  mediaQuery.addEventListener('change', onMediaChange)
})
onBeforeUnmount(() => {
  mediaQuery?.removeEventListener('change', onMediaChange)
  document.documentElement.style.overflow = ''
  document.body.style.paddingRight = ''
})
</script>

<template>
  <div :class="['admin-shell', { collapsed }]">
    <aside
      ref="asideRef"
      id="admin-sidebar"
      :class="['admin-sidebar', { open: drawerOpen }]"
      :role="isMobile ? 'dialog' : 'navigation'"
      :aria-modal="isMobile ? 'true' : undefined"
      :aria-label="isMobile ? '管理导航' : undefined"
      @keydown="onAsideKeydown"
    >
      <div class="sidebar-brand">
        <button type="button" class="sidebar-brand-main" aria-label="返回管理概览" @click="navTo('/')">
          <span class="brand-mark">P</span>
          <span class="brand-copy">
            <span class="brand-name">Pylai Admin</span>
            <span class="brand-subtitle">ADMIN CONSOLE</span>
          </span>
        </button>
        <button v-if="isMobile" type="button" class="icon-btn drawer-close" aria-label="关闭导航" @click="closeDrawer">
          <NIcon :component="X" />
        </button>
      </div>

      <nav class="sidebar-nav" aria-label="管理导航">
        <template v-for="group in navGroups" :key="group.key">
          <span class="nav-section-label" :class="{ 'nav-section-spaced': group.key !== 'workspace' }">{{ group.label }}</span>
          <button
            v-for="item in group.items"
            :key="item.key"
            type="button"
            :class="['nav-item', { active: isActive(item.route) }]"
            :title="collapsed && !isMobile ? item.name : undefined"
            @click="navTo(item.route)"
          >
            <span class="nav-icon"><NIcon :component="icons[item.key] || (item.key === 'home' ? Gauge : item.key === 'security' ? ShieldLock : ShieldCheck)" /></span>
            <span class="nav-label truncate">{{ item.name }}</span>
          </button>
        </template>
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
            <button
              v-if="!isMobile"
              class="icon-btn"
              type="button"
              :title="collapsed ? '展开侧栏' : '折叠侧栏'"
              :aria-label="collapsed ? '展开侧栏' : '折叠侧栏'"
              @click="toggleCollapse"
            >
              <NIcon :component="collapsed ? ChevronRight : ChevronLeft" />
            </button>
            <button class="icon-btn" type="button" title="切换主题" @click="themeStore.toggle()">
              <NIcon :component="themeIcon" />
            </button>
            <button class="icon-btn" type="button" title="退出登录" @click="onUserMenuSelect('logout')">
              <NIcon :component="Logout" />
            </button>
          </div>
        </div>
      </div>
    </aside>

    <div class="admin-main">
      <header class="admin-header">
        <div class="header-left">
          <button
            class="icon-btn mobile-menu-btn"
            type="button"
            title="打开导航"
            aria-label="打开导航"
            aria-controls="admin-sidebar"
            :aria-expanded="drawerOpen"
            @click="openDrawer"
          >
            <NIcon :component="Menu2" />
          </button>
          <NBreadcrumb class="header-breadcrumb">
            <NBreadcrumbItem v-for="(item, index) in breadcrumbItems" :key="index">{{ item.title }}</NBreadcrumbItem>
          </NBreadcrumb>
        </div>
        <div class="header-actions">
          <NAutoComplete
            v-model:value="searchText"
            class="header-search"
            :options="searchOptions"
            :input-props="{ 'aria-label': '全局搜索页面' }"
            placeholder="搜索页面"
            clearable
            @select="onSearchSelect"
          >
            <template #prefix>
              <NIcon :component="Search" />
            </template>
          </NAutoComplete>

          <NPopover placement="bottom-end" trigger="click">
            <template #trigger>
              <button class="icon-btn" type="button" title="帮助" aria-label="帮助">
                <NIcon :component="QuestionMark" />
              </button>
            </template>
            <div class="help-popover">
              <p class="help-title">需要帮助？</p>
              <p class="help-line">查看安装与运维文档，或到项目仓库提交 Issue。</p>
              <div class="help-links">
                <a href="https://github.com/Kirsmin/Pylai/blob/main/Docs/Installation.md" target="_blank" rel="noopener">安装文档</a>
                <a href="https://github.com/Kirsmin/Pylai" target="_blank" rel="noopener">项目仓库</a>
              </div>
              <p class="help-version mono">Pylai Admin v{{ appVersion }}</p>
            </div>
          </NPopover>

          <NDropdown :options="userMenuOptions" placement="bottom-end" @select="onUserMenuSelect">
            <button class="user-menu-trigger" type="button" aria-label="用户菜单">
              <span class="user-avatar">{{ avatarLetter }}</span>
              <span class="user-menu-name truncate">{{ authStore.displayName || '管理员' }}</span>
              <NIcon class="user-menu-caret" :component="CaretDown" />
            </button>
          </NDropdown>
        </div>
      </header>
      <main class="admin-content">
        <slot />
      </main>
    </div>

    <div v-if="drawerOpen && isMobile" class="mobile-overlay" @click="closeDrawer" />
    <MfaStepUpModal />
  </div>
</template>
