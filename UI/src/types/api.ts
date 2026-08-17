export const SUPPORT_EMAIL = (import.meta.env.VITE_SUPPORT_EMAIL as string | undefined)?.trim() || ''

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
