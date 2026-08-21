<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import DateTimeText from '@/components/DateTimeText.vue'
import { groupLabel, statusLabel } from '@/utils/labels'
import type { AdminUserDetail, AdminUserListItem, AdminUserSession, AdminUserTokenUsageItem } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()
const dialog = useDialog()

const users = ref<AdminUserListItem[]>([])
const total = ref(0)
const loading = ref(false)
const search = ref('')
const group = ref<string | null>(null)
const status = ref<string | null>(null)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('users'))
const targetGroups = computed(() => cap.value?.targetGroups ?? [])
const canEditGroup = computed(() => cap.value?.canEditGroup ?? false)
const canEditStatus = computed(() => cap.value?.canEditStatus ?? false)

const groupOptions = computed(() => targetGroups.value.map(g => ({ label: groupLabel(g), value: g })))
const statusFilterOptions = [
  { label: '正常', value: 'Active' },
  { label: '封禁', value: 'Banned' },
  { label: '锁定', value: 'Locked' },
  { label: '已删除', value: 'Deleted' }
]
const statusEditOptions = statusFilterOptions.filter(option => option.value !== 'Deleted')

function groupTone(g: string) {
  if (g.toLowerCase() === 'normal') return 'success'
  if (g.toLowerCase() === 'admin') return 'info'
  if (g.toLowerCase() === 'max') return 'purple'
  return 'neutral'
}
function statusTone(s: string) {
  if (s.toLowerCase() === 'active') return 'success'
  if (s.toLowerCase() === 'banned') return 'danger'
  if (s.toLowerCase() === 'locked') return 'warning'
  return 'neutral'
}
function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      skip: String((page.value - 1) * pageSize), take: String(pageSize)
    })
    if (search.value.trim()) params.set('search', search.value.trim())
    if (group.value) params.set('group', group.value)
    if (status.value) params.set('status', status.value)
    const data = await authStore.request<{ total: number; users: AdminUserListItem[] }>(
      `/api/admin/users?${params.toString()}`
    )
    users.value = data?.users ?? []
    total.value = data?.total ?? 0
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载失败')
  } finally { loading.value = false }
}
function searchUsers() { page.value = 1; load() }
function resetFilters() { search.value = ''; group.value = null; status.value = null; page.value = 1; load() }
onMounted(load)

// Detail
const detailVisible = ref(false)
const detail = ref<AdminUserDetail | null>(null)
const detailLoading = ref(false)
async function openDetail(uid: string) {
  detailVisible.value = true; detailLoading.value = true; detail.value = null
  try {
    const data = await authStore.request<{ user: AdminUserDetail | null }>(
      `/api/admin/users/${encodeURIComponent(uid)}`
    )
    detail.value = data?.user ?? null
  } catch (err) { message.error(err instanceof Error ? err.message : '加载详情失败'); detailVisible.value = false }
  finally { detailLoading.value = false }
}

// Edit
const editVisible = ref(false)
const editUid = ref('')
const editSaving = ref(false)
const editForm = ref({ displayName: '', email: '', status: 'Active', group: 'normal' })
function openEdit(user: AdminUserListItem) {
  editUid.value = user.uid
  editForm.value = { displayName: user.displayName ?? '', email: user.email ?? '', status: user.status, group: user.group }
  editVisible.value = true
}
async function saveEdit() {
  editSaving.value = true
  try {
    const body: Record<string, unknown> = {
      displayName: editForm.value.displayName || null,
      email: editForm.value.email || null
    }
    if (canEditStatus.value) body.status = editForm.value.status
    if (canEditGroup.value) body.group = editForm.value.group
    await authStore.request(`/api/admin/users/${encodeURIComponent(editUid.value)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    })
    message.success('用户已更新')
    editVisible.value = false; load()
  } catch (err) { message.error(err instanceof Error ? err.message : '更新失败') }
  finally { editSaving.value = false }
}

// Status toggle
const statusSavingUid = ref('')
async function setStatus(user: AdminUserListItem, next: string, lockoutEnd?: string | null) {
  statusSavingUid.value = user.uid
  try {
    const body: Record<string, unknown> = { status: next }
    if (lockoutEnd !== undefined) body.lockoutEnd = lockoutEnd
    await authStore.request(`/api/admin/users/${encodeURIComponent(user.uid)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    })
    message.success('状态已更新'); load()
    if (detail.value?.uid === user.uid) openDetail(user.uid)
  } catch (err) { message.error(err instanceof Error ? err.message : '操作失败') }
  finally { statusSavingUid.value = '' }
}

