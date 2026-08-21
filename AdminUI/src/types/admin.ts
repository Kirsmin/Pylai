export interface AdminCapabilityEndpoint {
  method: string
  path: string
}

export interface AdminCapability {
  key: string
  name: string
  description: string
  route: string
  canEditGroup: boolean
  canEditStatus: boolean
  targetGroups: string[]
  endpoints: AdminCapabilityEndpoint[]
}

export interface AdminCapabilityUser {
  uid: string
  name: string
  displayName: string | null
  email: string | null
  group: string
}

export interface AdminCapabilitiesResponse {
  user: AdminCapabilityUser | null
  capabilities: AdminCapability[]
}

export interface AdminUserListItem {
  uid: string
  name: string
  displayName: string | null
  email: string | null
  group: string
  status: string
  registerTime: string
  lastLoginAt: string | null
}

export interface AdminUserTokenUsageItem {
  id: number
  tokenPrefix: string
  occurredAt: string
  method: string
  endpoint: string
  ipAddress: string | null
  userAgent: string | null
}

export interface AdminUserTokenInfo {
  exists: boolean
  tokenPrefix: string | null
  createdAt: string | null
  refreshedAt: string | null
  expiresAt: string | null
  lastUsedAt: string | null
  lastIpAddress: string | null
  totalUsage: number
  usage: AdminUserTokenUsageItem[]
}

export interface AdminUserDetail extends AdminUserListItem {
  lockoutEnd: string | null
  accessFailedCount: number
  activeSessions: number
  externalLogins: Array<{
    provider: string
    providerDisplayName: string | null
    boundAt: string
  }>
  token: AdminUserTokenInfo | null
}

export interface AdminUserSession {
  id: number
  createdAt: string
  expiresAt: string
  ipAddress: string | null
  userAgent: string | null
  active: boolean
}

export interface AdminUserListResponse {
  total: number
  users: AdminUserListItem[]
}

export interface AdminUserDetailResponse {
  user: AdminUserDetail | null
}

export interface AdminUserSessionsResponse {
  sessions: AdminUserSession[]
}

export interface AdminInviteCode {
  id: string
  prefix: string
  group: string
  maxRedemptions: number
  usedCount: number
  status: string
  expiresAt: string
  usedBy?: Array<{ uid: string; name: string; displayName: string | null }>
}

export interface AdminInviteCodeCreateResponse {
  id: string
  code: string
  prefix: string
  group: string
  maxRedemptions: number
  expiresAt: string
  saveWarning: string
}

export interface AdminInviteCodeListResponse {
  total: number
  codes: AdminInviteCode[]
}

export interface AdminInviteCodeDetailResponse {
  code: AdminInviteCode | null
}

export interface AdminBanInfo {
  banId: string
  type: string
  ip: string | null
  userUid: string | null
  userName: string | null
  failureCount: number
  banExpires: string | null
}

export interface AdminBanHistoryItem {
  id: number
  banId: string
  type: string
  ip: string
  bannedAt: string
  banExpiresAt: string
  unbannedAt: string | null
}

export interface AdminAuditLogItem {
  id: number
  eventType: string
  userId: string | null
  userEmail: string | null
  endpoint: string | null
  method: string | null
  ipAddress: string | null
  success: boolean
  timestamp: string
  details: string | null
}

export interface AdminClientItem {
  id: string
  clientId: string
  displayName: string
  description: string | null
  homepageUrl: string | null
  isFajorCertified: boolean
  isDisabled: boolean
  hasLogo: boolean
  type: string
  scopes: string[]
  redirectUris: string[]
  postLogoutRedirectUris: string[]
  grantTypes: string[]
  permissions: string[]
}
