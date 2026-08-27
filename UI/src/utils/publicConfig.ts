import { api } from '@/utils/api'
import { setRuntimeSupportEmail, type PublicConfig } from '@/types/api'

let publicConfigPromise: Promise<PublicConfig> | null = null
let publicConfigSnapshot: PublicConfig | null = null

export function getPublicConfigSnapshot(): PublicConfig | null {
  return publicConfigSnapshot
}

export function loadPublicConfig(): Promise<PublicConfig> {
  if (!publicConfigPromise) {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 3000)
    publicConfigPromise = api<PublicConfig>('/api/config/public', { signal: controller.signal })
      .then((config) => {
        const normalized: PublicConfig = {
          supportEmail: config.supportEmail?.trim() || '',
          requireInviteCode: config.requireInviteCode ?? false,
          altchaEnabled: config.altchaEnabled ?? true,
          cookieHttpOnly: config.cookieHttpOnly ?? true
        }
        publicConfigSnapshot = normalized
        setRuntimeSupportEmail(normalized.supportEmail)
        return normalized
      })
      .catch((err) => {
        publicConfigPromise = null
        throw err
      })
      .finally(() => clearTimeout(timeoutId))
  }
  return publicConfigPromise
}
