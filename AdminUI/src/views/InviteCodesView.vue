<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import type { AdminInviteCode } from '@/types/admin'

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

function endpointAllowed(method: string, path: string): boolean {
  return cap.value?.endpoints.some((e) => e.method === method && e.path === path) ?? false
}

function groupTone(group: string): 'success' | 'info' | 'purple' | 'neutral' {
  if (group.toLowerCase() === 'normal') return 'success'
  if (group.toLowerCase() === 'admin') return 'info'
  if (group.toLowerCase() === 'max') return 'purple'
  return 'neutral'
}

function progressPercent(code: AdminInviteCode): number {
  if (!code.maxRedemptions) return 100
  return Math.min(100, Math.round((code.usedCount / code.maxRedemptions) * 100))
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      skip: String((page.value - 1) * pageSize),
      take: String(pageSize)
    })
    if (group.value) params.set('group', group.value)
    const data = await authStore.request<{ success: boolean; total: number; codes: AdminInviteCode[] }>(
      `/api/admin/invite-codes?${params.toString()}`
    )
    codes.value = data?.codes ?? []
    total.value = data?.total ?? 0
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载邀请码失败')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function resetFilters() {
  group.value = null
  page.value = 1
  load()
}

onMounted(load)

const editorVisible = ref(false)
const editingCode = ref<string | null>(null)
const saving = ref(false)
const form = ref({ code: '', group: 'normal', maxRedemptions: 10 })

function openCreate() {
  editingCode.value = null
  form.value = { code: '', group: 'normal', maxRedemptions: 10 }
  editorVisible.value = true
}

function openEdit(code: AdminInviteCode) {
  editingCode.value = code.code
  form.value = {
    code: code.code,
    group: code.group,
    maxRedemptions: code.maxRedemptions
  }
  editorVisible.value = true
}

