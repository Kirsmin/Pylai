using System.ComponentModel.DataAnnotations;

namespace Pylaios.Features.UserTokens;

public class UserTokenCreateRequest
{
    [Required]
    public string Password { get; set; } = string.Empty;

    /// <summary>正数=有效天数；0=永不过期；不传=使用配置默认值。</summary>
    public int? LifetimeDays { get; set; }
}

public class UserTokenQueryRequest
{
    [Required]
    public string Password { get; set; } = string.Empty;

    public int Skip { get; set; }
    public int Take { get; set; } = 20;
}

public class UserTokenRevokeRequest
{
    [Required]
    public string Password { get; set; } = string.Empty;
}

public class UserTokenCreateResponse : ApiResponse
{
    public string? Token { get; set; }
    public string? TokenPrefix { get; set; }
    public bool Refreshed { get; set; }
    public DateTimeOffset? CreatedAt { get; set; }
    public DateTimeOffset? ExpiresAt { get; set; }
}

public class UserTokenStatusDto
{
    public bool Exists { get; set; }
    public string? TokenPrefix { get; set; }
    public DateTimeOffset? CreatedAt { get; set; }
    public DateTimeOffset? RefreshedAt { get; set; }
    public DateTimeOffset? ExpiresAt { get; set; }
    public DateTimeOffset? LastUsedAt { get; set; }
    public string? LastIpAddress { get; set; }
    public List<UserTokenUsageDto> Usage { get; set; } = [];
    public int TotalUsage { get; set; }
}

public class UserTokenUsageDto
{
    public long Id { get; set; }
    public string TokenPrefix { get; set; } = string.Empty;
    public string OccurredAt { get; set; } = string.Empty;
    public string Method { get; set; } = string.Empty;
    public string Endpoint { get; set; } = string.Empty;
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }
}

public class UserTokenQueryResponse : ApiResponse
{
    public UserTokenStatusDto? Token { get; set; }
}

public class UserTokenRevokeResponse : ApiResponse
{
    public bool Revoked { get; set; }
}
