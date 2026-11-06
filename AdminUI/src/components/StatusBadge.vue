<script setup lang="ts">
/* 统一状态徽章：中文文案 + 色调 + 图标，状态绝不只靠颜色表达。 */
import { computed } from 'vue'
import type { Component } from 'vue'
import { AlertTriangle, CircleCheck, CircleX, InfoCircle, Minus } from '@vicons/tabler'

export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const props = withDefaults(defineProps<{
  status: string
  label?: string
  tone?: StatusTone
}>(), {})

interface Preset { label: string; tone: StatusTone }

/* 常见状态预设：中文文案 + 色调；未命中时原样展示并归入 neutral。 */
const PRESETS: Record<string, Preset> = {
  active: { label: '正常', tone: 'success' },
  enabled: { label: '已启用', tone: 'success' },
  success: { label: '成功', tone: 'success' },
  valid: { label: '有效', tone: 'success' },
  configured: { label: '已配置', tone: 'success' },
  disabled: { label: '已禁用', tone: 'neutral' },
  inactive: { label: '未启用', tone: 'neutral' },
  unconfigured: { label: '未配置', tone: 'neutral' },
  pending: { label: '待处理', tone: 'info' },
  unknown: { label: '状态未知', tone: 'warning' },
  expired: { label: '已过期', tone: 'warning' },
  revoked: { label: '已撤销', tone: 'warning' },
  warning: { label: '警告', tone: 'warning' },
  failed: { label: '失败', tone: 'danger' },
  error: { label: '错误', tone: 'danger' },
  banned: { label: '已封禁', tone: 'danger' },
  locked: { label: '已锁定', tone: 'danger' },
  deleted: { label: '已删除', tone: 'neutral' },
  exhausted: { label: '已用完', tone: 'warning' }
}

const TONE_ICONS: Record<StatusTone, Component> = {
  success: CircleCheck,
  warning: AlertTriangle,
  danger: CircleX,
  info: InfoCircle,
  neutral: Minus
}

const resolved = computed<Preset>(() => {
  if (props.label || props.tone) {
    return { label: props.label ?? props.status, tone: props.tone ?? 'neutral' }
  }
  return PRESETS[props.status.toLowerCase()] ?? { label: props.status, tone: 'neutral' }
})
const icon = computed(() => TONE_ICONS[resolved.value.tone])
</script>

<template>
  <span class="status-badge" :data-tone="resolved.tone">
    <NIcon class="status-icon" :component="icon" :aria-label="resolved.label" />
    <span class="status-label">{{ resolved.label }}</span>
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: var(--font-size-caption);
  line-height: var(--line-height-caption);
  font-weight: 600;
  white-space: nowrap;
}
.status-icon { font-size: 13px; flex-shrink: 0; }
.status-badge[data-tone='success'] { background: var(--accent-soft); color: var(--accent); }
.status-badge[data-tone='warning'] { background: var(--warning-soft); color: var(--warning); }
.status-badge[data-tone='danger'] { background: var(--danger-soft); color: var(--danger); }
.status-badge[data-tone='info'] { background: var(--info-soft); color: var(--info); }
.status-badge[data-tone='neutral'] { background: var(--neutral-soft); color: var(--text-secondary); }
</style>
