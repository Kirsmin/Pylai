<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/utils/http'
import { useUrlFilters } from '@/composables/useUrlFilters'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import StateBlock from '@/components/StateBlock.vue'
import type { AdminInviteCode, AdminInviteCodeCreateResponse, AdminInviteCodeListResponse } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()

const pageSize = 20

const codes = ref<AdminInviteCode[]>([])
const total = ref(0)
const state = ref<'loading' | 'ready' | 'empty' | 'error' | 'forbidden'>('loading')
const errorText = ref('')
const refreshing = ref(false)

const { filters, page, apply } = useUrlFilters(['q', 'group', 'status'], load)

const cap = computed(() => authStore.capability('inviteCodes'))

function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}
function groupTone(g: string) {
  if (g.toLowerCase() === 'normal') return 'success'
  if (g.toLowerCase() === 'admin') return 'info'
  if (g.toLowerCase() === 'max') return 'purple'
  return 'neutral'
}

const groupOptions = [
  { label: 'normal', value: 'normal' },
  { label: 'admin', value: 'admin' },
  { label: 'max', value: 'max' }
]
const statusOptions = [
  { label: '有效', value: 'active' },
  { label: '已用完', value: 'exhausted' },
  { label: '已过期', value: 'expired' },
  { label: '已撤销', value: 'revoked' }
]

// 有效状态为派生值：已撤销 > 已用完 > 已过期 > 有效（与后端 status 过滤语义一致）
function effectiveStatus(c: AdminInviteCode) {
  if (c.status === 'Revoked') return 'revoked'
  if (c.usedCount >= c.maxRedemptions) return 'exhausted'
  if (Date.parse(c.expiresAt) <= Date.now()) return 'expired'
  return 'active'
}
function progressPercent(c: AdminInviteCode) {
  if (!c.maxRedemptions) return 100
  return Math.min(100, Math.round((c.usedCount / c.maxRedemptions) * 100))
}

// 搜索框本地草稿；URL 变化（后退/分享打开）时回填
const qInput = ref(filters.value.q ?? '')
watch(() => filters.value.q, v => { qInput.value = v ?? '' })

async function load(f = filters.value, p = page.value) {
  if (codes.value.length === 0) state.value = 'loading'
  else refreshing.value = true
  errorText.value = ''
  try {
    const params = new URLSearchParams({ skip: String((p - 1) * pageSize), take: String(pageSize) })
    if (f.q?.trim()) params.set('search', f.q.trim())
    if (f.group) params.set('group', f.group)
    if (f.status) params.set('status', f.status)
    const data = await authStore.request<AdminInviteCodeListResponse>(`/api/admin/invite-codes?${params.toString()}`)
    codes.value = data?.codes ?? []
    total.value = data?.total ?? 0
    state.value = codes.value.length > 0 ? 'ready' : 'empty'
  } catch (err) {
    if (err instanceof ApiError && err.status === 403) {
      state.value = 'forbidden'
      codes.value = []
      return
    }
    errorText.value = err instanceof Error ? err.message : '加载失败'
    if (codes.value.length === 0) state.value = 'error'
  } finally {
    refreshing.value = false
  }
}
function reload() { return load(filters.value, page.value) }
function search() { apply({ q: qInput.value.trim() || null }) }
function resetFilters() { qInput.value = ''; apply({ q: null, group: null, status: null }) }

// ============ 注册策略：对话框二次确认 + MFA Step-up（后端强制） ============
const policyVisible = ref(false)
const policyDraft = ref(true)
const policySaving = ref(false)

function openPolicy() {
  policyDraft.value = authStore.inviteCodeRequired
  policyVisible.value = true
}
async function confirmPolicy() {
  if (policySaving.value) return
  policySaving.value = true
  try {
    await authStore.request('/api/admin/settings/require-invite-code', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requireInviteCode: policyDraft.value })
    })
    // 不只更新本地状态：重新读取后端 capability，确保显示服务端真实值
    await authStore.refreshCapabilities()
    if (authStore.inviteCodeRequired !== policyDraft.value) {
      message.warning('设置请求已完成，但后端返回的当前值不同，请检查服务端运行时配置')
      return
    }
    message.success(policyDraft.value ? '已开启：注册必须使用邀请码' : '已关闭：注册可跳过邀请码')
    policyVisible.value = false
  } catch (err) {
    await authStore.refreshCapabilities().catch(() => false)
    message.error(err instanceof Error ? err.message : '设置失败')
  } finally {
    policySaving.value = false
  }
}

