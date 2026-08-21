<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'
import PageHeader from '@/components/PageHeader.vue'
import AppPagination from '@/components/AppPagination.vue'
import AppBadge from '@/components/AppBadge.vue'
import type { AdminClientItem } from '@/types/admin'

const authStore = useAuthStore()
const message = useMessage()
const dialog = useDialog()

const clients = ref<AdminClientItem[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('clients'))

function endpointAllowed(method: string, path: string) {
  return cap.value?.endpoints.some(e => e.method === method && e.path === path) ?? false
}

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({ skip: String((page.value - 1) * pageSize), take: String(pageSize) })
    const data = await authStore.request<{ total: number; items: AdminClientItem[] }>(
      `/api/clients?${params.toString()}`
    )
    clients.value = data?.items ?? []
    total.value = data?.total ?? 0
  } catch (err) { message.error(err instanceof Error ? err.message : '加载失败') }
  finally { loading.value = false }
}
onMounted(load)

const editorVisible = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const form = ref<Partial<AdminClientItem> & { clientSecret?: string }>({
  clientId: '', displayName: '', clientSecret: '', description: '', homepageUrl: '',
  isFajorCertified: false, type: 'Confidential',
  scopes: ['openid','profile:basic','profile:mail','profile:role','offline_access'],
  redirectUris: [], postLogoutRedirectUris: [],
  grantTypes: ['authorization_code','refresh_token'], permissions: []
})

