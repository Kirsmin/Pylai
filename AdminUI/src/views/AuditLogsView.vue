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
const eventType = ref<string | null>(null)
const userId = ref('')
const ip = ref('')
const success = ref<boolean | null>(null)
const timeRange = ref<[number, number] | null>(null)
const page = ref(1)
const pageSize = 20

const cap = computed(() => authStore.capability('auditLogs'))

const eventLabels: Record<string, string> = {
  Login: '登录成功', LoginFailure: '登录失败', LoginLockedOut: '登录锁定', LoginIpBanned: '登录 IP 封禁',
  PasswordReset: '密码重置', ExternalLoginBound: '绑定外部登录', ExternalLoginSignedIn: '外部登录成功', ExternalLoginUnbound: '解绑外部登录',
  ConsentApproved: '同意授权', ConsentDenied: '拒绝授权', AuthorizationRevoked: '授权撤销', Logout: '退出登录',
  ClientCreated: '创建客户端', ClientUpdated: '更新客户端', ClientDeleted: '删除客户端', ClientDisabled: '禁用客户端', ClientEnabled: '启用客户端',
  ClientLogoUpdated: '更新客户端 Logo', ClientLogoDeleted: '删除客户端 Logo',
  TokenIssued: '签发令牌', TokenRefreshed: '刷新令牌', ClientCredentialsToken: '客户端凭据令牌', TokenRequest: '令牌请求',
  Authorize: '授权请求', AuthorizeRedirect: '授权跳转', UserInfo: '用户信息请求', Introspect: '令牌自省', Revoke: '令牌撤销', Discovery: 'OIDC Discovery', ApiCall: 'API 调用',
  InviteCodeRedeemed: '邀请码兑换成功', InviteCodeRedeemFailed: '邀请码兑换失败', InviteCodeCreated: '创建邀请码', InviteCodeUpdated: '更新邀请码',
  InviteCodeDeleted: '删除邀请码', InviteCodeRevoked: '撤销邀请码', RegisterStarted: '开始注册', RegisterCompleted: '完成注册',
  EmailVerificationSent: '发送邮箱验证', EmailVerificationFailed: '邮箱验证失败', EmailVerificationSuccess: '邮箱验证成功', EmailVerificationExpired: '邮箱验证过期',
  EmailVerificationMaxAttempts: '邮箱验证次数超限', EmailVerificationIpBanned: '邮箱验证 IP 封禁', EmailChanged: '邮箱变更', UserCreated: '创建用户',
  UserTokenCreated: '创建用户令牌', UserTokenRefreshed: '刷新用户令牌', UserTokenRevoked: '撤销用户令牌', UserTokenQueried: '查询用户令牌',
  ConfirmationSucceeded: '敏感确认成功', ConfirmationFailed: '敏感确认失败', MfaStepUpSkipped: '跳过 MFA Step-up',
  AdminUserUpdated: '管理员更新用户', AdminUserDeleted: '管理员删除用户', SessionsRevokedAll: '撤销全部会话', AdminAuthFailed: '管理员认证失败',
  AdminResetPassword: '管理员重置密码', AdminIpUnbanned: '管理员解除 IP 封禁', SettingsChanged: '系统设置变更', AltchaFailure: 'ALTCHA 验证失败', CliCommand: 'CLI 命令'
}

function option(value: string) {
  return { label: `${eventLabels[value] || value} · ${value}`, value }
}