const lockVisible = ref(false)
const lockUser = ref<AdminUserListItem | null>(null)
const lockMode = ref('15m')
const customLockoutEnd = ref('')
function openLock(user: AdminUserListItem) {
  lockUser.value = user; lockMode.value = '15m'; customLockoutEnd.value = ''; lockVisible.value = true
}
async function confirmLock() {
  if (!lockUser.value) return
  let lockoutEnd: string | null = null
  const minutes: Record<string, number> = { '15m': 15, '1h': 60, '24h': 1440 }
  if (lockMode.value in minutes) lockoutEnd = new Date(Date.now() + minutes[lockMode.value] * 60000).toISOString()
  if (lockMode.value === 'custom') {
    const value = new Date(customLockoutEnd.value)
    if (!customLockoutEnd.value || Number.isNaN(value.getTime()) || value.getTime() <= Date.now()) {
      message.warning('请选择未来的锁定到期时间')
      return
    }
    lockoutEnd = value.toISOString()
  }
  await setStatus(lockUser.value, 'Locked', lockoutEnd)
  lockVisible.value = false
}

// Password
const passwordVisible = ref(false)
const passwordUid = ref('')
const passwordSaving = ref(false)
const newPassword = ref('')
function openPassword(user: AdminUserListItem) { passwordUid.value = user.uid; newPassword.value = ''; passwordVisible.value = true }
async function savePassword() {
  if (!newPassword.value) return
  passwordSaving.value = true
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(passwordUid.value)}/reset-password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ newPassword: newPassword.value })
    })
    message.success('密码已重置'); passwordVisible.value = false; newPassword.value = ''
  } catch (err) { message.error(err instanceof Error ? err.message : '重置失败') }
  finally { passwordSaving.value = false }
}

