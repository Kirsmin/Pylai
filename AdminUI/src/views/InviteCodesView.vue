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

const settingSaving = ref(false)

async function refreshPage() {
  try {
    await Promise.all([load(), authStore.refreshCapabilities()])
  } catch (err) {
    message.error(err instanceof Error ? err.message : '刷新失败')
  }
}

async function toggleRequireInviteCode(value: boolean) {
  if (settingSaving.value) return
  settingSaving.value = true
  try {
    await authStore.request('/api/admin/settings/require-invite-code', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requireInviteCode: value })
    })

    // 不只更新本地状态：立即重新读取后端 capability，确保刷新后仍显示服务端真实值。
    await authStore.refreshCapabilities()
    if (authStore.inviteCodeRequired !== value) {
      message.warning('设置请求已完成，但后端返回的当前值不同，请检查服务端运行时配置')
      return
    }
    message.success(value ? '已开启：注册必须使用邀请码' : '已关闭：注册可跳过邀请码')
  } catch (err) {
    await authStore.refreshCapabilities().catch(() => false)
    message.error(err instanceof Error ? err.message : '设置失败')
  } finally {
    settingSaving.value = false
  }
}

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
        <NButton quaternary @click="refreshPage">刷新</NButton>
        <NButton v-if="endpointAllowed('POST','/api/admin/invite-codes')" type="primary" @click="openCreate">创建邀请码</NButton>
      </template>
    </PageHeader>

    <div class="admin-panel registration-policy">
      <div class="policy-copy">
        <strong>注册访问策略</strong>
        <span>开启后，新用户注册流程必须提供有效邀请码。该值直接读取后端当前运行时配置。</span>
        <small>服务重启后的初始值仍由服务端配置文件决定；AdminUI 不写入后端配置文件。</small>
      </div>
      <div class="policy-control">
        <span :class="['policy-state', { enabled: authStore.inviteCodeRequired }]">
          {{ authStore.inviteCodeRequired ? '必须邀请码' : '邀请码可选' }}
        </span>
        <NSwitch
          :value="authStore.inviteCodeRequired"
          :loading="settingSaving"
          :disabled="settingSaving"
          @update:value="toggleRequireInviteCode"
        />
      </div>
    </div>

    <div class="admin-filter-panel">
      <div class="invite-filter-grid">
        <div class="admin-filter-field">
          <label>目标用户组</label>
          <NSelect v-model:value="group" placeholder="全部用户组" clearable :options="groupOptions" />
        </div>
      </div>
      <div class="admin-filter-actions">
        <NButton quaternary @click="resetFilters">清空筛选</NButton>
        <NButton type="primary" :loading="loading" @click="search">查询</NButton>
      </div>
    </div>

    <div class="admin-context-strip">
      <span>当前条件下共 <strong>{{ total }}</strong> 个邀请码</span>
      <span class="muted">完整邀请码只在创建成功时展示一次。</span>
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
                <div class="invite-status-cell">
                  <AppBadge :tone="statusTone(c.status)">{{ c.status }}</AppBadge>
                  <span class="mono small muted">{{ formatDate(c.expiresAt) }}</span>
                </div>
              </td>
              <td>
                <div class="invite-usage-cell">
                  <span class="mono small muted">{{ c.usedCount }} / {{ c.maxRedemptions }}</span>
                  <div class="invite-progress-track">
                    <div class="invite-progress-value" :style="{ width: `${progressPercent(c)}%` }" />
                  </div>
                </div>
              </td>
              <td style="text-align:right">
                <div class="invite-row-actions">
                  <NButton v-if="endpointAllowed('GET','/api/admin/invite-codes/{id}')" size="tiny" quaternary @click="openDetail(c.id)">详情</NButton>
                  <NButton v-if="endpointAllowed('PATCH','/api/admin/invite-codes/{id}')" size="tiny" quaternary @click="openEdit(c)">编辑</NButton>
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

    <NModal v-model:show="editorVisible" preset="card" style="width:min(calc(100vw - 24px),460px)" :title="editingId===null?'创建邀请码':'编辑邀请码'">
      <div class="admin-form-stack">
        <label class="admin-field">
          <span class="admin-field-label">用户组</span>
          <NSelect v-model:value="form.group" :options="groupOptions" :disabled="editingId !== null" />
          <span v-if="editingId !== null" class="field-hint">编辑时只修改核销上限，用户组保持不变。</span>
        </label>
        <label class="admin-field">
          <span class="admin-field-label">最大核销次数</span>
          <NInputNumber v-model:value="form.maxRedemptions" :min="1" :precision="0" style="width:100%" />
        </label>
        <label v-if="editingId===null" class="admin-field">
          <span class="admin-field-label">有效期（小时）</span>
          <NInputNumber v-model:value="form.lifetimeHours" :min="1" :precision="0" style="width:100%" />
          <span class="field-hint">例如 168 小时为 7 天。</span>
        </label>
        <div class="modal-actions">
          <NButton quaternary @click="editorVisible = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="save">保存</NButton>
        </div>
      </div>
    </NModal>

    <NModal v-model:show="createdVisible" preset="card" style="width:min(92%,520px)" title="邀请码已创建">
      <div v-if="createdCode" class="created-code-box">
        <NAlert type="warning" :show-icon="false">完整邀请码只展示这一次，请立即安全保存。</NAlert>
        <code class="mono created-code-value">{{ createdCode.code }}</code>
        <div class="muted small">{{ createdCode.group }} · 最大核销 {{ createdCode.maxRedemptions }} 次</div>
        <div class="modal-actions"><NButton type="primary" @click="createdVisible = false">我已保存</NButton></div>
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

<style scoped>
.registration-policy {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 18px;
}
.policy-copy { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.policy-copy strong { font-size: 13px; font-weight: 650; color: var(--text-primary); }
.policy-copy span { font-size: 12px; color: var(--text-secondary); }
.policy-copy small { font-size: 11px; color: var(--text-tertiary); }
.policy-control { flex-shrink: 0; display: flex; align-items: center; gap: 10px; }
.policy-state { font-size: 12px; color: var(--text-tertiary); }
.policy-state.enabled { color: var(--accent); font-weight: 600; }
.invite-filter-grid { display: grid; grid-template-columns: minmax(180px, 260px); }
.invite-status-cell { display: flex; flex-direction: column; gap: 2px; }
.invite-usage-cell { display: flex; align-items: center; gap: 8px; min-width: 170px; }
.invite-progress-track { flex: 1; height: 5px; overflow: hidden; border-radius: 999px; background: var(--surface-active); }
.invite-progress-value { height: 100%; border-radius: inherit; background: var(--success); }
.invite-row-actions { display: inline-flex; gap: 4px; }
.created-code-box { display: flex; flex-direction: column; gap: 12px; }
.created-code-value { display: block; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); font-size: 16px; word-break: break-all; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
@media (max-width: 680px) {
  .registration-policy { align-items: flex-start; flex-direction: column; }
  .policy-control { width: 100%; justify-content: space-between; }
}
</style>
