<script setup lang="ts">
import { ref, nextTick, watch, computed, onMounted } from 'vue'
import { NButton, NInput, NAlert, NInputOtp } from 'naive-ui'
import type { ButtonProps } from 'naive-ui'
import { api, ApiError } from '@/utils/api'
import { SUPPORT_EMAIL, type PasswordPolicy } from '@/types/api'
import Dock from '@/components/Dock.vue'
import SessionExpiredAlert from '@/components/SessionExpiredAlert.vue'

type PageState = 'idle' | 'loading' | 'rateLimited' | 'serviceError' | 'email' | 'verifyCode' | 'username' | 'password' | 'invite' | 'inviteError' | 'completed'


const title = ref('Pylai！')
const subtitle = ref('注册 Pylai 通行证')
const btnType = ref<ButtonProps['type']>('success')
const btnText = ref('->')
const loading = ref(false)
const state = ref<PageState>('idle')
const inputRef = ref<InstanceType<typeof NInput> | null>(null)
const passwordNativeRef = ref<InstanceType<typeof NInput> | null>(null)
const emailRef = ref<InstanceType<typeof NInput> | null>(null)
const sessionToken = ref('')
const REG_SESSION_KEY = 'pylai_reg_session'

const requireInviteCode = ref(false)

function saveSession() {
  if (sessionToken.value) sessionStorage.setItem(REG_SESSION_KEY, sessionToken.value)
}

function clearSession() {
  sessionStorage.removeItem(REG_SESSION_KEY)
}


const email = ref('')
const emailError = ref('')
const isChangingEmail = ref(false)
const changesRemaining = ref(2)
const verificationCode = ref<string[]>([])
const otpStatus = ref<'warning'>()
const otpDisabled = ref(false)


const password = ref('')
const passwordPolicy = ref<PasswordPolicy>({
  minLength: 8,
  requireDigit: true,
  requireLowercase: false,
  requireUppercase: false,
  requireNonAlphanumeric: false
})


const username = ref('')
const usernameDuplicateFailed = ref(false)


const inviteCode = ref('')
const inviteErrorMsg = ref('')
const passwordSubmitError = ref('')
const inviteBanned = ref(false)


const userGroup = ref('normal')

const groupLabel = computed(() => {
  const g = userGroup.value.toLowerCase()
  if (g === 'admin') return 'Admin'
  if (g === 'max') return 'Max'
  return 'Normal'
})


const sessionExpired = ref(false)
const flashingRuleKeys = ref<Set<string>>(new Set())

function flashUnsatisfiedRules(keys: string[], duration = 600) {
  flashingRuleKeys.value = new Set(keys)
  setTimeout(() => {
    flashingRuleKeys.value = new Set()
  }, duration)
}


async function handleInit() {
  if (loading.value) return
  loading.value = true
  state.value = 'loading'
  title.value = 'Pylai...'

  try {
    // 拉取公共配置，判断是否强制邀请码
    try {
      const pub = await api('/api/config/public')
      requireInviteCode.value = (pub.requireInviteCode as boolean) ?? false
    } catch {
      requireInviteCode.value = false
    }

    const data = await api('/api/auth/register/init', { method: 'POST' })

    if (!data.success) {
      if (data.errorCode === 'rate_limited') {
        state.value = 'rateLimited'
        title.value = '×\u2009Pylai'
        subtitle.value = ''
      } else {
        state.value = 'serviceError'
        title.value = '×\u2009Pylai'
        subtitle.value = ''
      }
      return
    }

    sessionToken.value = (data.sessionToken as string) || ''
    saveSession()
    state.value = 'email'
    subtitle.value = '登记邮箱'
    email.value = ''
    emailError.value = ''
    isChangingEmail.value = false
    changesRemaining.value = 2
    verificationCode.value = []
    otpStatus.value = undefined
    otpDisabled.value = false
  } catch (e) {
    if (e instanceof ApiError && e.errorCode === 'rate_limited') {
      state.value = 'rateLimited'
    } else {
      state.value = 'serviceError'
    }
    title.value = '×\u2009Pylai'
    subtitle.value = ''
  } finally {
    loading.value = false
  }
}


function isValidEmail(str: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(str)
}

function handleEmailInput(value: string) {
  let cleaned = ''
  for (const char of value) {
    if (char.charCodeAt(0) > 31 && char.charCodeAt(0) !== 127 && char !== ' ') {
      cleaned += char
    }
  }
  email.value = cleaned
  emailError.value = ''
}

