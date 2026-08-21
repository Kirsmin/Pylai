export const STATUS_LABELS: Record<string, string> = {
  active: '正常',
  banned: '封禁',
  locked: '锁定',
  deleted: '已删除'
}

export const GROUP_LABELS: Record<string, string> = {
  normal: '普通用户',
  admin: '管理员',
  max: '超级管理员'
}

export const BAN_TYPE_LABELS: Record<string, string> = {
  login: '登录',
  invite: '邀请码',
  email: '邮箱验证',
  admin: '管理后台',
  confirm: '敏感操作'
}

export const INVITE_STATUS_LABELS: Record<string, string> = {
  active: '可用',
  revoked: '已撤销'
}

const label = (map: Record<string, string>, value: string) => map[value.toLowerCase()] || value

export const statusLabel = (value: string) => label(STATUS_LABELS, value)
export const groupLabel = (value: string) => label(GROUP_LABELS, value)
export const banTypeLabel = (value: string) => label(BAN_TYPE_LABELS, value)
export const inviteStatusLabel = (value: string) => label(INVITE_STATUS_LABELS, value)
