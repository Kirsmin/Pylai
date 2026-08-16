<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import type { AdminClientItem } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()

const clients = ref<AdminClientItem[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('clients'))

function endpointAllowed(method: string, path: string): boolean {
  return cap.value?.endpoints.some((e) => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const data = await authStore.request<{ items: AdminClientItem[]; total: number }>(
      `/api/clients?skip=${(page.value - 1) * pageSize}&take=${pageSize}`
    )
    clients.value = data?.items ?? []
    total.value = data?.total ?? 0
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载客户端失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<AdminClientItem | null>(null)

async function openDetail(id: string) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await authStore.request<AdminClientItem>(`/api/clients/${encodeURIComponent(id)}`) ?? null
  } catch (err) {
    message.error(err instanceof Error ? err.message : '加载客户端详情失败')
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

const editorVisible = ref(false)
const editingId = ref<string | null>(null)
const editingClient = ref<AdminClientItem | null>(null)
const saving = ref(false)
const form = ref({
  clientId: '',
  displayName: '',
  description: '',
  homepageUrl: '',
  type: 'Confidential',
  clientSecret: '',
  isFajorCertified: false,
  scopes: 'openid\nprofile:basic\nprofile:mail\nprofile:role\noffline_access',
  redirectUris: '',
  postLogoutRedirectUris: '',
  grantTypes: 'authorization_code\nrefresh_token',
  permissions: ''
})

function lines(value: string): string[] {
  return value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
}

function openCreate() {
  editingId.value = null
  editingClient.value = null
  form.value = {
    clientId: '',
    displayName: '',
    description: '',
    homepageUrl: '',
    type: 'Confidential',
    clientSecret: '',
    isFajorCertified: false,
    scopes: 'openid\nprofile:basic\nprofile:mail\nprofile:role\noffline_access',
    redirectUris: '',
    postLogoutRedirectUris: '',
    grantTypes: 'authorization_code\nrefresh_token',
    permissions: ''
  }
  editorVisible.value = true
}

function openEdit(client: AdminClientItem) {
  editingId.value = client.id
  editingClient.value = client
  form.value = {
    clientId: client.clientId,
    displayName: client.displayName,
    description: client.description ?? '',
    homepageUrl: client.homepageUrl ?? '',
    type: client.type,
    clientSecret: '',
    isFajorCertified: client.isFajorCertified,
    scopes: client.scopes.join('\n'),
    redirectUris: client.redirectUris.join('\n'),
    postLogoutRedirectUris: client.postLogoutRedirectUris.join('\n'),
    grantTypes: client.grantTypes.join('\n'),
    permissions: client.permissions.filter((p) => !p.startsWith('gt:') && !p.startsWith('scp:')).join('\n')
  }
  editorVisible.value = true
}

async function save() {
  saving.value = true
  try {
    const base = {
      displayName: form.value.displayName,
      description: form.value.description || null,
      homepageUrl: form.value.homepageUrl || null,
      isFajorCertified: form.value.isFajorCertified,
      scopes: lines(form.value.scopes),
      redirectUris: lines(form.value.redirectUris),
      postLogoutRedirectUris: lines(form.value.postLogoutRedirectUris),
      grantTypes: lines(form.value.grantTypes),
      permissions: lines(form.value.permissions)
    }

    if (editingId.value === null) {
      await authStore.request('/api/clients', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...base,
          clientId: form.value.clientId.trim(),
          type: form.value.type,
          clientSecret: form.value.clientSecret || ''
        })
      })
      message.success('客户端已创建')
    } else {
      await authStore.request(`/api/clients/${encodeURIComponent(editingId.value)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...base,
          clientSecret: form.value.clientSecret || undefined
        })
      })
      message.success('客户端已更新')
    }
    editorVisible.value = false
    load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '保存客户端失败')
  } finally {
    saving.value = false
  }
}

async function setDisabled(client: AdminClientItem, disabled: boolean) {
  try {
    await authStore.request(`/api/clients/${encodeURIComponent(client.id)}/${disabled ? 'disable' : 'enable'}`, {
      method: 'PATCH'
    })
    message.success(disabled ? '客户端已禁用' : '客户端已启用')
    load()
    if (detail.value?.id === client.id) openDetail(client.id)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '操作失败')
  }
}

async function remove(id: string) {
  try {
    await authStore.request(`/api/clients/${encodeURIComponent(id)}`, { method: 'DELETE' })
    message.success('客户端已删除')
    if (detailVisible.value) detailVisible.value = false
    load()
  } catch (err) {
    message.error(err instanceof Error ? err.message : '删除客户端失败')
  }
}

// ===== Logo 上传 / 删除 =====
const MAX_LOGO_SIZE = 2 * 1024 * 1024
const uploadingLogo = ref(false)
const logoInput = ref<HTMLInputElement | null>(null)
const logoVersion = ref(0)

function logoUrl(id: string): string {
  return `/api/clients/${encodeURIComponent(id)}/logo?v=${logoVersion.value}`
}

function chooseLogo(id: string) {
  const input = logoInput.value
  if (!input) return
  // 先绑定目标客户端，再打开文件选择器
  input.setAttribute('data-client-id', id)
  input.click()
}

async function uploadLogo(event: Event) {
  const input = event.target as HTMLInputElement
  const id = input.getAttribute('data-client-id') || ''
  const file = input.files?.[0]
  input.value = ''
  if (!id || !file) return

  if (file.size > MAX_LOGO_SIZE) {
    message.error('Logo 文件不能超过 2MB')
    return
  }

  uploadingLogo.value = true
  try {
    const body = new FormData()
    body.append('file', file)
    await authStore.request(`/api/clients/${encodeURIComponent(id)}/logo`, {
      method: 'PUT',
      body
    })
    logoVersion.value += 1
    message.success('Logo 已上传')
    load()
    if (editingClient.value?.id === id) refreshEditingClient(id)
    if (detail.value?.id === id) openDetail(id)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '上传 Logo 失败')
  } finally {
    uploadingLogo.value = false
  }
}

async function refreshEditingClient(id: string) {
  try {
    const updated = await authStore.request<AdminClientItem>(`/api/clients/${encodeURIComponent(id)}`)
    if (updated) editingClient.value = updated
  } catch {
    // 详情刷新失败不阻塞主流程，列表会在 load() 后保持最新。
  }
}

async function deleteLogo(id: string) {
  try {
    await authStore.request(`/api/clients/${encodeURIComponent(id)}/logo`, { method: 'DELETE' })
    logoVersion.value += 1
    message.success('Logo 已删除')
    load()
    if (editingClient.value?.id === id) refreshEditingClient(id)
    if (detail.value?.id === id) openDetail(id)
  } catch (err) {
    message.error(err instanceof Error ? err.message : '删除 Logo 失败')
  }
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="客户端管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('POST', '/api/clients')" type="success" ghost @click="openCreate">创建客户端</NButton>
      </template>
    </PageHeader>

    <div class="admin-table-card">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="clients.length > 0">
        <div class="admin-stack">
          <div v-for="client in clients" :key="client.id" class="client-card">
            <img v-if="client.hasLogo" :src="logoUrl(client.id)" alt="" class="logo" />
            <div v-else class="logo placeholder mono">{{ client.clientId.slice(0, 1).toUpperCase() }}</div>

            <div class="client-main">
              <div class="client-title">
                <strong>{{ client.displayName || client.clientId }}</strong>
                <span class="mono muted">{{ client.clientId }}</span>
                <AppBadge :tone="client.isDisabled ? 'neutral' : 'success'">{{ client.isDisabled ? 'disabled' : 'enabled' }}</AppBadge>
                <AppBadge v-if="client.isFajorCertified" tone="purple">Fajor</AppBadge>
              </div>
              <p class="muted">{{ client.description || '暂无描述' }}</p>
              <p class="mono muted uris">{{ client.redirectUris.join(' · ') || '无 redirect URI' }}</p>
            </div>

            <div class="client-actions">
              <NButton v-if="endpointAllowed('GET', '/api/clients/{id}')" size="small" quaternary type="success" @click="openDetail(client.id)">详情</NButton>
              <NButton v-if="endpointAllowed('PUT', '/api/clients/{id}')" size="small" quaternary type="success" @click="openEdit(client)">编辑</NButton>
              <NButton v-if="endpointAllowed('PUT', '/api/clients/{id}/logo')" size="small" quaternary type="success" :loading="uploadingLogo" @click="chooseLogo(client.id)">Logo</NButton>
              <NButton
                v-if="!client.isDisabled && endpointAllowed('PATCH', '/api/clients/{id}/disable')"
                size="small"
                quaternary
                type="warning"
                @click="setDisabled(client, true)"
              >
                禁用
              </NButton>
              <NButton
                v-if="client.isDisabled && endpointAllowed('PATCH', '/api/clients/{id}/enable')"
                size="small"
                quaternary
                type="success"
                @click="setDisabled(client, false)"
              >
                启用
              </NButton>
              <NPopconfirm v-if="endpointAllowed('DELETE', '/api/clients/{id}')" @positive-click="remove(client.id)">
                <template #trigger>
                  <NButton size="small" quaternary type="error">删除</NButton>
                </template>
                <span style="white-space: nowrap;">删除客户端 {{ client.clientId }}？</span>
              </NPopconfirm>
            </div>
          </div>
        </div>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="个" @update:page="load" />
      </template>
      <NEmpty v-else description="没有客户端" class="admin-empty" />
    </div>

    <NModal v-model:show="detailVisible" preset="card" style="width: min(94%, 820px);" title="客户端详情">
      <div v-if="detailLoading" class="admin-modal-state"><NSpin /></div>
      <template v-else-if="detail">
        <div class="detail-head">
          <img v-if="detail.hasLogo" :src="logoUrl(detail.id)" alt="" class="logo big" />
          <div v-else class="logo placeholder big mono">{{ detail.clientId.slice(0, 1).toUpperCase() }}</div>
          <div class="detail-title">
            <h3>{{ detail.displayName || detail.clientId }}</h3>
            <p class="mono muted">{{ detail.id }} · {{ detail.clientId }}</p>
          </div>
        </div>

        <dl class="admin-detail-grid">
          <div><dt>类型</dt><dd>{{ detail.type }}</dd></div>
          <div><dt>状态</dt><dd><AppBadge :tone="detail.isDisabled ? 'neutral' : 'success'">{{ detail.isDisabled ? '禁用' : '启用' }}</AppBadge></dd></div>
          <div><dt>Fajor 认证</dt><dd>{{ detail.isFajorCertified ? '是' : '否' }}</dd></div>
          <div><dt>主页</dt><dd>{{ detail.homepageUrl || '—' }}</dd></div>
          <div><dt>描述</dt><dd>{{ detail.description || '—' }}</dd></div>
          <div><dt>Scopes</dt><dd class="mono wrap">{{ detail.scopes.join('\n') }}</dd></div>
          <div><dt>Redirect URIs</dt><dd class="mono wrap">{{ detail.redirectUris.join('\n') || '—' }}</dd></div>
          <div><dt>Post Logout URIs</dt><dd class="mono wrap">{{ detail.postLogoutRedirectUris.join('\n') || '—' }}</dd></div>
          <div><dt>Grant Types</dt><dd class="mono wrap">{{ detail.grantTypes.join('\n') }}</dd></div>
          <div><dt>Permissions</dt><dd class="mono wrap">{{ detail.permissions.join('\n') }}</dd></div>
        </dl>

        <div class="admin-form-actions">
          <NButton v-if="endpointAllowed('PUT', '/api/clients/{id}/logo')" quaternary type="success" :loading="uploadingLogo" @click="chooseLogo(detail.id)">
            {{ detail.hasLogo ? '更换 Logo' : '上传 Logo' }}
          </NButton>
          <NButton v-if="detail.hasLogo && endpointAllowed('DELETE', '/api/clients/{id}/logo')" quaternary type="error" @click="deleteLogo(detail.id)">删除 Logo</NButton>
        </div>
      </template>
    </NModal>

    <NModal v-model:show="editorVisible" preset="card" style="width: min(94%, 760px);" :title="editingId === null ? '创建客户端' : '编辑客户端'">
      <div class="admin-form-stack">
        <div class="form-grid">
          <label class="admin-field">
            <span class="admin-field-label">Client ID</span>
            <input v-model="form.clientId" class="admin-input mono" :disabled="editingId !== null" placeholder="my-app" />
          </label>
          <label class="admin-field">
            <span class="admin-field-label">显示名</span>
            <input v-model="form.displayName" class="admin-input" placeholder="My Application" />
          </label>
          <label class="admin-field">
            <span class="admin-field-label">类型</span>
            <NSelect v-model:value="form.type" :disabled="editingId !== null" :options="[{ label: 'Confidential', value: 'Confidential' }, { label: 'Public', value: 'Public' }]" />
          </label>
          <label class="admin-field">
            <span class="admin-field-label">Client Secret（{{ editingId === null ? 'Confidential 创建可填写，Public 留空' : '留空表示不修改' }}）</span>
            <input v-model="form.clientSecret" type="password" class="admin-input mono" />
          </label>
          <label class="admin-field">
            <span class="admin-field-label">主页 URL</span>
            <input v-model="form.homepageUrl" class="admin-input mono" placeholder="https://myapp.dev" />
          </label>
          <label class="admin-field full">
            <span class="admin-field-label">描述</span>
            <textarea v-model="form.description" class="admin-input area" rows="2" placeholder="应用介绍" />
          </label>
          <label class="admin-field check full">
            <NSwitch v-model:value="form.isFajorCertified" />
            <span>Fajor 认证</span>
          </label>

          <!-- 编辑模式下的 Logo 上传区 -->
          <div v-if="editingId !== null && endpointAllowed('PUT', '/api/clients/{id}/logo')" class="admin-field full logo-editor">
            <span class="admin-field-label">Logo（PNG / SVG，≤ 2MB）</span>
            <div class="logo-editor-row">
              <img v-if="editingClient?.hasLogo" :src="logoUrl(editingId)" alt="" class="logo editor" />
              <div v-else class="logo placeholder editor mono">{{ form.clientId.slice(0, 1).toUpperCase() }}</div>
              <div class="logo-editor-actions">
                <NButton size="small" type="success" ghost :loading="uploadingLogo" @click="chooseLogo(editingId)">上传 / 更换</NButton>
                <NButton
                  v-if="editingClient?.hasLogo && endpointAllowed('DELETE', '/api/clients/{id}/logo')"
                  size="small"
                  quaternary
                  type="error"
                  @click="deleteLogo(editingId)"
                >
                  删除 Logo
                </NButton>
                <span class="muted">列表和详情弹窗也提供 Logo 按钮，可直接修改。</span>
              </div>
            </div>
          </div>

          <label class="admin-field">
            <span class="admin-field-label">Scopes（每行一个）</span>
            <textarea v-model="form.scopes" class="admin-input area mono" rows="6" />
          </label>
          <label class="admin-field">
            <span class="admin-field-label">Grant Types（每行一个）</span>
            <textarea v-model="form.grantTypes" class="admin-input area mono" rows="4" />
          </label>
          <label class="admin-field">
            <span class="admin-field-label">Redirect URIs（每行一个）</span>
            <textarea v-model="form.redirectUris" class="admin-input area mono" rows="4" />
          </label>
          <label class="admin-field">
            <span class="admin-field-label">Post Logout URIs（每行一个）</span>
            <textarea v-model="form.postLogoutRedirectUris" class="admin-input area mono" rows="3" />
          </label>
          <label class="admin-field full">
            <span class="admin-field-label">Permissions（每行一个，gt:/scp: 由服务端自动生成）</span>
            <textarea v-model="form.permissions" class="admin-input area mono" rows="3" />
          </label>
        </div>

        <div class="admin-form-actions">
          <NButton type="success" ghost :loading="saving" @click="save">保存</NButton>
        </div>
      </div>
    </NModal>

    <input ref="logoInput" type="file" accept="image/png,image/svg+xml" style="display: none;" @change="uploadLogo" />
  </section>
</template>

<style scoped>
.client-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px;
  border: 1px solid var(--card-border);
  border-radius: var(--admin-radius-sm);
  background: var(--card-bg-solid);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.logo {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  object-fit: contain;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  flex: 0 0 auto;
}

.logo.big {
  width: 56px;
  height: 56px;
}

.logo.editor {
  width: 56px;
  height: 56px;
}

.logo.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--success-color);
  font-weight: 700;
  font-size: 18px;
}

.client-main {
  flex: 1;
  min-width: 0;
}

.client-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 14px;
}

.client-title strong {
  color: var(--text-primary);
}

.client-title .mono,
.uris {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.muted {
  margin: 6px 0 0;
  color: var(--text-tertiary);
  font-size: 12px;
  line-height: 1.6;
}

.uris {
  max-width: 100%;
}

.client-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 4px;
}

.detail-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
}

.detail-title h3 {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.detail-title p {
  margin: 0;
  font-size: 12px;
  word-break: break-all;
}

.wrap {
  white-space: pre-wrap;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 14px;
}

.form-grid .full {
  grid-column: 1 / -1;
}

.area {
  resize: vertical;
}

.check {
  flex-direction: row !important;
  align-items: center;
  gap: 8px !important;
  color: var(--text-secondary);
}

.logo-editor-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.logo-editor-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
}

@media (max-width: 760px) {
  .client-card {
    flex-direction: column;
    align-items: stretch;
  }

  .client-actions {
    justify-content: flex-start;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
