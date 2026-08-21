<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import type { AdminAuditLogItem } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()

const logs = ref<AdminAuditLogItem[]>([])
const total = ref(0)
const loading = ref(false)
const eventType = ref('')
const userId = ref('')
const ip = ref('')
const success = ref<boolean | null>(null)
const fromDate = ref<string | null>(null)
const toDate = ref<string | null>(null)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('auditLogs'))

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({ skip: String((page.value - 1) * pageSize), take: String(pageSize) })
    if (eventType.value.trim()) params.set('eventType', eventType.value.trim())
    if (userId.value.trim()) params.set('userId', userId.value.trim())
    if (ip.value.trim()) params.set('ip', ip.value.trim())
    if (success.value !== null) params.set('success', String(success.value))
    if (fromDate.value) params.set('from', fromDate.value)
    if (toDate.value) params.set('to', toDate.value)
    const data = await authStore.request<{ total: number; logs: AdminAuditLogItem[] }>(
      `/api/admin/audit-logs?${params.toString()}`
    )
    logs.value = data?.logs ?? []
    total.value = data?.total ?? 0
  } catch (err) { message.error(err instanceof Error ? err.message : '加载失败') }
  finally { loading.value = false }
}
function search() { page.value = 1; load() }
function resetFilters() {
  eventType.value = ''; userId.value = ''; ip.value = ''; success.value = null
  fromDate.value = null; toDate.value = null; page.value = 1; load()
}
onMounted(load)

function eventTone(t: string): 'success' | 'info' | 'warning' | 'danger' | 'purple' | 'neutral' {
  if (t.includes('Failure') || t.includes('Failed')) return 'danger'
  if (t.includes('Created') || t.includes('Granted') || t.includes('Succeeded')) return 'success'
  if (t.includes('Deleted') || t.includes('Revoked')) return 'warning'
  return 'neutral'
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="审计日志" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
      </template>
    </PageHeader>

    <div class="admin-toolbar" style="gap:8px;">
      <input v-model="eventType" class="admin-input" placeholder="事件类型" style="width:160px" @keyup.enter="search" />
      <input v-model="userId" class="admin-input" placeholder="用户ID" style="width:160px" @keyup.enter="search" />
      <input v-model="ip" class="admin-input" placeholder="IP" style="width:140px" @keyup.enter="search" />
      <NSelect v-model:value="success" placeholder="结果" clearable :options="[{label:'成功',value:true},{label:'失败',value:false}]" style="width:110px" @update:value="search" />
      <NButton type="success" ghost @click="search">查询</NButton>
      <NButton quaternary @click="resetFilters">重置</NButton>
    </div>

    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="logs.length">
        <table class="admin-table">
          <thead>
            <tr>
              <th>ID</th><th>事件</th><th>用户</th><th>端点</th><th>IP</th><th>结果</th><th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log.id">
              <td class="mono small muted">#{{ log.id }}</td>
              <td><AppBadge :tone="eventTone(log.eventType)">{{ log.eventType }}</AppBadge></td>
              <td>
                <div style="display:flex;flex-direction:column;gap:2px;">
                  <span class="small">{{ log.userEmail || '—' }}</span>
                  <span v-if="log.userId" class="mono small muted">{{ log.userId }}</span>
                </div>
              </td>
              <td>
                <div style="display:flex;flex-direction:column;gap:2px;">
                  <span class="small mono">{{ log.method }} {{ log.endpoint }}</span>
                  <span v-if="log.details" class="small muted" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ log.details }}</span>
                </div>
              </td>
              <td class="mono small muted">{{ log.ipAddress || '—' }}</td>
              <td><AppBadge :tone="log.success?'success':'danger'">{{ log.success?'成功':'失败' }}</AppBadge></td>
              <td><DateTimeText :value="log.timestamp" /></td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" @update:page="load" />
      </template>
      <NEmpty v-else description="没有审计记录" class="admin-empty" />
    </div>
  </section>
</template>