async function handleEmailSubmit() {
  if (!isValidEmail(email.value)) {
    emailError.value = '邮箱格式错误'
    return
  }
  loading.value = true
  try {
    const data = await api('/api/auth/register/send-email-code', {
      method: 'POST',
      body: JSON.stringify({ sessionToken: sessionToken.value, email: email.value })
    })
    if (data.success) {
      isChangingEmail.value = false
      state.value = 'verifyCode'
      verificationCode.value = []
      otpStatus.value = undefined
      otpDisabled.value = false
      if (typeof data.changesRemaining === 'number') changesRemaining.value = data.changesRemaining
      await nextTick()
    } else {
      emailError.value = data.error || '发送失败，请重试'
      if (data.errorCode === 'invalid_session') { sessionExpired.value = true; clearSession() }
      if (data.errorCode === 'max_changes') {
        changesRemaining.value = 0
        otpDisabled.value = true
      }
      if (data.errorCode === 'banned') {
        emailError.value = '该邮箱暂时无法注册，请更换邮箱或稍后再试。'
      }
    }
  } catch (e) {
    emailError.value = e instanceof ApiError && e.status === 403
      ? '该邮箱暂时无法注册，请更换邮箱或稍后再试。'
      : '网络错误，请重试'
  } finally {
    loading.value = false
  }
}

async function handleChangeEmail() {
  if (!isValidEmail(email.value)) {
    emailError.value = '邮箱格式错误'
    return
  }
  loading.value = true
  try {
    const data = await api('/api/auth/register/change-email', {
      method: 'POST',
      body: JSON.stringify({ sessionToken: sessionToken.value, newEmail: email.value })
    })
    if (data.success) {
      state.value = 'verifyCode'
      isChangingEmail.value = false
      emailError.value = ''
      verificationCode.value = []
      otpStatus.value = undefined
      otpDisabled.value = false
      if (typeof data.changesRemaining === 'number') changesRemaining.value = data.changesRemaining
      await nextTick()
    } else {
      emailError.value = data.error || '更换邮箱失败，请重试'
      if (data.errorCode === 'invalid_session') { sessionExpired.value = true; clearSession() }
      if (data.errorCode === 'max_changes') {
        changesRemaining.value = 0
        otpDisabled.value = true
      }
      if (data.errorCode === 'banned') {
        emailError.value = '该邮箱暂时无法注册，请更换邮箱或稍后再试。'
      }
    }
  } catch (e) {
    emailError.value = e instanceof ApiError && e.status === 403
      ? '该邮箱暂时无法注册，请更换邮箱或稍后再试。'
      : '网络错误，请重试'
  } finally {
    loading.value = false
  }
}

function handleCorrectEmail() {
  if (changesRemaining.value <= 0) return
  state.value = 'email'
  isChangingEmail.value = true
  verificationCode.value = []
  otpStatus.value = undefined
  otpDisabled.value = false
  emailError.value = ''
  nextTick(() => {
    emailRef.value?.focus()
  })
}


async function handleVerifyCode() {
  const code = verificationCode.value.join('')
  if (code.length !== 6) return
  loading.value = true
  try {
    const data = await api('/api/auth/register/verify-email', {
      method: 'POST',
      body: JSON.stringify({ sessionToken: sessionToken.value, code })
    })
    if (data.success) {
      state.value = 'username'
      subtitle.value = '设置用户名'
      username.value = ''
      usernameDuplicateFailed.value = false
    } else {
      if (data.errorCode === 'invalid_session') { sessionExpired.value = true; clearSession() }
      else if (data.errorCode === 'max_attempts') otpDisabled.value = true
      else if (data.errorCode === 'expired') {
        emailError.value = data.error || '验证码已过期，请重新获取'
        otpStatus.value = 'warning'
      }
      else otpStatus.value = 'warning'
      verificationCode.value = []
    }
  } catch {
    otpStatus.value = 'warning'
    verificationCode.value = []
  } finally {
    loading.value = false
  }
}


function handleUsernameInput(value: string) {
  for (const char of value) {
    if (char.trim() === '' || (char.charCodeAt(0) >= 0 && char.charCodeAt(0) <= 31) || char.charCodeAt(0) === 127) {
      username.value = value.replace(/[\s\x00-\x1F\x7F]/g, '')
      usernameDuplicateFailed.value = false
      return
    }
  }
  username.value = value
  usernameDuplicateFailed.value = false
}

function hasInvalidChars(str: string): boolean {
  for (const char of str) {
    if (char.trim() === '' || (char.charCodeAt(0) >= 0 && char.charCodeAt(0) <= 31) || char.charCodeAt(0) === 127) {
      return true
    }
  }
  return false
}