// Sessions
const sessionsVisible = ref(false)
const sessionsUid = ref('')
const sessionsLoading = ref(false)
const sessions = ref<AdminUserSession[]>([])
async function loadSessions(uid: string) {
  sessionsLoading.value = true; sessions.value = []
  try {
    const data = await authStore.request<{ sessions: AdminUserSession[] }>(
      `/api/admin/users/${encodeURIComponent(uid)}/sessions`
    )
    sessions.value = data?.sessions ?? []
  } catch (err) { message.error(err instanceof Error ? err.message : '加载会话失败') }
  finally { sessionsLoading.value = false }
}
function openSessions(user: AdminUserListItem) { sessionsUid.value = user.uid; sessionsVisible.value = true; loadSessions(user.uid) }
async function revokeSession(id: number) {
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(sessionsUid.value)}/sessions/${id}`, { method: 'DELETE' })
    message.success('会话已吊销'); loadSessions(sessionsUid.value)
  } catch (err) { message.error(err instanceof Error ? err.message : '吊销失败') }
}
async function revokeAllSessions(uid: string) {
  try {
    await authStore.request(`/api/admin/users/${encodeURIComponent(uid)}/revoke-sessions`, { method: 'POST' })
    message.success('全部会话已吊销'); if (sessionsVisible.value) loadSessions(uid)
  } catch (err) { message.error(err instanceof Error ? err.message : '吊销失败') }
}

// Token
const tokenVisible = ref(false)
const tokenUid = ref('')
const tokenLoading = ref(false)
const tokenInfo = ref<Partial<NonNullable<AdminUserDetail['token']>>>({})
const tokenUsage = ref<AdminUserTokenUsageItem[]>([])
const tokenPage = ref(0)
const tokenPageSize = 20
const tokenTotal = ref(0)
async function loadToken(uid: string, skip: number) {
  tokenLoading.value = true
  try {
    const data = await authStore.request<{
      exists: boolean; tokenPrefix?: string | null;
      createdAt?: string | null; refreshedAt?: string | null; expiresAt?: string | null;
      lastUsedAt?: string | null; lastIpAddress?: string | null; totalUsage?: number; usage?: AdminUserTokenUsageItem[]
    }>(`/api/admin/users/${encodeURIComponent(uid)}/token?skip=${skip}&take=${tokenPageSize}`)
    tokenInfo.value = data ?? {}
    tokenUsage.value = data?.usage ?? []
    tokenTotal.value = data?.totalUsage ?? 0
    tokenPage.value = Math.floor(skip / tokenPageSize)
  } catch (err) { message.error(err instanceof Error ? err.message : '加载失败') }
  finally { tokenLoading.value = false }
}
function openToken(user: AdminUserListItem) { tokenUid.value = user.uid; tokenVisible.value = true; loadToken(user.uid, 0) }
async function revokeToken(uid: string) {
  try {
    const data = await authStore.request<{ revoked: boolean }>(
      `/api/admin/users/${encodeURIComponent(uid)}/token`, { method: 'DELETE' }
    )
    message.success(data?.revoked === false ? '无 Token' : 'Token 已吊销')
    if (tokenVisible.value) loadToken(uid, 0)
    if (detailVisible.value && detail.value?.uid === uid) openDetail(uid)
  } catch (err) { message.error(err instanceof Error ? err.message : '吊销失败') }
}

function moreOptions(user: AdminUserListItem) {
  const opts: Array<{ label: string; key: string }> = []
  if (endpointAllowed('POST', '/api/admin/users/{uid}/reset-password')) opts.push({ label: '重置密码', key: 'password' })
  if (endpointAllowed('GET', '/api/admin/users/{uid}/sessions')) opts.push({ label: '会话', key: 'sessions' })
  if (endpointAllowed('GET', '/api/admin/users/{uid}/token')) opts.push({ label: 'Token', key: 'token' })
  if (endpointAllowed('DELETE', '/api/admin/users/{uid}')) opts.push({ label: '删除用户', key: 'delete' })
  return opts
}
function handleMore(key: string | number, user: AdminUserListItem) {
  const a = String(key)
  if (a === 'password') openPassword(user)
  else if (a === 'sessions') openSessions(user)
  else if (a === 'token') openToken(user)
  else if (a === 'delete') dialog.warning({
    title: '删除用户', content: `软删除 ${user.name} 并吊销其会话/Token？`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await authStore.request(`/api/admin/users/${encodeURIComponent(user.uid)}`, { method: 'DELETE' })
        message.success('用户已删除'); if (detailVisible.value) detailVisible.value = false; load()
      } catch (err) { message.error(err instanceof Error ? err.message : '删除失败') }
    }
  })
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="用户管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
      </template>
    </PageHeader>

    <div class="admin-toolbar">
      <NInput v-model:value="search" placeholder="搜索用户名 / 邮箱 / 显示名" clearable style="width:260px" @keyup.enter="searchUsers" />
      <NSelect v-if="targetGroups.length" v-model:value="group" placeholder="用户组" clearable :options="groupOptions" style="width:130px" @update:value="searchUsers" />
      <NSelect v-if="canEditStatus" v-model:value="status" placeholder="状态" clearable :options="statusFilterOptions" style="width:130px" @update:value="searchUsers" />
      <NButton type="success" ghost @click="searchUsers">查询</NButton>
      <NButton quaternary @click="resetFilters">重置</NButton>
    </div>

    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="users.length">
        <table class="admin-table">
          <thead>
            <tr>
              <th>用户</th><th>邮箱</th><th>组</th><th>状态</th><th>最近登录</th><th style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.uid">
              <td>
                <div style="display:flex;flex-direction:column;gap:2px;">
                  <span class="truncate" style="font-weight:600;">{{ u.displayName || u.name }}</span>
                  <span class="mono small muted">{{ u.name }}</span>
                </div>
              </td>
              <td><span class="truncate muted">{{ u.email || '—' }}</span></td>
              <td><AppBadge :tone="groupTone(u.group)">{{ groupLabel(u.group) }}</AppBadge></td>
              <td><AppBadge :tone="statusTone(u.status)">{{ statusLabel(u.status) }}</AppBadge></td>
              <td><DateTimeText :value="u.lastLoginAt" /></td>
              <td style="text-align:right">
                <div style="display:inline-flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;">
                  <NButton v-if="endpointAllowed('GET','/api/admin/users/{uid}')" size="tiny" quaternary type="success" @click="openDetail(u.uid)">详情</NButton>
                  <NButton v-if="endpointAllowed('PATCH','/api/admin/users/{uid}')" size="tiny" quaternary type="success" @click="openEdit(u)">编辑</NButton>
                  <template v-if="canEditStatus && endpointAllowed('PATCH','/api/admin/users/{uid}')">
                    <NPopconfirm v-if="u.status.toLowerCase()==='active'" @positive-click="setStatus(u,'Banned')">
                      <template #trigger><NButton size="tiny" quaternary type="warning" :loading="statusSavingUid===u.uid">封禁</NButton></template>
                      <span style="white-space:nowrap">封禁 {{ u.name }}？</span>
                    </NPopconfirm>
                    <NButton v-if="u.status.toLowerCase()==='active'" size="tiny" quaternary type="warning" :loading="statusSavingUid===u.uid" @click="openLock(u)">锁定</NButton>
                    <NPopconfirm v-if="u.status.toLowerCase()!=='active'" @positive-click="setStatus(u,'Active')">
                      <template #trigger><NButton size="tiny" quaternary type="success" :loading="statusSavingUid===u.uid">启用</NButton></template>
                      <span style="white-space:nowrap">启用 {{ u.name }}？</span>
                    </NPopconfirm>
                  </template>
                  <NDropdown v-if="moreOptions(u).length" trigger="click" :options="moreOptions(u)" @select="(k: string | number) => handleMore(k,u)">
                    <NButton size="tiny" quaternary>更多</NButton>
                  </NDropdown>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="人" @update:page="load" />
      </template>
      <NEmpty v-else description="没有符合条件的用户" class="admin-empty" />
    </div>

    <!-- Detail -->
    <NModal v-model:show="detailVisible" preset="card" style="width:min(92%,760px)" title="用户详情">
      <div v-if="detailLoading" class="admin-empty"><NSpin /></div>
      <template v-else-if="detail">
        <dl class="admin-detail-grid">
          <div><dt>UID</dt><dd class="mono">{{ detail.uid }}</dd></div>
          <div><dt>登录名</dt><dd class="mono">{{ detail.name }}</dd></div>
          <div><dt>显示名</dt><dd>{{ detail.displayName||'—' }}</dd></div>
          <div><dt>邮箱</dt><dd>{{ detail.email||'—' }}</dd></div>
          <div><dt>用户组</dt><dd><AppBadge :tone="groupTone(detail.group)">{{ groupLabel(detail.group) }}</AppBadge></dd></div>
          <div><dt>状态</dt><dd><AppBadge :tone="statusTone(detail.status)">{{ statusLabel(detail.status) }}</AppBadge></dd></div>
          <div><dt>注册时间</dt><dd><DateTimeText :value="detail.registerTime" /></dd></div>
          <div><dt>最近登录</dt><dd><DateTimeText :value="detail.lastLoginAt" /></dd></div>
          <div><dt>锁定到期</dt><dd><DateTimeText :value="detail.lockoutEnd" :empty="detail.status.toLowerCase()==='locked'?'永久锁定':'未锁定'" /></dd></div>
          <div><dt>失败次数</dt><dd>{{ detail.accessFailedCount }}</dd></div>
          <div><dt>活跃会话</dt><dd>{{ detail.activeSessions }}</dd></div>
          <div>
            <dt>外部登录</dt>
            <dd v-if="!detail.externalLogins.length">无</dd>
            <dd v-for="login in detail.externalLogins" :key="login.provider" class="mono small">
              {{ login.providerDisplayName||login.provider }} · <DateTimeText :value="login.boundAt" />
            </dd>
          </div>
        </dl>
        <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap;">
          <NButton v-if="endpointAllowed('POST','/api/admin/users/{uid}/revoke-sessions')" quaternary type="warning" @click="revokeAllSessions(detail.uid)">吊销全部会话</NButton>
          <NButton v-if="endpointAllowed('DELETE','/api/admin/users/{uid}/token')" quaternary type="error" @click="revokeToken(detail.uid)">吊销 UserToken</NButton>
        </div>
      </template>
    </NModal>

    <!-- Edit -->
    <NModal v-model:show="editVisible" preset="card" style="width:min(92%,480px)" title="编辑用户">
      <div style="display:flex;flex-direction:column;gap:14px;">
        <label class="admin-field">
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:4px;display:block;">显示名</span>
          <input v-model="editForm.displayName" class="admin-input" placeholder="显示名称" />
        </label>
        <label class="admin-field">
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:4px;display:block;">邮箱</span>
          <input v-model="editForm.email" class="admin-input" placeholder="user@example.com" />
        </label>
        <div v-if="canEditStatus">
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:6px;display:block;">状态</span>
          <div class="segmented">
            <button v-for="opt in statusEditOptions" :key="opt.value" type="button" :class="{active:editForm.status===opt.value}" @click="editForm.status=opt.value">{{ opt.label }}</button>
          </div>
        </div>
        <div v-if="canEditGroup">
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:6px;display:block;">用户组</span>
          <div class="segmented">
            <button v-for="opt in groupOptions" :key="opt.value" type="button" :class="{active:editForm.group===opt.value}" @click="editForm.group=opt.value">{{ opt.label }}</button>
          </div>
        </div>
        <div style="display:flex;justify-content:flex-end;margin-top:4px;">
          <NButton type="success" ghost :loading="editSaving" @click="saveEdit">保存</NButton>
        </div>
      </div>
    </NModal>

    <!-- Lock -->
    <NModal v-model:show="lockVisible" preset="card" style="width:min(92%,440px)" title="锁定用户">
      <div style="display:flex;flex-direction:column;gap:14px;">
        <NRadioGroup v-model:value="lockMode">
          <NSpace vertical>
            <NRadio value="15m">15 分钟</NRadio>
            <NRadio value="1h">1 小时</NRadio>
            <NRadio value="24h">24 小时</NRadio>
            <NRadio value="permanent">永久</NRadio>
            <NRadio value="custom">自定义</NRadio>
          </NSpace>
        </NRadioGroup>
        <input v-if="lockMode==='custom'" v-model="customLockoutEnd" type="datetime-local" class="admin-input" />
        <div style="display:flex;justify-content:flex-end;">
          <NButton type="warning" ghost :loading="statusSavingUid===lockUser?.uid" @click="confirmLock">确认锁定</NButton>
        </div>
      </div>
    </NModal>

    <!-- Password -->
    <NModal v-model:show="passwordVisible" preset="card" style="width:min(92%,400px)" title="重置密码">
      <div style="display:flex;flex-direction:column;gap:12px;">
        <label>
          <span style="font-size:12px;color:var(--text-tertiary);margin-bottom:4px;display:block;">新密码</span>
          <input v-model="newPassword" type="password" class="admin-input" placeholder="输入新密码" />
        </label>
        <p class="muted small">重置后该用户全部会话将被吊销。</p>
        <div style="display:flex;justify-content:flex-end;">
          <NButton type="success" ghost :loading="passwordSaving" :disabled="!newPassword" @click="savePassword">重置密码</NButton>
        </div>
      </div>
    </NModal>

    <!-- Sessions -->
    <NModal v-model:show="sessionsVisible" preset="card" style="width:min(92%,720px)" title="用户会话">
      <div v-if="sessionsLoading" class="admin-empty"><NSpin /></div>
      <template v-else>
        <div v-if="sessions.length" style="display:flex;flex-direction:column;gap:8px;">
          <div v-for="s in sessions" :key="s.id" class="admin-line-card">
            <div style="display:flex;flex-direction:column;gap:2px;min-width:0;">
              <strong :class="{muted:!s.active}">#{{ s.id }} {{ s.active?'活跃':'已吊销' }}</strong>
              <span class="mono small muted"><DateTimeText :value="s.createdAt" /> → <DateTimeText :value="s.expiresAt" /></span>
              <span class="small muted">{{ s.ipAddress||'未知 IP' }} · {{ s.userAgent||'未知 UA' }}</span>
            </div>
            <NButton v-if="s.active && endpointAllowed('DELETE','/api/admin/users/{uid}/sessions/{sessionId}')" size="small" quaternary type="error" @click="revokeSession(s.id)">吊销</NButton>
          </div>
        </div>
        <NEmpty v-else description="没有会话记录" />
        <div v-if="sessions.length" style="margin-top:12px;">
          <NButton v-if="endpointAllowed('POST','/api/admin/users/{uid}/revoke-sessions')" quaternary type="error" @click="revokeAllSessions(sessionsUid)">吊销全部会话</NButton>
        </div>
      </template>
    </NModal>

    <!-- Token -->
    <NModal v-model:show="tokenVisible" preset="card" style="width:min(92%,760px)" title="UserToken">
      <div v-if="tokenLoading" class="admin-empty"><NSpin /></div>
      <template v-else>
        <dl class="admin-detail-grid">
          <div><dt>状态</dt><dd class="mono">{{ tokenInfo.exists ? (tokenInfo.tokenPrefix||'—') : '未创建' }}</dd></div>
          <div><dt>创建</dt><dd><DateTimeText :value="tokenInfo.createdAt" /></dd></div>
          <div><dt>刷新</dt><dd><DateTimeText :value="tokenInfo.refreshedAt" /></dd></div>
          <div><dt>过期</dt><dd><DateTimeText :value="tokenInfo.expiresAt" empty="永不过期" /></dd></div>
          <div><dt>最近使用</dt><dd><DateTimeText :value="tokenInfo.lastUsedAt" /></dd></div>
          <div><dt>最近 IP</dt><dd class="mono">{{ tokenInfo.lastIpAddress||'—' }}</dd></div>
        </dl>
        <div v-if="tokenUsage.length" style="display:flex;flex-direction:column;gap:6px;margin-top:14px;">
          <div v-for="u in tokenUsage" :key="u.id" class="admin-line-card">
            <div style="display:flex;flex-direction:column;gap:2px;">
              <strong class="mono small">{{ u.method }} {{ u.endpoint }}</strong>
              <span class="mono small muted"><DateTimeText :value="u.occurredAt" /> · {{ u.ipAddress||'未知 IP' }}</span>
            </div>
          </div>
        </div>
        <NEmpty v-else-if="tokenInfo.exists" description="暂无使用记录" style="margin-top:12px;" />
        <div class="admin-pagination">
          <span class="muted small">共 {{ tokenTotal }} 条</span>
          <div style="display:flex;gap:4px;">
            <button class="pg-btn" :disabled="tokenPage<=0" @click="loadToken(tokenUid,(tokenPage-1)*tokenPageSize)">上一页</button>
            <button class="pg-btn" :disabled="(tokenPage+1)*tokenPageSize>=tokenTotal" @click="loadToken(tokenUid,(tokenPage+1)*tokenPageSize)">下一页</button>
          </div>
        </div>
        <div style="margin-top:12px;">
          <NButton v-if="endpointAllowed('DELETE','/api/admin/users/{uid}/token')" quaternary type="error" @click="revokeToken(tokenUid)">吊销 UserToken</NButton>
        </div>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.admin-field { display: block; }
.segmented {
  display: inline-flex; gap: 0; border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden;
}
.segmented button {
  padding: 6px 14px; border: none; background: var(--surface); color: var(--text-secondary);
  font: inherit; font-size: 13px; cursor: pointer; transition: all var(--transition-fast);
}
.segmented button:hover { background: var(--surface-hover); color: var(--text-primary); }
.segmented button.active { background: var(--success); color: #fff; }
.pg-btn {
  min-width: 32px; height: 32px; padding: 0 8px; border: 1px solid var(--border);
  border-radius: var(--radius-sm); background: var(--surface); color: var(--text-secondary);
  font-size: 13px; cursor: pointer; transition: all var(--transition-fast);
}
.pg-btn:hover:not(:disabled) { border-color: var(--border-strong); color: var(--text-primary); background: var(--surface-hover); }
.pg-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
