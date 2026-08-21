using System.ComponentModel.DataAnnotations;
using System.Text.Json.Serialization;

namespace Pylaios.Features.Admin;

public class AdminResetPasswordRequest
{
    [Required]
    [StringLength(128, MinimumLength = 12)]
    public string NewPassword { get; set; } = string.Empty;
}

public class AdminUserUpdateRequest
{
    private DateTimeOffset? _lockoutEnd;

    public string? DisplayName { get; set; }
    public string? Email { get; set; }
    public string? Status { get; set; }
    public string? Group { get; set; }
    public DateTimeOffset? LockoutEnd
    {
        get => _lockoutEnd;
        set
        {
            _lockoutEnd = value;
            LockoutEndSpecified = true;
        }
    }

    [JsonIgnore]
    public bool LockoutEndSpecified { get; private set; }
}

public class AdminUserCreateRequest
{
    [Required]
    public string Email { get; set; } = string.Empty;
    public string? Name { get; set; }
    public string? DisplayName { get; set; }
    public string Group { get; set; } = AuthConstants.Roles.Normal;
    public string? Password { get; set; }
}

public class InviteCodeBanInfo
{
    public string Ip { get; set; } = string.Empty;
    public int FailureCount { get; set; }
    public string? BanExpires { get; set; }
    public string? BanId { get; set; }
}

public class AdminUserListItem
{
    public Guid Uid { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? DisplayName { get; set; }
    public string? Email { get; set; }
    public string Group { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public string RegisterTime { get; set; } = string.Empty;
    public string? LastLoginAt { get; set; }
}

public class AdminUserListResponse : ApiResponse
{
    public int Total { get; set; }
    public List<AdminUserListItem> Users { get; set; } = [];
}

public class AdminUserDetail : AdminUserListItem
{
    public DateTimeOffset? LockoutEnd { get; set; }
    public int AccessFailedCount { get; set; }
    public int ActiveSessions { get; set; }
    public List<AdminUserExternalLogin> ExternalLogins { get; set; } = [];
    public AdminUserTokenInfo? Token { get; set; }
}

public class AdminUserExternalLogin
{
    public string Provider { get; set; } = string.Empty;
    public string? ProviderDisplayName { get; set; }
    public string BoundAt { get; set; } = string.Empty;
}

public class AdminUserTokenInfo
{
    public bool Exists { get; set; }
    public string? TokenPrefix { get; set; }
    public DateTimeOffset? CreatedAt { get; set; }
    public DateTimeOffset? RefreshedAt { get; set; }
    public DateTimeOffset? ExpiresAt { get; set; }
    public DateTimeOffset? LastUsedAt { get; set; }
    public string? LastIpAddress { get; set; }
    public int TotalUsage { get; set; }
    public List<AdminUserTokenUsageItem> Usage { get; set; } = [];
}

public class AdminUserTokenUsageItem
{
    public long Id { get; set; }
    public string TokenPrefix { get; set; } = string.Empty;
    public string OccurredAt { get; set; } = string.Empty;
    public string Method { get; set; } = string.Empty;
    public string Endpoint { get; set; } = string.Empty;
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }
}

public class AdminUserDetailResponse : ApiResponse
{
    public AdminUserDetail? User { get; set; }
}

public class AdminUserSessionInfo
{
    public long Id { get; set; }
    public string CreatedAt { get; set; } = string.Empty;
    public string ExpiresAt { get; set; } = string.Empty;
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }
    public bool Active { get; set; }
}

public class AdminUserSessionsResponse : ApiResponse
{
    public List<AdminUserSessionInfo> Sessions { get; set; } = [];
}

public class AdminInviteCodeCreateRequest
{
    [Required]
    public string Group { get; set; } = string.Empty;
    public int? MaxRedemptions { get; set; }
    public int? LifetimeHours { get; set; }
}

public class AdminInviteCodeUpdateRequest
{
    public int? MaxRedemptions { get; set; }
    public DateTimeOffset? ExpiresAt { get; set; }
    public bool? Revoked { get; set; }
}