function validateUsername(): number[] {
  const errors: number[] = []
  if (username.value.length <= 2 || username.value.length >= 256) errors.push(0)
  if (hasInvalidChars(username.value)) errors.push(1)
  return errors
}

const usernameValid = computed(() => validateUsername().length === 0)

const usernameSuggestionRules = [
  { key: 'caseInsensitive', text: '不区分大小写' },
  { key: 'chinese', text: '支持中文' },
  { key: 'invalidChars', text: '无空格和控制字符' }
]

const usernameRequiredRules = computed(() => [
  { key: 'length', text: '2-256 字符', satisfied: username.value.length > 2 && username.value.length < 256 },
  { key: 'duplicate', text: '不可重复', satisfied: !usernameDuplicateFailed.value }
])

async function handleUsernameSubmit() {
  if (sessionExpired.value) return
  const errors = validateUsername()
  if (errors.length > 0) {
    flashUnsatisfiedRules(usernameRequiredRules.value.filter(r => !r.satisfied).map(r => r.key))
    return
  }
  loading.value = true
  try {
    const data = await api('/api/auth/register/check-username', {
      method: 'POST',
      body: JSON.stringify({ sessionToken: sessionToken.value, username: username.value })
    })
    if (data.success) {
      state.value = 'password'
      subtitle.value = '设置密码'
      password.value = ''
    } else if (data.errorCode === 'invalid_session') {
      sessionExpired.value = true; clearSession()
    } else if (data.errorCode === 'invalid_format') {
      flashUnsatisfiedRules(usernameRequiredRules.value.filter(r => !r.satisfied).map(r => r.key))
    } else if (data.errorCode === 'rate_limited') {
      emailError.value = data.error || '请求过于频繁，请稍后重试'
    } else {
      usernameDuplicateFailed.value = true
      flashUnsatisfiedRules(['duplicate'])
    }
  } catch (e) {
    if (e instanceof ApiError && e.errorCode === 'rate_limited') {
      emailError.value = '请求过于频繁，请稍后重试'
    } else {
      usernameDuplicateFailed.value = true
      flashUnsatisfiedRules(['duplicate'])
    }
  } finally {
    loading.value = false
  }
}


async function fetchPasswordPolicy() {
  try {
    const data = await api('/api/auth/password-policy')
    passwordPolicy.value = {
      minLength: (data.minLength as number) ?? 6,
      requireDigit: (data.requireDigit as boolean) ?? false,
      requireLowercase: (data.requireLowercase as boolean) ?? false,
      requireUppercase: (data.requireUppercase as boolean) ?? false,
      requireNonAlphanumeric: (data.requireNonAlphanumeric as boolean) ?? false
    }
  } catch {
  }
}

function handlePasswordInput(value: string) {
  let cleaned = ''
  for (const char of value) {
    if (!(char.trim() === '' || (char.charCodeAt(0) >= 0 && char.charCodeAt(0) <= 31) || char.charCodeAt(0) === 127)) {
      cleaned += char
    }
  }
  password.value = cleaned
}

function validatePassword(): number[] {
  const errors: number[] = []
  const p = passwordPolicy.value
  if (password.value.length < p.minLength) errors.push(0)
  if (p.requireDigit && !/\d/.test(password.value)) errors.push(1)
  if (p.requireLowercase && !/[a-z]/.test(password.value)) errors.push(1)
  if (p.requireUppercase && !/[A-Z]/.test(password.value)) errors.push(1)
  if (p.requireNonAlphanumeric && !/[^a-zA-Z0-9]/.test(password.value)) errors.push(1)
  if (hasInvalidChars(password.value)) errors.push(3)
  return errors
}

const passwordValid = computed(() => validatePassword().length === 0)

const passwordSuggestionRules = computed(() => {
  const p = passwordPolicy.value
  const rules: { key: string; text: string }[] = []
  if (!p.requireDigit) rules.push({ key: 'suggest-digit', text: '数字' })
  if (!p.requireLowercase) rules.push({ key: 'suggest-lowercase', text: '小写字母' })
  if (!p.requireUppercase) rules.push({ key: 'suggest-uppercase', text: '大写字母' })
  if (!p.requireNonAlphanumeric) rules.push({ key: 'suggest-special', text: '特殊字符' })
  rules.push({ key: 'suggest-chinese', text: '支持中文' })
  rules.push({ key: 'suggest-invalidChars', text: '无空格和控制字符' })
  return rules
})

