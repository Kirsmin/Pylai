<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import type { AdminInviteCode, AdminInviteCodeCreateResponse } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()

const codes = ref<AdminInviteCode[]>([])
const total = ref(0)
const loading = ref(false)
const group = ref<string | null>(null)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('inviteCodes'))
const groupOptions = [
  { label: 'normal', value: 'normal' },
  { label: 'admin', value: 'admin' },
  { label: 'max', value: 'max' }
]

function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}
function groupTone(g: string) {
  if (g.toLowerCase() === 'normal') return 'success'
  if (g.toLowerCase() === 'admin') return 'info'
  if (g.toLowerCase() === 'max') return 'purple'
  return 'neutral'
}
function statusTone(s: string) {
  if (s === 'Active') return 'success'
  if (s === 'Revoked') return 'danger'
  return 'neutral'
}
function progressPercent(c: AdminInviteCode) {
  if (!c.maxRedemptions) return 100
  return Math.min(100, Math.round((c.usedCount / c.maxRedemptions) * 100))
}
function formatDate(v: string) {
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN', { hour12: false })
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({ skip: String((page.value - 1) * pageSize), take: String(pageSize) })
    if (group.value) params.set('group', group.value)
    const data = await authStore.request<{ success: boolean; total: number; codes: AdminInviteCode[] }>(
      `/api/admin/invite-codes?${params.toString()}`
    )
    codes.value = data?.codes ?? []
    total.value = data?.total ?? 0
  } catch (err) { message.error(err instanceof Error ? err.message : '加载失败') }
  finally { loading.value = false }
}
function search() { page.value = 1; load() }
function resetFilters() { group.value = null; page.value = 1; load() }
onMounted(load)

const editorVisible = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const form = ref({ group: 'normal' as string, maxRedemptions: 10, lifetimeHours: 168 })
const createdCode = ref<AdminInviteCodeCreateResponse | null>(null)
const createdVisible = ref(false)

