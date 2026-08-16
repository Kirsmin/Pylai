<template>
  <NAlert
    type="warning"
    :show-icon="true"
    :bordered="false"
    style="width: 100%; max-width: 420px; text-align: left;"
  >
    <template #header>
      <span style="font-weight: 600;">会话过期</span>
    </template>
    <p style="margin: 4px 0;">当前页面停留时间过长，请刷新页面，重新注册。</p>
  </NAlert>
</template>