const passwordRequiredRules = computed(() => {
  const p = passwordPolicy.value
  const rules: { key: string; text: string; satisfied: boolean }[] = []
  rules.push({ key: 'minLength', text: `至少 ${p.minLength} 个字符`, satisfied: password.value.length >= p.minLength })
  if (p.requireDigit) rules.push({ key: 'digit', text: '必须包括数字', satisfied: /\d/.test(password.value) })
  if (p.requireLowercase) rules.push({ key: 'lowercase', text: '必须包括小写字母', satisfied: /[a-z]/.test(password.value) })
  if (p.requireUppercase) rules.push({ key: 'uppercase', text: '必须包括大写字母', satisfied: /[A-Z]/.test(password.value) })
  if (p.requireNonAlphanumeric) rules.push({ key: 'special', text: '必须包括特殊字符', satisfied: /[^a-zA-Z0-9]/.test(password.value) })
  return rules
})

async function handlePasswordSubmit() {
  const errors = validatePassword()
  if (errors.length > 0) {
    flashUnsatisfiedRules(passwordRequiredRules.value.filter(r => !r.satisfied).map(r => r.key))
    return
  }
  loading.value = true
  passwordSubmitError.value = ''
  try {
    const data = await api('/api/auth/register/create', {
      method: 'POST',
      body: JSON.stringify({ sessionToken: sessionToken.value, password: password.value })
    })
    if (data.success) {
      if (typeof data.group === 'string' && data.group) userGroup.value = data.group
      state.value = 'invite'
      subtitle.value = '验证邀请码'
      inviteCode.value = ''
      inviteErrorMsg.value = ''
      inviteBanned.value = false
    } else {
      if (data.errorCode === 'invalid_session') { sessionExpired.value = true; clearSession() }
      else flashUnsatisfiedRules(passwordRequiredRules.value.filter(r => !r.satisfied).map(r => r.key))
    }
  } catch {
    passwordSubmitError.value = '网络错误，请重试'
  } finally {
    loading.value = false
  }
}


function handleInviteInput(value: string) {
  const cleaned = value.replace(/[\s\\]/g, '')
  if (cleaned !== value) inviteCode.value = cleaned
}

async function handleInviteSubmit() {
  if (inviteCode.value.length <= 3) return
  loading.value = true
  inviteErrorMsg.value = ''
  try {
    const data = await api('/api/auth/register/redeem-invite', {
      method: 'POST',
      body: JSON.stringify({ sessionToken: sessionToken.value, inviteCode: inviteCode.value })
    })
    if (data.success) {
      if (typeof data.newGroup === 'string' && data.newGroup) userGroup.value = data.newGroup
      await handleRegisterComplete()
    } else {
      if (data.errorCode === 'banned') {
        inviteBanned.value = true
        subtitle.value = '注册中止'
      } else if (data.errorCode === 'invalid_session') {
        sessionExpired.value = true; clearSession()
      } else if (data.errorCode === 'api_error') {
        state.value = 'inviteError'
        inviteErrorMsg.value = '外部服务错误，请稍后重试'
        inviteCode.value = ''
        await nextTick()
        inputRef.value?.focus()
      } else {
        state.value = 'inviteError'
        inviteErrorMsg.value = data.error || '邀请码无效'
        inviteCode.value = ''
        await nextTick()
        inputRef.value?.focus()
      }
    }
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) {
      inviteBanned.value = true
      subtitle.value = '注册中止'
    } else {
      state.value = 'inviteError'
      inviteErrorMsg.value = '网络错误，请重试'
      inviteCode.value = ''
      await nextTick()
      inputRef.value?.focus()
    }
  } finally {
    loading.value = false
  }
}

async function handleSkipInvite() {
  if (requireInviteCode.value) {
    inviteErrorMsg.value = '当前注册必须使用邀请码，无法跳过。'
    return
  }
  loading.value = true
  inviteErrorMsg.value = ''
  try {
    const data = await api('/api/auth/register/redeem-invite', {
      method: 'POST',
      body: JSON.stringify({ sessionToken: sessionToken.value })
    })
    if (data.success) {
      await handleRegisterComplete()
    } else {
      if (data.errorCode === 'invalid_session') { sessionExpired.value = true; clearSession() }
      else inviteErrorMsg.value = data.error || '跳过失败，请重试'
    }
  } catch {
    inviteErrorMsg.value = '网络错误，请重试'
  } finally {
    loading.value = false
  }
}


