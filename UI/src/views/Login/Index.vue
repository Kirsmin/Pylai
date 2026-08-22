<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NIcon } from 'naive-ui'
import { Account } from '@vicons/carbon'
import { useAuthStore } from '@/stores/auth'
import Dock from '@/components/Dock.vue'
import LocalLoginForm from './LocalLoginForm.vue'
import ExternalLogin from './ExternalLogin.vue'
import ManageApps from './ManageApps.vue'
import ManageThirdParty from './ManageThirdParty.vue'

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const panel = ref<'home' | 'apps' | 'thirdParty'>('home')
const returnUrl = ref('')
const externalError = ref('')

function isSafeReturnUrl(url: string): boolean {
  if (url.startsWith('//') || url.startsWith('\\')) return false
  if (/^(javascript|data):/i.test(url)) return false
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(url)) return false
  return url.startsWith('/')
}

function mapExternalError(error: unknown): string {
  if (error === 'external_login_requires_account') return '该第三方账号未绑定任何 Pylaios 账户，请先使用本地账户登录并绑定。'
  if (error === 'mfa_required') return '该账户已启用多因素认证，请继续完成第二因素验证。'
  if (error === 'external_failed') return '第三方登录失败，请重试。'
  if (error === 'mfa_step_up_required') return '绑定第三方账号需要先完成安全验证，请先通过 MFA 验证后再试。'
  if (error === 'invalid_state') return '第三方登录状态已过期或无效，请重新发起。'
  return ''
}

async function logout() {
  await authStore.logout()
  panel.value = 'home'
}

onMounted(async () => {
  const ru = route.query.return_url
  if (typeof ru === 'string' && ru && isSafeReturnUrl(ru)) returnUrl.value = ru
  externalError.value = mapExternalError(route.query.error)
})
</script>

<template>
  <div class="page-shell">
    <div class="page-wrapper">
      <div class="page-card">
        <div class="login-content" :class="{ 'manage-content': panel !== 'home' }">
          <template v-if="!authStore.isAuthenticated">
            <h1 class="login-title">Pylai!</h1>
            <p class="login-subtitle">登录</p>
            <LocalLoginForm :return-url="returnUrl" />
            <ExternalLogin :initial-error="externalError" />
          </template>

          <template v-else-if="panel === 'home'">
            <div class="login-title">
              <NIcon class="login-title-icon" :component="Account" />
              <span>&lt; Pylai &gt;</span>
            </div>
            <p class="login-subtitle">管理 Pylai 通行证</p>
            <NButton type="success" dashed @click="panel = 'apps'">管理已授权应用</NButton>
            <NButton type="success" dashed @click="panel = 'thirdParty'">第三方登录方式</NButton>
            <NButton type="success" dashed @click="router.push('/login/ResetPassword')">修改登录密码</NButton>
            <NButton quaternary @click="logout">退出登录</NButton>
            <NButton type="success" size="large" circle class="submit-btn" @click="router.push('/')">-&gt;</NButton>
          </template>

          <ManageApps v-else-if="panel === 'apps'" @back="panel = 'home'" />
          <ManageThirdParty v-else @back="panel = 'home'" />
        </div>
      </div>
      <Dock />
    </div>
  </div>
</template>

<style scoped>
.login-content { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 48px 32px; text-align: center; }
.manage-content { align-items: stretch; text-align: left; gap: 16px; }
.login-title { margin: 0; font-weight: 600; font-size: 32px; color: var(--text-primary); display: flex; align-items: center; justify-content: center; gap: 8px; }
.login-title-icon { font-size: 32px; color: var(--text-primary); }
.login-subtitle { margin: 0; font-size: 16px; color: var(--text-tertiary); }
</style>
