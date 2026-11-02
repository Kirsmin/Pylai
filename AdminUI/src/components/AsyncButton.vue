<script setup lang="ts">
/* 异步操作按钮：防重复提交、加载中保持宽度、失败自动反馈。
   点击后进入 pending，期间禁用；宽度锁定避免布局抖动。 */
import { ref } from 'vue'
import { useMessage } from 'naive-ui'
import type { ButtonProps } from 'naive-ui'

const props = withDefaults(defineProps<{
  onClick: () => Promise<unknown>
  type?: ButtonProps['type']
  size?: ButtonProps['size']
  secondary?: boolean
  tertiary?: boolean
  ghost?: boolean
  dashed?: boolean
  circle?: boolean
  block?: boolean
  disabled?: boolean
  silent?: boolean
}>(), {
  type: 'default',
  silent: false
})

const emit = defineEmits<{ done: []; error: [message: string] }>()

const message = useMessage()
const buttonRef = ref<{ $el: HTMLElement } | null>(null)
const pending = ref(false)
const lockedWidth = ref('')

async function handleClick() {
  if (pending.value || props.disabled) return
  const el = buttonRef.value?.$el as HTMLElement | undefined
  lockedWidth.value = el ? `${el.offsetWidth}px` : ''
  pending.value = true
  try {
    await props.onClick()
    emit('done')
  } catch (err) {
    const text = err instanceof Error ? err.message : '操作失败，请重试'
    if (!props.silent) message.error(text)
    emit('error', text)
  } finally {
    pending.value = false
    lockedWidth.value = ''
  }
}
</script>

<template>
  <NButton
    ref="buttonRef"
    :type="type"
    :size="size"
    :secondary="secondary"
    :tertiary="tertiary"
    :ghost="ghost"
    :dashed="dashed"
    :circle="circle"
    :block="block"
    :disabled="disabled || pending"
    :loading="pending"
    :style="lockedWidth ? { minWidth: lockedWidth } : undefined"
    @click="handleClick"
  >
    <slot />
  </NButton>
</template>
