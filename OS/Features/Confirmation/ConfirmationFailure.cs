using System.ComponentModel.DataAnnotations;

namespace Pylaios.Features.Confirmation;

/// <summary>
/// 特殊功能密码二次验证失败追踪（账号级：每个用户一条，达到上限后 1 天内禁止所有特殊功能操作）。
/// </summary>
public class ConfirmationFailure
{
    [Key]
    public Guid UserUid { get; set; }

    public int FailureCount { get; set; }

    public DateTimeOffset? BanExpiresAt { get; set; }

    [MaxLength(128)]
    public string? BanId { get; set; }

    public DateTimeOffset LastFailureAt { get; set; } = DateTimeOffset.UtcNow;
}