const eventTypeOptions: any[] = [
  {
    type: 'group', label: '认证与账户', key: 'auth', children: [
      'Login', 'LoginFailure', 'LoginLockedOut', 'LoginIpBanned', 'PasswordReset',
      'ExternalLoginBound', 'ExternalLoginSignedIn', 'ExternalLoginUnbound', 'Logout'
    ].map(option)
  },
  {
    type: 'group', label: '注册与邀请码', key: 'registration', children: [
      'RegisterStarted', 'RegisterCompleted', 'EmailVerificationSent', 'EmailVerificationFailed',
      'EmailVerificationSuccess', 'EmailVerificationExpired', 'EmailVerificationMaxAttempts', 'EmailVerificationIpBanned',
      'EmailChanged', 'InviteCodeRedeemed', 'InviteCodeRedeemFailed', 'InviteCodeCreated', 'InviteCodeUpdated',
      'InviteCodeDeleted', 'InviteCodeRevoked', 'UserCreated'
    ].map(option)
  },
  {
    type: 'group', label: 'OAuth2 / OIDC', key: 'oauth', children: [
      'ConsentApproved', 'ConsentDenied', 'AuthorizationRevoked', 'ClientCreated', 'ClientUpdated', 'ClientDeleted',
      'ClientDisabled', 'ClientEnabled', 'ClientLogoUpdated', 'ClientLogoDeleted', 'TokenIssued', 'TokenRefreshed',
      'ClientCredentialsToken', 'TokenRequest', 'Authorize', 'AuthorizeRedirect', 'UserInfo', 'Introspect', 'Revoke', 'Discovery'
    ].map(option)
  },
  {
    type: 'group', label: '管理与安全', key: 'admin', children: [
      'AdminUserUpdated', 'AdminUserDeleted', 'SessionsRevokedAll', 'AdminAuthFailed', 'AdminResetPassword', 'AdminIpUnbanned',
      'SettingsChanged', 'ConfirmationSucceeded', 'ConfirmationFailed', 'MfaStepUpSkipped', 'UserTokenCreated', 'UserTokenRefreshed',
      'UserTokenRevoked', 'UserTokenQueried', 'AltchaFailure', 'CliCommand', 'ApiCall'
    ].map(option)
  }
]

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({ skip: String((page.value - 1) * pageSize), take: String(pageSize) })
    if (eventType.value) params.set('eventType', eventType.value)
    if (userId.value.trim()) params.set('userId', userId.value.trim())
    if (ip.value.trim()) params.set('ip', ip.value.trim())
    if (success.value !== null) params.set('success', String(success.value))
    if (timeRange.value?.[0]) params.set('from', new Date(timeRange.value[0]).toISOString())
    if (timeRange.value?.[1]) params.set('to', new Date(timeRange.value[1]).toISOString())
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
  void load()
}

function resetFilters() {
  eventType.value = null
  userId.value = ''
  ip.value = ''
  success.value = null
  timeRange.value = null
  page.value = 1
  void load()
}

function eventLabel(type: string) {
  return eventLabels[type] || type
}

function eventTone(type: string): 'success' | 'info' | 'warning' | 'danger' | 'purple' | 'neutral' {
  if (/(Failure|Failed|Denied|Locked|Banned)/.test(type)) return 'danger'
  if (/(Created|Completed|Success|Succeeded|Enabled|Issued|Redeemed|Bound)/.test(type)) return 'success'
  if (/(Deleted|Revoked|Disabled|Unbound)/.test(type)) return 'warning'
  if (/(Client|Authorize|Token|Consent|Discovery|UserInfo|Introspect)/.test(type)) return 'info'
  if (/(Mfa|Confirmation|Admin)/.test(type)) return 'purple'
  return 'neutral'
}

onMounted(load)
</script>