async function handleRegisterComplete() {
  try {
    const data = await api('/api/auth/register/complete', {
      method: 'POST',
      body: JSON.stringify({ sessionToken: sessionToken.value })
    })
    if (data.success) {
      state.value = 'completed'
      subtitle.value = '注册成功'
      clearSession()
    } else {
      if (data.errorCode === 'invalid_session') { sessionExpired.value = true; clearSession() }
      else inviteErrorMsg.value = data.error || '完成注册失败，请重试'
    }
  } catch {
    inviteErrorMsg.value = '网络错误，请重试'
  }
}


function openAbout() {
  window.open('/about', '_blank')
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  if (state.value === 'email' && email.value.includes('@')) {
    isChangingEmail.value ? handleChangeEmail() : handleEmailSubmit()
  } else if (state.value === 'verifyCode' && verificationCode.value.length === 6) {
    handleVerifyCode()
  } else if (state.value === 'password') {
    handlePasswordSubmit()
  } else if (state.value === 'username' && !sessionExpired.value) {
    handleUsernameSubmit()
  } else if ((state.value === 'invite' || state.value === 'inviteError') && inviteCode.value.length > 3) {
    handleInviteSubmit()
  }
}

function handleBlur() {
  if (state.value === 'invite' || state.value === 'inviteError' || state.value === 'username') {
    nextTick(() => {
      inputRef.value?.focus()
    })
  }
}

onMounted(async () => {
  const savedToken = sessionStorage.getItem(REG_SESSION_KEY)
  if (!savedToken) return

  sessionToken.value = savedToken
  try {
    const data = await api(`/api/auth/register/status?session_token=${encodeURIComponent(savedToken)}`)
    if (!data.success || !data.step) {
      clearSession()
      return
    }

    email.value = (data.pendingEmail as string) || ''
    changesRemaining.value = Math.max(0, 2 - Number(data.emailChangeCount ?? 0))

    if (data.completed) {
      state.value = 'completed'
      subtitle.value = '注册成功'
      clearSession()
      return
    }

    const step = Number(data.step)
    if (step === 1) {
      state.value = 'email'
      subtitle.value = '登记邮箱'
    } else if (step === 2) {
      state.value = 'verifyCode'
      subtitle.value = '验证邮箱'
    } else if (step === 3) {
      state.value = 'username'
      subtitle.value = '设置用户名'
      username.value = (data.normalizedName as string) || ''
    } else if (step === 4) {
      state.value = 'password'
      subtitle.value = '设置密码'
      username.value = (data.normalizedName as string) || ''
    } else if (step === 5 || step === 6) {
      state.value = 'invite'
      subtitle.value = '验证邀请码'
      userGroup.value = 'normal'
    }
  } catch {
    clearSession()
  }
})

watch(state, (newState) => {
  if (newState === 'email') nextTick(() => {
    emailRef.value?.focus()
  })
  if (newState === 'verifyCode') nextTick(() => {
    const otpInput = document.querySelector('.n-input-otp input') as HTMLInputElement
    otpInput?.focus()
  })
  if (newState === 'password') {
    fetchPasswordPolicy()
    nextTick(() => {
      passwordNativeRef.value?.focus()
    })
  }
  if (newState === 'username') nextTick(() => {
    inputRef.value?.focus()
  })
  if (newState === 'invite' || newState === 'inviteError') nextTick(() => {
    inputRef.value?.focus()
  })
})
</script>