// ============ 创建 / 编辑 ============
const editorVisible = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const form = ref({ group: 'normal' as string, maxRedemptions: 10, lifetimeHours: 168 })
// 高权限组（admin/max）服务端强制最大核销 1 次：选中后立即锁定输入框
const isHighPrivilegeGroup = computed(() => ['admin', 'max'].includes(form.value.group.toLowerCase()))
watch(isHighPrivilegeGroup, (high) => { if (high) form.value.maxRedemptions = 1 })

const editExpiresTs = ref<number | null>(null)

function openCreate() {
  editingId.value = null
  form.value = { group: 'normal', maxRedemptions: 10, lifetimeHours: 168 }
  editExpiresTs.value = null
  editorVisible.value = true
}
function openEdit(code: AdminInviteCode) {
  editingId.value = code.id
  form.value = { group: code.group, maxRedemptions: code.maxRedemptions, lifetimeHours: 168 }
  editExpiresTs.value = Date.parse(code.expiresAt)
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
      createdSaved.value = false
      createdVisible.value = data !== null && data !== undefined
    } else {
      if (editExpiresTs.value === null) {
        message.error('请选择到期时间')
        return
      }
      if (editExpiresTs.value <= Date.now()) {
        message.error('到期时间必须晚于当前时间')
        return
      }
      await authStore.request(`/api/admin/invite-codes/${encodeURIComponent(editingId.value)}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          maxRedemptions: form.value.maxRedemptions,
          expiresAt: new Date(editExpiresTs.value).toISOString()
        })
      })
      message.success('邀请码已更新')
    }
    editorVisible.value = false
    await reload()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '保存失败')
  } finally {
    saving.value = false
  }
}

// ============ 创建结果弹窗（复制 / 禁误关 / 勾选保存） ============
const createdCode = ref<AdminInviteCodeCreateResponse | null>(null)
const createdVisible = ref(false)
const createdSaved = ref(false)

async function copyCreatedCode() {
  if (!createdCode.value) return
  try {
    await navigator.clipboard.writeText(createdCode.value.code)
    message.success('邀请码已复制')
  } catch {
    message.error('复制失败，请手动复制')
  }
}
function finishCreated() { createdVisible.value = false; createdSaved.value = false }

// ============ 详情 / 撤销 ============
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AdminInviteCode | null>(null)

async function openDetail(id: string) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const data = await authStore.request<{ code: AdminInviteCode | null }>(
      `/api/admin/invite-codes/${encodeURIComponent(id)}`
    )
    detail.value = data?.code ?? null
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载详情失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}
async function revoke(id: string) {
  try {
    await authStore.request(`/api/admin/invite-codes/${encodeURIComponent(id)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revoked: true })
    })
    message.success('邀请码已撤销')
    detailVisible.value = false
    await reload()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '撤销失败')
  }
}

// 首次加载
void load()
</script>

