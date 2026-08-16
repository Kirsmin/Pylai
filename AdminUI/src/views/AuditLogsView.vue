<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import { utc8ToIso } from '@/utils/time'
import type { AdminAuditLogItem } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()

const logs = ref<AdminAuditLogItem[]>([])
const total = ref(0)
const loading = ref(false)
const eventType = ref('')
const userId = ref('')
const ip = ref('')
const success = ref<string | null>(null)
const from = ref('')
const to = ref('')
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('auditLogs'))

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      skip: String((page.value - 1) * pageSize),
      take: String(pageSize)
    })
    if (eventType.value.trim()) params.set('eventType', eventType.value.trim())
    if (userId.value.trim()) params.set('userId', userId.value.trim())
    if (ip.value.trim()) params.set('ip', ip.value.trim())
    if (success.value !== null) params.set('success', success.value)

    // datetime-local 按页面口径解释为 UTC+8，再转 UTC 发送
    const fromIso = utc8ToIso(from.value)
    const toIso = utc8ToIso(to.value)
    if (fromIso) params.set('from', fromIso)
    if (toIso) params.set('to', toIso)

    const data = await authStore.request<{ success: boolean; total: number; logs: AdminAuditLogItem[] }>(
      `/api/admin/audit-logs?${params.toString()}`
    )
    logs.value = data?.logs ?? []
    total.value = data?.total ?? 0
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载审计日志失败')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function resetFilters() {
  eventType.value = ''
  userId.value = ''
  ip.value = ''
  success.value = null
  from.value = ''
  to.value = ''
  page.value = 1
  load()
}

onMounted(load)
</script>

<template>
  <section class="admin-page">
    <PageHeader title="审计日志" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
      </template>
    </PageHeader>

    <div class="admin-toolbar">
      <NInput v-model:value="eventType" class="tool-input" placeholder="EventType" clearable @keyup.enter="search" />
      <NInput v-model:value="userId" class="tool-input" placeholder="UserId / UID" clearable @keyup.enter="search" />
      <NInput v-model:value="ip" class="tool-ip" placeholder="IP" clearable @keyup.enter="search" />
      <NSelect
        v-model:value="success"
        class="tool-select"
        placeholder="成功 / 失败"
        clearable
        :options="[
          { label: '成功', value: 'true' },
          { label: '失败', value: 'false' }
        ]"
      />
      <label class="date-field">
        <span>从（UTC+8）</span>
        <input v-model="from" type="datetime-local" class="admin-input date-input" />
      </label>
      <label class="date-field">
        <span>到（UTC+8）</span>
        <input v-model="to" type="datetime-local" class="admin-input date-input" />
      </label>
      <NButton type="success" ghost @click="search">查询</NButton>
      <NButton quaternary @click="resetFilters">重置</NButton>
    </div>

    <div class="admin-table-card">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="logs.length > 0">
        <div class="admin-stack">
          <div v-for="log in logs" :key="log.id" class="log-card" :class="log.success ? 'is-success' : 'is-failure'">
            <div class="log-head">
              <AppBadge :tone="log.success ? 'success' : 'danger'">{{ log.success ? '成功' : '失败' }}</AppBadge>
              <strong class="mono">{{ log.eventType }}</strong>
              <span class="mono muted">#{{ log.id }}</span>
            </div>
            <p class="mono muted endpoint">{{ log.method }} {{ log.endpoint }}</p>
            <p class="muted"><DateTimeText :value="log.timestamp" /> · IP {{ log.ipAddress || '未知' }} · {{ log.userEmail || log.userId || '匿名' }}</p>
            <p v-if="log.details" class="details">{{ log.details }}</p>
          </div>
        </div>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" @update:page="load" />
      </template>
      <NEmpty v-else description="没有审计日志" class="admin-empty" />
    </div>
  </section>
</template>

<style scoped>
.tool-input {
  width: min(220px, 100%);
}

.tool-ip {
  width: 140px;
}

.tool-select {
  width: 130px;
}

.date-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: 12px;
}

.date-input {
  width: 190px;
  padding: 7px 8px;
  color-scheme: light dark;
}

.log-card {
  border: 1px dashed var(--success-color-soft);
  border-left-width: 3px;
  border-left-style: solid;
  border-radius: var(--admin-radius-sm);
  padding: 12px;
  background: var(--card-bg-solid);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  transition: border-color 0.2s ease, background 0.2s ease;
}

.log-card.is-success {
  border-color: var(--success-color-soft);
  border-left-color: var(--success-color);
}

.log-card.is-failure {
  border-color: var(--danger-border);
  border-left-color: var(--text-danger);
  background: var(--danger-soft);
}

.log-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 13px;
}

.endpoint {
  margin: 8px 0 4px;
  word-break: break-all;
}

.muted {
  margin: 0;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.6;
  word-break: break-all;
}

.details {
  margin: 8px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
  word-break: break-all;
}

.mono {
  font-family: var(--font-family-mono);
}
</style>
