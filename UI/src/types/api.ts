/** @deprecated Use loadPublicConfig().supportEmail; kept only for source compatibility. */
export let SUPPORT_EMAIL = ''

export function setRuntimeSupportEmail(value: string) {
  SUPPORT_EMAIL = value.trim()
}

export interface PublicConfig {
  supportEmail: string
  requireInviteCode: boolean
}

export interface ScopeInfo {
  name: string
  displayName: string
  description?: string
}

export interface PasswordPolicy {
  minLength: number
  requireDigit: boolean
  requireLowercase: boolean
  requireUppercase: boolean
  requireNonAlphanumeric: boolean
  adminMinLength?: number
  checkBreachedPasswords?: boolean
}
