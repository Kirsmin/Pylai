<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { Component } from 'vue'
import { Apps, FileSearch, ShieldCheck, Ticket, Users } from '@vicons/tabler'
import { useAuthStore } from '@/stores/auth'
import AppBadge from '@/components/AppBadge.vue'
import PageHeader from '@/components/PageHeader.vue'

const authStore = useAuthStore()
const router = useRouter()

const icons: Record<string, Component> = {
  users: Users,
  inviteCodes: Ticket,
  bans: ShieldCheck,
  auditLogs: FileSearch,
  clients: Apps
}

const cards = computed(() => authStore.capabilities)
const inviteCapability = computed(() => authStore.hasCapability('inviteCodes'))

function groupTone(g: string) {
  if (g === 'normal') return 'success'
  if (g === 'admin') return 'info'
  if (g === 'max') return 'purple'
  return 'neutral'
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="管理概览" subtitle="集中查看当前权限和常用管理入口。">
      <template #actions>
        <AppBadge :tone="groupTone(authStore.group)">{{ authStore.group }}</AppBadge>
      </template>
    </PageHeader>

    <div class="overview-grid">
      <div class="overview-cell">
        <span class="overview-label">当前管理员</span>
        <strong class="overview-value truncate">{{ authStore.displayName }}</strong>
      </div>
      <div class="overview-cell">
        <span class="overview-label">权限组</span>
        <strong class="overview-value mono">{{ authStore.group }}</strong>
      </div>
      <div class="overview-cell">
        <span class="overview-label">可用模块</span>
        <strong class="overview-value">{{ cards.length }}</strong>
      </div>
      <div v-if="inviteCapability" class="overview-cell">
        <span class="overview-label">注册策略</span>
        <strong class="overview-value">{{ authStore.inviteCodeRequired ? '必须邀请码' : '邀请码可选' }}</strong>
      </div>
    </div>

    <div class="admin-panel">
      <div class="admin-panel-header">
        <div>
          <h3 class="admin-panel-title">管理模块</h3>
          <p class="admin-panel-subtitle">入口来自后端 capability 返回值；未授权功能不会展示。</p>
        </div>
      </div>
      <div v-if="cards.length" class="module-list">
        <button
          v-for="item in cards"
          :key="item.key"
          type="button"
          class="module-row"
          @click="router.push(item.route)"
        >
          <span class="module-icon"><NIcon :component="icons[item.key]" /></span>
          <span class="module-copy">
            <strong>{{ item.name }}</strong>
            <span>{{ item.description }}</span>
          </span>
          <span class="module-enter">进入</span>
        </button>
      </div>
      <div v-else class="admin-empty">
        <NEmpty description="当前用户组没有可用的管理功能" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.overview-cell {
  min-width: 0;
  padding: 15px 17px;
  border-right: 1px solid var(--border);
}
.overview-cell:last-child { border-right: 0; }
.overview-label {
  display: block;
  margin-bottom: 5px;
  font-size: 11px;
  font-weight: 650;
  color: var(--text-tertiary);
}
.overview-value {
  display: block;
  font-size: 15px;
  font-weight: 650;
  color: var(--text-primary);
}
.module-list { display: flex; flex-direction: column; }
.module-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 18px;
  border: 0;
  border-bottom: 1px solid var(--divider);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.module-row:last-child { border-bottom: 0; }
.module-row:hover { background: var(--surface-hover); }
.module-icon {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-size: 17px;
  background: var(--surface-sunken);
}
.module-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 1px; }
.module-copy strong { font-size: 13px; font-weight: 650; color: var(--text-primary); }
.module-copy span { font-size: 12px; color: var(--text-tertiary); }
.module-enter { flex-shrink: 0; font-size: 12px; color: var(--accent); }
@media (max-width: 720px) {
  .overview-grid { grid-template-columns: 1fr 1fr; }
  .overview-cell:nth-child(2n) { border-right: 0; }
  .overview-cell { border-bottom: 1px solid var(--border); }
  .overview-cell:nth-last-child(-n + 2) { border-bottom: 0; }
}
@media (max-width: 480px) {
  .overview-grid { grid-template-columns: 1fr; }
  .overview-cell { border-right: 0; border-bottom: 1px solid var(--border); }
  .overview-cell:last-child { border-bottom: 0; }
}
</style>