function openCreate() {
  editingId.value = null
  form.value = {
    clientId: '', displayName: '', clientSecret: '', description: '', homepageUrl: '',
    isFajorCertified: false, type: 'Confidential',
    scopes: ['openid','profile:basic','profile:mail','profile:role','offline_access'],
    redirectUris: [], postLogoutRedirectUris: [],
    grantTypes: ['authorization_code','refresh_token'], permissions: []
  }
  editorVisible.value = true
}
function openEdit(c: AdminClientItem) {
  editingId.value = c.id
  form.value = { ...c }
  editorVisible.value = true
}
async function save() {
  saving.value = true
  try {
    const body = {
      clientId: form.value.clientId,
      displayName: form.value.displayName,
      clientSecret: form.value.clientSecret || undefined,
      description: form.value.description || undefined,
      homepageUrl: form.value.homepageUrl || undefined,
      isFajorCertified: form.value.isFajorCertified,
      type: form.value.type,
      scopes: form.value.scopes,
      redirectUris: form.value.redirectUris,
      postLogoutRedirectUris: form.value.postLogoutRedirectUris,
      grantTypes: form.value.grantTypes,
      permissions: form.value.permissions
    }
    if (editingId.value === null) {
      await authStore.request('/api/clients', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      message.success('客户端已创建')
    } else {
      await authStore.request(`/api/clients/${encodeURIComponent(editingId.value)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      })
      message.success('客户端已更新')
    }
    editorVisible.value = false; load()
  } catch (err) { message.error(err instanceof Error ? err.message : '保存失败') }
  finally { saving.value = false }
}

async function toggleDisable(c: AdminClientItem) {
  try {
    await authStore.request(`/api/clients/${encodeURIComponent(c.id)}/${c.isDisabled ? 'enable' : 'disable'}`, { method: 'PATCH' })
    message.success(c.isDisabled ? '客户端已启用' : '客户端已禁用')
    load()
  } catch (err) { message.error(err instanceof Error ? err.message : '操作失败') }
}

function confirmDelete(c: AdminClientItem) {
  dialog.warning({
    title: '删除客户端', content: `确定删除 ${c.displayName || c.clientId}？`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await authStore.request(`/api/clients/${encodeURIComponent(c.id)}`, { method: 'DELETE' })
        message.success('客户端已删除'); load()
      } catch (err) { message.error(err instanceof Error ? err.message : '删除失败') }
    }
  })
}

const logoFile = ref<File | null>(null)
const logoUid = ref('')
const logoVisible = ref(false)
const logoUploading = ref(false)

function openLogo(c: AdminClientItem) { logoUid.value = c.id; logoFile.value = null; logoVisible.value = true }
async function uploadLogo() {
  if (!logoFile.value) return
  logoUploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', logoFile.value)
    await authStore.request(`/api/clients/${encodeURIComponent(logoUid.value)}/logo`, { method: 'PUT', body: fd })
    message.success('Logo 已上传'); logoVisible.value = false; load()
  } catch (err) { message.error(err instanceof Error ? err.message : '上传失败') }
  finally { logoUploading.value = false }
}
async function deleteLogo(c: AdminClientItem) {
  try {
    await authStore.request(`/api/clients/${encodeURIComponent(c.id)}/logo`, { method: 'DELETE' })
    message.success('Logo 已删除'); load()
  } catch (err) { message.error(err instanceof Error ? err.message : '删除失败') }
}

function arrayInput(v: string): string[] {
  return v.split(/[\n,]/).map(s => s.trim()).filter(Boolean)
}
function arrayOutput(v: string[] | undefined): string {
  return (v || []).join('\n')
}
</script>

<template>
  <section class="admin-page">
    <PageHeader title="客户端管理" :subtitle="cap?.description">
      <template #actions>
        <NButton quaternary type="success" @click="load">刷新</NButton>
        <NButton v-if="endpointAllowed('POST','/api/clients')" type="success" ghost @click="openCreate">创建客户端</NButton>
      </template>
    </PageHeader>

    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="clients.length">
        <table class="admin-table">
          <thead>
            <tr>
              <th>客户端</th><th>类型</th><th>状态</th><th>Scope</th><th style="text-align:right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in clients" :key="c.id">
              <td>
                <div style="display:flex;align-items:center;gap:10px;">
                  <div v-if="c.hasLogo" style="width:32px;height:32px;border-radius:var(--radius-sm);border:1px solid var(--border);overflow:hidden;background:var(--surface);">
                    <img :src="`/api/clients/${c.id}/logo`" style="width:100%;height:100%;object-fit:contain;" />
                  </div>
                  <div v-else style="width:32px;height:32px;border-radius:var(--radius-sm);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;color:var(--text-tertiary);font-size:12px;">无</div>
                  <div style="display:flex;flex-direction:column;gap:2px;min-width:0;">
                    <span class="truncate" style="font-weight:600;">{{ c.displayName }}</span>
                    <span class="mono small muted">{{ c.clientId }}</span>
                  </div>
                </div>
              </td>
              <td><AppBadge tone="info">{{ c.type }}</AppBadge></td>
              <td><AppBadge :tone="c.isDisabled?'danger':'success'">{{ c.isDisabled?'禁用':'正常' }}</AppBadge></td>
              <td>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">
                  <AppBadge v-for="s in c.scopes.slice(0,3)" :key="s" tone="neutral" style="font-size:11px;padding:1px 6px;">{{ s }}</AppBadge>
                  <span v-if="c.scopes.length>3" class="small muted">+{{ c.scopes.length-3 }}</span>
                </div>
              </td>
              <td style="text-align:right">
                <div style="display:inline-flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;">
                  <NButton v-if="endpointAllowed('PUT','/api/clients/{id}')" size="tiny" quaternary type="success" @click="openEdit(c)">编辑</NButton>
                  <NButton size="tiny" quaternary @click="toggleDisable(c)">{{ c.isDisabled?'启用':'禁用' }}</NButton>
                  <NButton v-if="endpointAllowed('PUT','/api/clients/{id}/logo')" size="tiny" quaternary @click="openLogo(c)">Logo</NButton>
                  <NButton v-if="c.hasLogo && endpointAllowed('DELETE','/api/clients/{id}/logo')" size="tiny" quaternary type="error" @click="deleteLogo(c)">删Logo</NButton>
                  <NPopconfirm v-if="endpointAllowed('DELETE','/api/clients/{id}')" @positive-click="confirmDelete(c)">
                    <template #trigger><NButton size="tiny" quaternary type="error">删除</NButton></template>
                    <span style="white-space:nowrap">删除 {{ c.clientId }}？</span>
                  </NPopconfirm>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" unit="个" @update:page="load" />
      </template>
      <NEmpty v-else description="没有客户端" class="admin-empty" />
    </div>

    <NModal v-model:show="editorVisible" preset="card" style="width:min(92%,600px);max-height:85vh;overflow:auto;" :title="editingId===null?'创建客户端':'编辑客户端'">
      <div style="display:flex;flex-direction:column;gap:12px;">
        <label><span class="field-label">clientId</span><input v-model="form.clientId" class="admin-input mono" :disabled="editingId!==null" /></label>
        <label><span class="field-label">显示名称</span><input v-model="form.displayName" class="admin-input" /></label>
        <label v-if="editingId===null"><span class="field-label">客户端密钥</span><input v-model="form.clientSecret" type="password" class="admin-input" placeholder="留空自动生成" /></label>
        <label><span class="field-label">介绍</span><input v-model="form.description" class="admin-input" /></label>
        <label><span class="field-label">主页</span><input v-model="form.homepageUrl" class="admin-input" /></label>
        <div style="display:flex;align-items:center;gap:8px;">
          <input :checked="form.isFajorCertified" type="checkbox" @change="form.isFajorCertified = ($event.target as HTMLInputElement).checked" />
          <span style="font-size:13px;">Fajor 认证</span>
        </div>
        <label><span class="field-label">Scopes（每行一个）</span><textarea :value="arrayOutput(form.scopes)" class="admin-input mono" rows="4" @input="form.scopes = arrayInput(($event.target as HTMLTextAreaElement).value)" /></label>
        <label><span class="field-label">重定向地址（每行一个）</span><textarea :value="arrayOutput(form.redirectUris)" class="admin-input mono" rows="3" @input="form.redirectUris = arrayInput(($event.target as HTMLTextAreaElement).value)" /></label>
        <label><span class="field-label">登出后重定向地址（每行一个）</span><textarea :value="arrayOutput(form.postLogoutRedirectUris)" class="admin-input mono" rows="2" @input="form.postLogoutRedirectUris = arrayInput(($event.target as HTMLTextAreaElement).value)" /></label>
        <label><span class="field-label">授权类型（每行一个）</span><textarea :value="arrayOutput(form.grantTypes)" class="admin-input mono" rows="2" @input="form.grantTypes = arrayInput(($event.target as HTMLTextAreaElement).value)" /></label>
        <div style="display:flex;justify-content:flex-end;margin-top:4px;">
          <NButton type="success" ghost :loading="saving" @click="save">保存</NButton>
        </div>
      </div>
    </NModal>

    <NModal v-model:show="logoVisible" preset="card" style="width:min(92%,400px)" title="上传 Logo">
      <div style="display:flex;flex-direction:column;gap:12px;">
        <input type="file" accept="image/svg+xml,image/png" @change="logoFile = ($event.target as HTMLInputElement).files?.[0] ?? null" />
        <p class="muted small">仅支持 SVG 和 PNG，最大 2MB</p>
        <div style="display:flex;justify-content:flex-end;">
          <NButton type="success" ghost :loading="logoUploading" :disabled="!logoFile" @click="uploadLogo">上传</NButton>
        </div>
      </div>
    </NModal>
  </section>
</template>

<style scoped>
.field-label { font-size:12px; color:var(--text-tertiary); margin-bottom:4px; display:block; }
textarea.admin-input { resize:vertical; min-height:60px; }
</style>