<template>
  <div class="page-shell">
    <transition name="bg-fade">
      <div v-if="state === 'completed'" class="completed-bg" :class="'completed-bg-' + userGroup.toLowerCase()"></div>
    </transition>
    <div class="page-wrapper">
      <div class="page-card">
        <div class="register-content">
        <h1 class="register-title">
          <template v-if="state === 'email' || state === 'verifyCode'">
            <span class="title-bold">P</span><span class="title-light">ylai</span>
          </template>
          <template v-else-if="state === 'username'">
            <span class="title-bold">Py</span><span class="title-light">lai</span>
          </template>
          <template v-else-if="state === 'password'">
            <span class="title-bold">Pyl</span><span class="title-light">ai</span>
          </template>
          <template v-else-if="state === 'invite' || state === 'inviteError'">
            <template v-if="!inviteBanned">
              <span class="title-bold">Pyla</span><span class="title-light">i</span>
            </template>
            <template v-else>
              <span class="title-bold">×</span><span class="title-light">&#8201;Pylai</span>
            </template>
          </template>
          <template v-else-if="state === 'completed'">
            <span class="title-bold">Pylai!</span>
          </template>
          <template v-else>{{ title }}</template>
        </h1>

        <p v-if="subtitle" class="register-subtitle">{{ subtitle }}</p>

        
        <template v-if="state === 'rateLimited' || state === 'serviceError'">
          <NAlert
            type="warning"
            :show-icon="true"
            :bordered="false"
            style="width: 100%; max-width: 420px; text-align: left;"
          >
            <template #header>
              <span style="font-weight: 600;">{{ state === 'rateLimited' ? '请求过于频繁' : '注册服务故障' }}</span>
            </template>
            <template v-if="state === 'rateLimited'">
              <p style="margin: 4px 0;">请求过于频繁，请稍后重试。</p>
              <p style="margin: 4px 0;">等待几分钟后刷新页面即可恢复。</p>
            </template>
            <template v-else>
              <p style="margin: 4px 0;">由于注册服务故障，暂时无法完成注册。</p>
              <p style="margin: 4px 0;">此错误由服务端引起，请等待修复。</p>
              <p style="margin: 4px 0;">请将此页面错误信息发送至 {{ SUPPORT_EMAIL || '站点管理员' }} 以获得支持。</p>
            </template>
          </NAlert>
        </template>

        
        <template v-else-if="state === 'email'">
          <p v-if="emailError" class="error-msg">{{ emailError }}</p>
          <SessionExpiredAlert v-if="sessionExpired" />

          <NInput
            ref="emailRef"
            v-model:value="email"
            type="text"
            size="large"
            placeholder="邮箱"
            class="underline-input"
            autofocus
            :input-props="{ onKeydown: handleKeyDown }"
            @input="handleEmailInput"
          />

          <NButton
            v-if="isValidEmail(email) && !loading && !sessionExpired"
            type="success"
            size="large"
            circle
            class="submit-btn"
            @click="isChangingEmail ? handleChangeEmail() : handleEmailSubmit()"
          >
            -&gt;
          </NButton>
          <NButton v-else-if="loading" type="success" size="large" circle class="submit-btn" loading />
        </template>

        
        <template v-else-if="state === 'verifyCode'">
          <p v-if="emailError" class="error-msg">{{ emailError }}</p>
          <SessionExpiredAlert v-if="sessionExpired" />
          <template v-if="!sessionExpired">
            <p class="hint-msg">验证码已发送至 {{ email }}</p>
            <NInputOtp
              v-model:value="verificationCode"
              :length="6"
              :status="otpStatus"
              :disabled="otpDisabled"
              @complete="handleVerifyCode"
              @keydown="handleKeyDown"
            />
            <NButton
              v-if="!loading && verificationCode.length === 6 && !otpDisabled"
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="handleVerifyCode"
            >
              -&gt;
            </NButton>
            <NButton v-else-if="loading" type="success" size="large" circle class="submit-btn" loading />
          </template>
          <NAlert
            v-if="otpDisabled && changesRemaining > 0"
            type="warning"
            :show-icon="true"
            :bordered="false"
            style="width: 100%; max-width: 420px; text-align: left;"
          >
            <template #header>
              <span style="font-weight: 600;">错误次数过多</span>
            </template>
            <p style="margin: 4px 0;">验证码验证错误次数过多，你可以选择订正邮箱地址重试。</p>
          </NAlert>
          <template v-if="otpDisabled && changesRemaining <= 0">
            <NAlert
              type="error"
              :show-icon="true"
              :bordered="false"
              style="width: 100%; max-width: 420px; text-align: left;"
            >
              <template #header>
                <span style="font-weight: 600;">错误次数过多</span>
              </template>
              <p style="margin: 4px 0;">刷新页面以重新注册。</p>
              <p style="margin: 4px 0;">如有疑问，请将编码</p>
              <code style="display: inline-block; margin: 4px 0; font-family: inherit; background: transparent; word-break: break-all;">{{ sessionToken }}</code>
              <p style="margin: 4px 0;">发送至 {{ SUPPORT_EMAIL || '站点管理员' }} 以获得支持。</p>
              <p style="margin: 4px 0;">此编码仅用于客服定位问题，请勿公开。</p>
            </NAlert>
          </template>
          <NButton
            v-if="changesRemaining > 0 && !sessionExpired && !otpDisabled"
            quaternary
            type="success"
            size="small"
            @click="handleCorrectEmail"
          >
            订正邮箱
          </NButton>
        </template>

        
        <template v-else-if="state === 'username'">
          <NInput
            ref="inputRef"
            v-model:value="username"
            type="text"
            name="username"
            autocomplete="username"
            size="large"
            placeholder="用户名"
            class="underline-input"
            autofocus
            :input-props="{ onKeydown: handleKeyDown, onBlur: handleBlur }"
            @input="handleUsernameInput"
          />

          <div class="rules-text-list">
            <div
              v-for="item in usernameSuggestionRules"
              :key="item.key"
              class="rule-text-item rule-text-suggestion"
            >
              <span class="rule-text-symbol">*</span>
              <span class="rule-text-content">{{ item.text }}</span>
            </div>
            <div
              v-for="item in usernameRequiredRules"
              :key="item.key"
              class="rule-text-item"
              :class="{ 'rule-text-satisfied': item.satisfied, 'rule-highlight': flashingRuleKeys.has(item.key) }"
            >
              <span class="rule-text-symbol">{{ item.satisfied ? '✓' : '○' }}</span>
              <span class="rule-text-content">{{ item.text }}</span>
            </div>
          </div>

          <SessionExpiredAlert v-if="sessionExpired" />
          <p v-if="emailError && !sessionExpired" class="error-msg">{{ emailError }}</p>

          <NButton
            v-if="usernameValid && !loading && !sessionExpired"
            type="success"
            size="large"
            circle
            class="submit-btn"
            @click="handleUsernameSubmit"
          >
            -&gt;
          </NButton>
          <NButton v-else-if="loading && !sessionExpired" type="success" size="large" circle class="submit-btn" loading />
        </template>

        
        <template v-else-if="state === 'password'">
          <NInput
            ref="passwordNativeRef"
            v-model:value="password"
            type="password"
            size="large"
            placeholder="密码"
            class="underline-input"
            autofocus
            :input-props="{ onKeydown: handleKeyDown, autocomplete: 'new-password' }"
            @input="handlePasswordInput"
          />

          <div class="rules-text-list">
            <div
              v-for="item in passwordSuggestionRules"
              :key="item.key"
              class="rule-text-item rule-text-suggestion"
            >
              <span class="rule-text-symbol">*</span>
              <span class="rule-text-content">{{ item.text }}</span>
            </div>
            <div
              v-for="item in passwordRequiredRules"
              :key="item.key"
              class="rule-text-item"
              :class="{ 'rule-text-satisfied': item.satisfied, 'rule-highlight': flashingRuleKeys.has(item.key) }"
            >
              <span class="rule-text-symbol">{{ item.satisfied ? '✓' : '○' }}</span>
              <span class="rule-text-content">{{ item.text }}</span>
            </div>
          </div>

          <SessionExpiredAlert v-if="sessionExpired" />

          <p v-if="passwordSubmitError" class="error-msg">{{ passwordSubmitError }}</p>

          <NButton
            v-if="passwordValid && !loading && !sessionExpired"
            type="success"
            size="large"
            circle
            class="submit-btn"
            @click="handlePasswordSubmit"
          >
            -&gt;
          </NButton>
          <NButton v-else-if="loading" type="success" size="large" circle class="submit-btn" loading />
        </template>

        
        <template v-else-if="state === 'invite' || state === 'inviteError'">
          <template v-if="!inviteBanned">
            <p v-if="inviteErrorMsg" class="error-msg">{{ inviteErrorMsg }}</p>
            <SessionExpiredAlert v-if="sessionExpired" />

            <NButton
              v-if="!sessionExpired"
              quaternary
              type="success"
              size="small"
              class="invite-btn"
              @click="openAbout"
            >
              <span style="display: inline-block; position: relative;">
                获取邀请码
                <span style="position: absolute; top: -4px; right: -16px; font-size: 11px; color: var(--success-color);">↗</span>
              </span>
            </NButton>

            <NInput
              v-if="!sessionExpired"
              ref="inputRef"
              v-model:value="inviteCode"
              size="large"
              placeholder="邀请码"
              class="underline-input"
              autofocus
              :input-props="{ onKeydown: handleKeyDown, onBlur: handleBlur }"
              @input="handleInviteInput"
            />

            <NButton
              v-if="inviteCode.length > 3 && !loading && !sessionExpired"
              type="success"
              size="large"
              circle
              class="submit-btn"
              @click="handleInviteSubmit"
            >
              -&gt;
            </NButton>
            <NButton v-else-if="loading" type="success" size="large" circle class="submit-btn" loading />

            <NButton
              v-if="!loading && !sessionExpired && !requireInviteCode"
              quaternary
              type="success"
              size="small"
              @click="handleSkipInvite"
            >
              我没有邀请码，直接完成注册
            </NButton>
          </template>

          <template v-else>
            <NAlert
              type="error"
              :show-icon="true"
              :bordered="false"
              style="width: 100%; max-width: 420px; text-align: left;"
            >
              <template #header>
                <span style="font-weight: 600;">邀请码验证受限，注册中止</span>
              </template>
              <p style="margin: 4px 0;">关闭此页面，更换网络环境以重试。</p>
              <p style="margin: 4px 0;">如有疑问，请将编码</p>
              <code style="display: inline-block; margin: 4px 0; font-family: inherit; background: transparent; word-break: break-all;">{{ sessionToken }}</code>
              <p style="margin: 4px 0;">发送至 {{ SUPPORT_EMAIL || '站点管理员' }} 以获得支持。</p>
              <p style="margin: 4px 0;">此编码仅用于客服定位问题，请勿公开。</p>
            </NAlert>
          </template>
        </template>

        
        <template v-else-if="state === 'completed'">
          <div class="profile-card">
            <div class="profile-row">
              <span class="profile-label">用户名</span>
              <span class="profile-value">{{ username }}</span>
            </div>
            <div class="profile-row">
              <span class="profile-label">邮箱</span>
              <span class="profile-value">{{ email }}</span>
            </div>
            <div class="profile-row">
              <span class="profile-label">权限</span>
              <span class="profile-value" :class="'profile-group-' + userGroup.toLowerCase()">{{ groupLabel }}</span>
            </div>
          </div>
          <NButton
            type="success"
            size="large"
            circle
            class="submit-btn"
            @click="$router.push('/login')"
          >
            -&gt;
          </NButton>
        </template>

        
        <template v-else>
          <NButton v-if="!loading" :type="btnType" size="large" circle @click="handleInit()">
            {{ btnText }}
          </NButton>
          <NButton v-else :type="btnType" size="large" circle loading />
        </template>
      </div>
    </div>
    <Dock />
  </div>