<template>
  <section class="admin-page">
    <PageHeader title="审计日志" :subtitle="cap?.description || '检索认证、管理、OAuth2 与安全事件，快速定位行为与失败原因。'">
      <template #actions>
        <NButton quaternary :loading="loading" @click="load">刷新</NButton>
      </template>
    </PageHeader>

    <div class="admin-filter-panel">
      <div class="audit-filter-grid">
        <div class="admin-filter-field audit-event-filter">
          <label>事件类型</label>
          <NSelect
            v-model:value="eventType"
            :options="eventTypeOptions"
            placeholder="全部事件"
            filterable
            clearable
            @keyup.enter="search"
          />
        </div>
        <div class="admin-filter-field">
          <label>用户 ID</label>
          <NInput v-model:value="userId" clearable placeholder="UID" @keyup.enter="search" />
        </div>
        <div class="admin-filter-field">
          <label>IP 地址</label>
          <NInput v-model:value="ip" clearable placeholder="例如 203.0.113.10" @keyup.enter="search" />
        </div>
        <div class="admin-filter-field">
          <label>结果</label>
          <NSelect
            v-model:value="success"
            placeholder="全部结果"
            clearable
            :options="[{ label: '成功', value: true }, { label: '失败', value: false }]"
          />
        </div>
        <div class="admin-filter-field audit-time-filter">
          <label>发生时间</label>
          <NDatePicker v-model:value="timeRange" type="datetimerange" clearable style="width: 100%;" />
        </div>
      </div>
      <div class="admin-filter-actions">
        <NButton quaternary @click="resetFilters">清空筛选</NButton>
        <NButton type="primary" :loading="loading" @click="search">查询</NButton>
      </div>
    </div>

    <div class="admin-context-strip">
      <span>当前条件下共 <strong>{{ total }}</strong> 条记录</span>
      <span class="muted">事件类型来自后端审计常量，可直接搜索中文说明或事件名。</span>
    </div>

    <div class="admin-table-wrap">
      <div v-if="loading" class="admin-empty"><NSpin /></div>
      <template v-else-if="logs.length">
        <table class="admin-table audit-table">
          <thead>
            <tr>
              <th>事件</th>
              <th>主体</th>
              <th>请求</th>
              <th>IP</th>
              <th>结果</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log.id">
              <td>
                <div class="audit-event-cell">
                  <div><AppBadge :tone="eventTone(log.eventType)">{{ eventLabel(log.eventType) }}</AppBadge></div>
                  <span class="mono small muted">{{ log.eventType }} · #{{ log.id }}</span>
                </div>
              </td>
              <td>
                <div class="compact-stack">
                  <span>{{ log.userEmail || '系统 / 匿名' }}</span>
                  <span v-if="log.userId" class="mono small muted">{{ log.userId }}</span>
                </div>
              </td>
              <td>
                <div class="audit-request-cell">
                  <span class="mono small">{{ [log.method, log.endpoint].filter(Boolean).join(' ') || '—' }}</span>
                  <NTooltip v-if="log.details" trigger="hover">
                    <template #trigger><span class="audit-details small muted">{{ log.details }}</span></template>
                    <span class="mono">{{ log.details }}</span>
                  </NTooltip>
                </div>
              </td>
              <td class="mono small muted">{{ log.ipAddress || '—' }}</td>
              <td><AppBadge :tone="log.success ? 'success' : 'danger'">{{ log.success ? '成功' : '失败' }}</AppBadge></td>
              <td><DateTimeText :value="log.timestamp" /></td>
            </tr>
          </tbody>
        </table>
        <AppPagination v-model:page="page" :page-size="pageSize" :total="total" @update:page="load" />
      </template>
      <NEmpty v-else description="当前筛选条件下没有审计记录" class="admin-empty" />
    </div>
  </section>
</template>

<style scoped>
.audit-filter-grid {
  display: grid;
  grid-template-columns: minmax(220px, 1.6fr) minmax(160px, .9fr) minmax(170px, 1fr) minmax(130px, .65fr);
  gap: 10px 12px;
  align-items: end;
}
.audit-time-filter { grid-column: span 2; }
.audit-table { min-width: 1040px; }
.audit-event-cell, .compact-stack, .audit-request-cell { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.audit-request-cell { max-width: 330px; }
.audit-details { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: help; }
@media (max-width: 1050px) {
  .audit-filter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .audit-time-filter { grid-column: span 2; }
}
@media (max-width: 620px) {
  .audit-filter-grid { grid-template-columns: 1fr; }
  .audit-time-filter { grid-column: auto; }
  .admin-filter-actions { justify-content: stretch; }
  .admin-filter-actions :deep(.n-button) { flex: 1; }
}
</style>