function openCreate() { editingId.value = null; form.value = { group: 'normal', maxRedemptions: 10, lifetimeHours: 168 }; editorVisible.value = true }
function openEdit(code: AdminInviteCode) {
  editingId.value = code.id
  form.value = { group: code.group, maxRedemptions: code.maxRedemptions, lifetimeHours: Math.max(1, Math.round((Date.parse(code.expiresAt) - Date.now()) / 3600000)) }
  editorVisible.value = true
}
async function save() {
  saving.value = true
  try {
    if (editingId.value === null) {
      const data = await authStore.request<AdminInviteCodeCreateResponse>('/api/admin/invite-codes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: form.value.group, maxRedemptions: form.value.maxRedemptions, lifetimeHours: form.value.lifetimeHours })
      })
      createdCode.value = data ?? null
      createdVisible.value = data !== null && data !== undefined
    } else {
      await authStore.request(`/api/admin/invite-codes/${encodeURIComponent(editingId.value)}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ maxRedemptions: form.value.maxRedemptions })
      })
      message.success('邀请码已更新')
    }
    editorVisible.value = false; load()
  } catch (err) { message.error(err instanceof Error ? err.message : '保存失败') }
  finally { saving.value = false }
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AdminInviteCode | null>(null)
async function openDetail(id: string) {
  detailVisible.value = true; detailLoading.value = true; detail.value = null
  try {
    const data = await authStore.request<{ success: boolean; code: AdminInviteCode | null }>(
      `/api/admin/invite-codes/${encodeURIComponent(id)}`
    )
    detail.value = data?.code ?? null
  } catch (err) { message.error(err instanceof Error ? err.message : '加载详情失败'); detailVisible.value = false }
  finally { detailLoading.value = false }
}
async function revoke(id: string) {
  try {
    await authStore.request(`/api/admin/invite-codes/${encodeURIComponent(id)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revoked: true })
    })
    message.success('邀请码已撤销'); if (detailVisible.value) detailVisible.value = false; load()
  } catch (err) { message.error(err instanceof Error ? err.message : '撤销失败') }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="邀请码" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('POST','/api/admin/invite-codes')" type="success" ghost @click="openCreate">创建邀请码</NButton>
      </template>
    </PageHeader>

    <div class="admin-toolbar">
      <NSelect v-model:value="group" placeholder="用户组" clearable :options="groupOptions" style="width:150px" @update:value="search" />
      <NButton type="success" ghost @click="search">查询</NButton>
      <NButton quaternary @click="resetFilters">重置</NButton>
    </div>

    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="codes.length">
        <table class="admin-table">
          <thead>
            <tr><th>邀请码</th><th>用户组</th><th>状态 / 有效期</th><th>已核销 / 上限</th><th style="text-align:right">操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in codes" :key="c.id">
              <td><span class="mono cell-primary">{{ c.prefix }}...</span></td>
              <td><AppBadge :tone="groupTone(c.group)">{{ c.group }}</AppBadge></td>
              <td>
                <div style="display:flex;flex-direction:column;gap:2px;">
                  <AppBadge :tone="statusTone(c.status)">{{ c.status }}</AppBadge>
                  <span class="mono small muted">{{ formatDate(c.expiresAt) }}</span>
                </div>
              </td>
              <td>
                <div style="display:flex;align-items:center;gap:8px;">
                  <span class="mono small muted">{{ c.usedCount }} / {{ c.maxRedemptions }}</span>
                  <div style="flex:1;height:6px;background:var(--surface-active);border-radius:999px;overflow:hidden;">
                    <div :style="{width:`${progressPercent(c)}%`,height:'100%',background:'var(--success)',borderRadius:'inherit',transition:'width 0.3s ease'}" />
                  </div>
                </div>
              </td>
              <td style="text-align:right">
                <div style="display:inline-flex;gap:4px;">
                  <NButton v-if="endpointAllowed('GET','/api/admin/invite-codes/{id}')" size="tiny" quaternary type="success" @click="openDetail(c.id)">详情</NButton>
                  <NButton v-if="endpointAllowed('PATCH','/api/admin/invite-codes/{id}')" size="tiny" quaternary type="success" @click="openEdit(c)">编辑</NButton>
                  <NPopconfirm v-if="endpointAllowed('PATCH','/api/admin/invite-codes/{id}') && c.status==='Active'" @positive-click="revoke(c.id)">
                    <template #trigger><NButton size="tiny" quaternary type="error">撤销</NButton></template>
                    <span style="white-space:nowrap">撤销 {{ c.prefix }}...？</span>
                  </NPopconfirm>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="个" @update:page="load" />
      </template>
      <NEmpty v-else description="没有邀请码" class="admin-empty" />
    </div>

    <NModal v-model:show="editorVisible" preset="card" style="width:min(92%,440px)" :title="editingId===null?'创建邀请码':'编辑邀请码'">
      <div style="display:flex;flex-direction:column;gap:14px;">
        <label>
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:4px;display:block;">用户组</span>
          <NSelect v-model:value="form.group" :options="groupOptions" />
        </label>
        <label>
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:4px;display:block;">最大核销次数</span>
          <input v-model.number="form.maxRedemptions" type="number" min="1" class="admin-input" />
        </label>
        <label v-if="editingId===null">
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:4px;display:block;">有效期（小时）</span>
          <input v-model.number="form.lifetimeHours" type="number" min="1" class="admin-input" />
        </label>
        <div style="display:flex;justify-content:flex-end;">
          <NButton type="success" ghost :loading="saving" @click="save">保存</NButton>
        </div>
      </div>
    </NModal>

    <NModal v-model:show="createdVisible" preset="card" style="width:min(92%,520px)" title="邀请码已创建">
      <div v-if="createdCode" style="display:flex;flex-direction:column;gap:12px;">
        <p class="muted small">请立即保存，此后无法再次查看完整邀请码。</p>
        <div class="mono" style="font-size:18px;word-break:break-all;padding:12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface-active);">
          {{ createdCode.code }}
        </div>
        <div class="muted small">{{ createdCode.group }} · 最大核销 {{ createdCode.maxRedemptions }} 次</div>
        <NButton type="success" ghost @click="createdVisible = false">我已保存</NButton>
      </div>
    </NModal>

    <NModal v-model:show="detailVisible" preset="card" style="width:min(92%,600px)" title="邀请码详情">
      <div v-if="detailLoading" class="admin-empty"><NSpin /></div>
      <template v-else-if="detail">
        <dl class="admin-detail-grid">
          <div><dt>邀请码</dt><dd class="mono">{{ detail.prefix }}...</dd></div>
          <div><dt>用户组</dt><dd><AppBadge :tone="groupTone(detail.group)">{{ detail.group }}</AppBadge></dd></div>
          <div><dt>状态</dt><dd><AppBadge :tone="statusTone(detail.status)">{{ detail.status }}</AppBadge></dd></div>
          <div><dt>有效期</dt><dd class="mono">{{ formatDate(detail.expiresAt) }}</dd></div>
          <div><dt>核销进度</dt><dd class="mono">{{ detail.usedCount }} / {{ detail.maxRedemptions }}</dd></div>
        </dl>
        <h4 style="margin:18px 0 10px;font-size:13px;color:var(--text-secondary);font-weight:600;">核销记录</h4>
        <div v-if="(detail.usedBy||[]).length" style="display:flex;flex-direction:column;gap:8px;">
          <div v-for="u in detail.usedBy" :key="u.uid" class="admin-line-card">
            <div style="display:flex;flex-direction:column;gap:2px;">
              <strong>{{ u.displayName || u.name }}</strong>
              <span class="mono small muted">{{ u.name }} · {{ u.uid }}</span>
            </div>
          </div>
        </div>
        <NEmpty v-else description="尚未核销" />
      </template>
    </NModal>
  </section>
</template>