async function save() {
  saving.value = true
  try {
    if (editingCode.value === null) {
      await authStore.request('/api/admin/invite-codes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: form.value.code.trim(),
          group: form.value.group,
          maxRedemptions: form.value.maxRedemptions
        })
      })
      message.success('邀请码已创建')
    } else {
      await authStore.request(`/api/admin/invite-codes/${encodeURIComponent(editingCode.value)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          group: form.value.group,
          maxRedemptions: form.value.maxRedemptions
        })
      })
      message.success('邀请码已更新')
    }
    editorVisible.value = false
    load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '保存邀请码失败')
  } finally {
    saving.value = false
  }
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AdminInviteCode | null>(null)

async function openDetail(code: string) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    const data = await authStore.request<{ success: boolean; code: AdminInviteCode | null }>(
      `/api/admin/invite-codes/${encodeURIComponent(code)}`
    )
    detail.value = data?.code ?? null
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载邀请码详情失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

async function remove(code: string) {
  try {
    await authStore.request(`/api/admin/invite-codes/${encodeURIComponent(code)}`, { method: 'DELETE' })
    message.success('邀请码已删除')
    if (detailVisible.value) detailVisible.value = false
    load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '删除邀请码失败')
  }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="邀请码" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('POST', '/api/admin/invite-codes')" type="success" ghost @click="openCreate">创建邀请码</NButton>
      </template>
    </PageHeader>

    <div class="admin-toolbar">
      <NSelect v-model:value="group" class="tool-select" placeholder="用户组" clearable :options="groupOptions" @update:value="search" />
      <NButton type="success" ghost @click="search">查询</NButton>
      <NButton quaternary @click="resetFilters">重置</NButton>
    </div>

    <div class="admin-table-card">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="codes.length > 0">
        <div class="admin-table-wrap">
          <table class="admin-table table-invites">
            <colgroup>
              <col style="width: 30%" />
              <col style="width: 14%" />
              <col style="width: 26%" />
              <col style="width: 30%" />
            </colgroup>
            <thead>
              <tr>
                <th>邀请码</th>
                <th>用户组</th>
                <th>已核销 / 上限</th>
                <th class="cell-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="code in codes" :key="code.code">
                <td><span class="mono cell-primary cell-ellipsis">{{ code.code }}</span></td>
                <td><AppBadge :tone="groupTone(code.group)">{{ code.group }}</AppBadge></td>
                <td>
                  <div class="progress-cell">
                    <span class="mono muted">{{ code.usedCount }} / {{ code.maxRedemptions }}</span>
                    <span class="progress-track"><i :style="{ width: `${progressPercent(code)}%` }" /></span>
                  </div>
                </td>
                <td>
                  <div class="cell-actions">
                    <NButton v-if="endpointAllowed('GET', '/api/admin/invite-codes/{code}')" size="tiny" quaternary type="success" @click="openDetail(code.code)">详情</NButton>
                    <NButton v-if="endpointAllowed('PATCH', '/api/admin/invite-codes/{code}')" size="tiny" quaternary type="success" @click="openEdit(code)">编辑</NButton>
                    <NPopconfirm v-if="endpointAllowed('DELETE', '/api/admin/invite-codes/{code}')" @positive-click="remove(code.code)">
                      <template #trigger>
                        <NButton size="tiny" quaternary type="error">删除</NButton>
                      </template>
                      <span style="white-space: nowrap;">删除邀请码 {{ code.code }}？</span>
                    </NPopconfirm>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="个" @update:page="load" />
      </template>
      <NEmpty v-else description="没有邀请码" class="admin-empty" />
    </div>

    <NModal v-model:show="editorVisible" preset="card" style="width: min(92%, 440px);" :title="editingCode === null ? '创建邀请码' : '编辑邀请码'">
      <div class="admin-form-stack">
        <label v-if="editingCode === null" class="admin-field">
          <span class="admin-field-label">邀请码</span>
          <input v-model="form.code" class="admin-input" placeholder="如 TEST-001" />
        </label>
        <label class="admin-field">
          <span class="admin-field-label">用户组</span>
          <NSelect v-model:value="form.group" :options="groupOptions" />
        </label>
        <label class="admin-field">
          <span class="admin-field-label">最大核销次数</span>
          <input v-model.number="form.maxRedemptions" type="number" min="1" class="admin-input" />
        </label>
        <div class="admin-form-actions" style="margin-top: 0;">
          <NButton type="success" ghost :loading="saving" :disabled="editingCode === null && !form.code.trim()" @click="save">保存</NButton>
        </div>
      </div>
    </NModal>

    <NModal v-model:show="detailVisible" preset="card" style="width: min(92%, 620px);" title="邀请码详情">
      <div v-if="detailLoading" class="admin-modal-state"><NSpin /></div>
      <template v-else-if="detail">
        <dl class="admin-detail-grid">
          <div><dt>邀请码</dt><dd class="mono">{{ detail.code }}</dd></div>
          <div><dt>用户组</dt><dd><AppBadge :tone="groupTone(detail.group)">{{ detail.group }}</AppBadge></dd></div>
          <div><dt>核销进度</dt><dd class="mono">{{ detail.usedCount }} / {{ detail.maxRedemptions }}</dd></div>
        </dl>
        <h3 class="sub-title">核销记录</h3>
        <div class="admin-stack">
          <div v-for="u in detail.usedBy || []" :key="u.uid" class="admin-line-card">
            <div class="admin-line-main">
              <strong>{{ u.displayName || u.name }}</strong>
              <span class="mono muted">{{ u.name }} · {{ u.uid }}</span>
            </div>
          </div>
          <NEmpty v-if="(detail.usedBy || []).length === 0" description="尚未核销" />
        </div>
      </template>
    </NModal>
  </section>
</template>

<style scoped>
.tool-select {
  width: 150px;
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.progress-track {
  flex: 1;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
}

.progress-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--success-color);
  transition: width 0.2s ease;
}

.sub-title {
  margin: 18px 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}
</style>