<template>
  <section class="admin-page">
    <PageHeader title="邀请码" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary :loading="refreshing" @click="reload">刷新</NButton>
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
        <NButton size="small" @click="openPolicy">更改策略</NButton>
      </div>
    </div>

    <div class="admin-filter-panel">
      <div class="invite-filter-grid">
        <div class="admin-filter-field">
          <label>搜索</label>
          <NInput v-model:value="qInput" placeholder="按前缀搜索，如 Ab3" clearable @keyup.enter="search" />
        </div>
        <div class="admin-filter-field">
          <label>目标用户组</label>
          <NSelect
            :value="filters.group"
            placeholder="全部用户组"
            clearable
            :options="groupOptions"
            @update:value="(v: string | null) => apply({ group: v })"
          />
        </div>
        <div class="admin-filter-field">
          <label>状态</label>
          <NSelect
            :value="filters.status"
            placeholder="全部状态"
            clearable
            :options="statusOptions"
            @update:value="(v: string | null) => apply({ status: v })"
          />
        </div>
      </div>
      <div class="admin-filter-actions">
        <NButton quaternary @click="resetFilters">清空筛选</NButton>
        <NButton type="primary" @click="search">查询</NButton>
      </div>
    </div>

    <div v-if="state === 'ready'" class="admin-context-strip">
      <span>当前条件下共 <strong>{{ total }}</strong> 个邀请码</span>
      <span class="muted">完整邀请码只在创建成功时展示一次。</span>
    </div>

    <div class="admin-table-wrap">
      <StateBlock v-if="state === 'loading'" state="loading" variant="skeleton" loading-text="正在加载邀请码…" />
      <StateBlock
        v-else-if="state === 'forbidden'"
        state="forbidden"
        forbidden-text="没有权限查看邀请码"
        description="邀请码管理仅对 max 用户组开放。"
      />
      <StateBlock
        v-else-if="state === 'error'"
        state="error"
        error-text="邀请码列表加载失败"
        :description="errorText"
        retryable
        @retry="reload"
      />
      <StateBlock
        v-else-if="state === 'empty'"
        state="empty"
        empty-text="没有符合条件的邀请码"
        description="试试调整搜索关键词或筛选条件。"
      />
      <template v-else>
        <NAlert v-if="errorText" type="error" class="list-error-banner">
          刷新失败：{{ errorText }}（已保留旧数据）
          <NButton size="tiny" quaternary @click="reload">重试</NButton>
        </NAlert>
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
                  <StatusBadge :status="effectiveStatus(c)" />
                  <DateTimeText :value="c.expiresAt" />
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
                  <NPopconfirm
                    v-if="endpointAllowed('PATCH','/api/admin/invite-codes/{id}') && effectiveStatus(c) !== 'revoked'"
                    @positive-click="revoke(c.id)"
                  >
                    <template #trigger><NButton size="tiny" quaternary type="error">撤销</NButton></template>
                    <span style="white-space:nowrap">撤销 {{ c.prefix }}...？撤销需 MFA 验证。</span>
                  </NPopconfirm>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination :page="page" :page-size="pageSize" :total="total" unit="个" @update:page="(p: number) => apply({}, p)" />
      </template>
    </div>

    <!-- 更改注册策略：显示 当前值 → 新值 + 影响说明；确认需 MFA Step-up（后端强制） -->
    <NModal v-model:show="policyVisible" preset="card" style="width:min(calc(100vw - 24px),520px)" title="更改注册策略">
      <div class="admin-form-stack">
        <div class="policy-diff">
          <div class="policy-diff-row">
            <span class="policy-diff-label">当前值</span>
            <strong>{{ authStore.inviteCodeRequired ? '必须邀请码' : '邀请码可选' }}</strong>
          </div>
          <div class="policy-diff-row">
            <span class="policy-diff-label">新值</span>
            <strong :class="{ 'policy-new-enabled': policyDraft }">{{ policyDraft ? '必须邀请码' : '邀请码可选' }}</strong>
          </div>
        </div>
        <NRadioGroup v-model:value="policyDraft" style="display:flex;flex-direction:column;gap:12px;">
          <NRadio :value="true">
            <div><strong>必须邀请码</strong></div>
            <div class="muted small">新用户注册必须提供有效邀请码；注册流程的「跳过」入口将被拒绝。已注册用户不受影响。</div>
          </NRadio>
          <NRadio :value="false">
            <div><strong>邀请码可选</strong></div>
            <div class="muted small">新用户注册可跳过邀请码步骤直接完成；已发放的邀请码仍然有效，可用于提权。</div>
          </NRadio>
        </NRadioGroup>
        <NAlert type="warning" :show-icon="false">确认后需要完成 MFA Step-up 验证（TOTP / Passkey）；验证通过后策略立即生效。</NAlert>
        <div class="modal-actions">
          <NButton quaternary :disabled="policySaving" @click="policyVisible = false">取消</NButton>
          <NButton
            type="primary"
            :loading="policySaving"
            :disabled="policyDraft === authStore.inviteCodeRequired"
            @click="confirmPolicy"
          >
            确认更改
          </NButton>
        </div>
      </div>
    </NModal>

    <!-- 创建 / 编辑 -->
    <NModal v-model:show="editorVisible" preset="card" style="width:min(calc(100vw - 24px),480px)" :title="editingId===null?'创建邀请码':'编辑邀请码'">
      <div class="admin-form-stack">
        <label class="admin-field">
          <span class="admin-field-label">用户组</span>
          <NSelect v-model:value="form.group" :options="groupOptions" :disabled="editingId !== null" />
          <span v-if="editingId !== null" class="field-hint">用户组创建后不可修改。</span>
        </label>
        <label class="admin-field">
          <span class="admin-field-label">最大核销次数</span>
          <NInputNumber
            v-model:value="form.maxRedemptions"
            :min="1"
            :precision="0"
            :max="isHighPrivilegeGroup ? 1 : undefined"
            :disabled="isHighPrivilegeGroup"
            style="width:100%"
          />
          <span v-if="isHighPrivilegeGroup" class="field-hint">高权限邀请码仅允许核销 1 次（服务端强制）。</span>
        </label>
        <label v-if="editingId===null" class="admin-field">
          <span class="admin-field-label">有效期（小时）</span>
          <NInputNumber v-model:value="form.lifetimeHours" :min="1" :precision="0" style="width:100%" />
          <span class="field-hint">例如 168 小时为 7 天。</span>
        </label>
        <label v-else class="admin-field">
          <span class="admin-field-label">到期时间</span>
          <NDatePicker v-model:value="editExpiresTs" type="datetime" style="width:100%" clearable />
          <span class="field-hint">必须晚于当前时间；修改后立即生效。</span>
        </label>
        <div class="modal-actions">
          <NButton quaternary @click="editorVisible = false">取消</NButton>
          <NButton type="primary" :loading="saving" @click="save">保存</NButton>
        </div>
      </div>
    </NModal>

    <!-- 创建结果：禁误关 / Esc；复制 + 勾选「已保存」后才可完成 -->
    <NModal
      v-model:show="createdVisible"
      preset="card"
      style="width:min(92%,520px)"
      title="邀请码已创建"
      :mask-closable="false"
      :closable="false"
      :close-on-esc="false"
    >
      <div v-if="createdCode" class="created-code-box">
        <NAlert type="warning" :show-icon="false">完整邀请码只展示这一次，误关后无法恢复，请立即安全保存。</NAlert>
        <div class="created-code-row">
          <code class="mono created-code-value">{{ createdCode.code }}</code>
          <NButton size="small" quaternary @click="copyCreatedCode">复制</NButton>
        </div>
        <div class="muted small">
          用户组 {{ createdCode.group }} · 最大核销 {{ createdCode.maxRedemptions }} 次 · 到期 <DateTimeText :value="createdCode.expiresAt" />
        </div>
        <NCheckbox v-model:checked="createdSaved">我已安全保存该邀请码</NCheckbox>
        <div class="modal-actions">
          <NButton type="primary" :disabled="!createdSaved" @click="finishCreated">完成</NButton>
        </div>
      </div>
    </NModal>

    <!-- 详情 -->
    <NModal v-model:show="detailVisible" preset="card" style="width:min(92%,600px)" title="邀请码详情">
      <div v-if="detailLoading" class="admin-empty"><NSpin /></div>
      <template v-else-if="detail">
        <dl class="admin-detail-grid">
          <div><dt>邀请码</dt><dd class="mono">{{ detail.prefix }}...</dd></div>
          <div><dt>用户组</dt><dd><AppBadge :tone="groupTone(detail.group)">{{ detail.group }}</AppBadge></dd></div>
          <div><dt>状态</dt><dd><StatusBadge :status="effectiveStatus(detail)" /></dd></div>
          <div><dt>有效期</dt><dd><DateTimeText :value="detail.expiresAt" /></dd></div>
          <div><dt>核销进度</dt><dd class="mono">{{ detail.usedCount }} / {{ detail.maxRedemptions }}</dd></div>
        </dl>
        <h4 class="usage-title">核销记录</h4>
        <div v-if="(detail.usedBy||[]).length" class="redeem-list">
          <div v-for="u in detail.usedBy" :key="u.uid" class="admin-line-card">
            <div class="redeem-copy">
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
.policy-diff { display: flex; flex-direction: column; gap: 6px; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 12px; background: var(--surface-sunken); }
.policy-diff-row { display: flex; align-items: center; gap: 10px; font-size: 13px; }
.policy-diff-label { width: 48px; flex-shrink: 0; font-size: 12px; color: var(--text-tertiary); }
.policy-new-enabled { color: var(--accent); }
.invite-filter-grid { display: grid; grid-template-columns: minmax(220px, 2fr) minmax(150px, .8fr) minmax(150px, .8fr); gap: 10px 12px; align-items: end; }
.invite-status-cell { display: flex; flex-direction: column; gap: 2px; }
.invite-usage-cell { display: flex; align-items: center; gap: 8px; min-width: 170px; }
.invite-progress-track { flex: 1; height: 5px; overflow: hidden; border-radius: 999px; background: var(--surface-active); }
.invite-progress-value { height: 100%; border-radius: inherit; background: var(--success); }
.invite-row-actions { display: inline-flex; gap: 4px; }
.list-error-banner { margin-bottom: 10px; }
.created-code-box { display: flex; flex-direction: column; gap: 12px; }
.created-code-row { display: flex; align-items: center; gap: 8px; }
.created-code-value { flex: 1; min-width: 0; display: block; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--surface-sunken); font-size: 16px; word-break: break-all; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
.usage-title { margin: 16px 0 10px; font-size: 13px; color: var(--text-secondary); font-weight: 600; }
.redeem-list { display: flex; flex-direction: column; gap: 8px; }
.redeem-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
@media (max-width: 780px) { .invite-filter-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 520px) { .invite-filter-grid { grid-template-columns: 1fr; } .registration-policy { align-items: flex-start; flex-direction: column; } .policy-control { width: 100%; justify-content: space-between; } }
</style>