public class AdminInviteCodeListItem
{
    public Guid Id { get; set; }
    public string Prefix { get; set; } = string.Empty;
    public string Group { get; set; } = string.Empty;
    public int MaxRedemptions { get; set; }
    public int UsedCount { get; set; }
    public string Status { get; set; } = string.Empty;
    public DateTimeOffset ExpiresAt { get; set; }
}

public class AdminInviteCodeListResponse : ApiResponse
{
    public int Total { get; set; }
    public List<AdminInviteCodeListItem> Codes { get; set; } = [];
}

public class AdminInviteCodeDetail : AdminInviteCodeListItem
{
    public List<AdminInviteCodeRedemption> UsedBy { get; set; } = [];
}

public class AdminInviteCodeRedemption
{
    public Guid Uid { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? DisplayName { get; set; }
}

public class AdminInviteCodeDetailResponse : ApiResponse
{
    public AdminInviteCodeDetail? Code { get; set; }
}

public class AdminInviteCodeCreateResponse : ApiResponse
{
    public Guid Id { get; set; }
    public string? Code { get; set; }
    public string Prefix { get; set; } = string.Empty;
    public string Group { get; set; } = string.Empty;
    public int MaxRedemptions { get; set; }
    public DateTimeOffset ExpiresAt { get; set; }
    public string SaveWarning { get; set; } = "请立即保存，此后无法再次查看完整邀请码。";
}

public class AdminInviteCodeRevokeRequest
{
    [Required]
    public List<Guid> Ids { get; set; } = [];
}

public class AdminBanInfo
{
    public string BanId { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty;
    public string? Ip { get; set; }
    public Guid? UserUid { get; set; }
    public string? UserName { get; set; }
    public int FailureCount { get; set; }
    public string? BanExpires { get; set; }
}

public class AdminBanListResponse : ApiResponse
{
    public int Total { get; set; }
    public List<AdminBanInfo> Bans { get; set; } = [];
}

public class AdminBanHistoryItem
{
    public long Id { get; set; }
    public string BanId { get; set; } = string.Empty;
    public string Type { get; set; } = string.Empty;
    public string Ip { get; set; } = string.Empty;
    public string BannedAt { get; set; } = string.Empty;
    public string BanExpiresAt { get; set; } = string.Empty;
    public string? UnbannedAt { get; set; }
}

public class AdminBanHistoryResponse : ApiResponse
{
    public int Total { get; set; }
    public List<AdminBanHistoryItem> Bans { get; set; } = [];
}

public class AdminAuditLogItem
{
    public long Id { get; set; }
    public string EventType { get; set; } = string.Empty;
    public string? UserId { get; set; }
    public string? UserEmail { get; set; }
    public string? Endpoint { get; set; }
    public string? Method { get; set; }
    public string? IpAddress { get; set; }
    public bool Success { get; set; }
    public string Timestamp { get; set; } = string.Empty;
    public string? Details { get; set; }
}

public class AdminAuditLogListResponse : ApiResponse
{
    public int Total { get; set; }
    public List<AdminAuditLogItem> Logs { get; set; } = [];
}

public class AdminCapabilityEndpoint
{
    public string Method { get; set; } = string.Empty;
    public string Path { get; set; } = string.Empty;
}

public class AdminCapability
{
    public string Key { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
    public string Route { get; set; } = string.Empty;
    public bool CanEditGroup { get; set; }
    public bool CanEditStatus { get; set; }
    public List<string> TargetGroups { get; set; } = [];
    public List<AdminCapabilityEndpoint> Endpoints { get; set; } = [];
}

public class AdminCapabilityUser
{
    public Guid Uid { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? DisplayName { get; set; }
    public string? Email { get; set; }
    public string Group { get; set; } = string.Empty;
}

public class AdminCapabilitiesResponse : ApiResponse
{
    public AdminCapabilityUser? User { get; set; }
    public List<AdminCapability> Capabilities { get; set; } = [];
}