</div>
</template>

<style scoped>




.register-content {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 32px;
  text-align: center;
}

.register-title {
  margin: 0;
  font-weight: 600;
  font-size: 32px;
  color: var(--text-primary);
}

.title-bold {
  font-weight: 600;
}

.title-light {
  font-weight: 500;
}

.register-subtitle {
  margin: 0;
  font-size: 16px;
  color: var(--text-secondary);
}

.hint-msg {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
}

.completed-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.completed-bg-normal {
  background: var(--page-bg-completed-normal);
}

.completed-bg-admin {
  background: var(--page-bg-completed-admin);
}

.completed-bg-max {
  background: var(--page-bg-completed-max);
}

.bg-fade-enter-active {
  transition: opacity 0.8s ease;
}

.bg-fade-enter-from {
  opacity: 0;
}

.profile-card {
  width: 100%;
  max-width: 260px;
  padding: 4px 8px;
  text-align: left;
}

.profile-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  padding: 6px 0;
}

.profile-label {
  font-size: 13px;
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.profile-value {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
  word-break: break-all;
  text-align: right;
}

.profile-group-normal {
  color: var(--success-color);
}

.profile-group-admin {
  color: var(--info-color);
}

.profile-group-max {
  color: var(--purple-color);
}

.invite-btn {
  margin-top: -8px;
  padding-right: 24px !important;
}

.rules-text-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  width: 100%;
  max-width: 280px;
  margin-bottom: 4px;
  text-align: left;
}

.rule-text-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-primary);
  position: relative;
  line-height: 1.5;
}

.rule-text-satisfied {
  color: var(--text-tertiary);
}

.rule-text-symbol {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  flex-shrink: 0;
  text-align: center;
  font-size: 15px;
  line-height: 1;
  font-family: 'Segoe UI Symbol', 'Courier New', Consolas, 'Noto Sans Symbols 2', monospace;
}

.rule-text-item::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  width: 100%;
  height: 2px;
  background: var(--highlight-color);
  opacity: 0;
  border-radius: 1px;
}

.rule-text-item.rule-highlight::after {
  animation: highlightLine 0.6s ease forwards;
}

@keyframes highlightLine {
  0% {
    opacity: 0;
  }
  25% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
  75% {
    opacity: 1;
  }
  100% {
    opacity: 0;
  }
}

@media (max-width: 640px) {
  .register-content {
    gap: 12px;
    padding: 24px 16px;
  }

  .register-title {
    font-size: 24px;
  }

  .register-subtitle {
    font-size: 14px;
  }
}
</style>
