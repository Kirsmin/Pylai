using System.ComponentModel.DataAnnotations;

namespace Pylaios.Features.Users;

public class User
{
    [Key]
    public Guid Uid { get; set; } = Guid.NewGuid();

    [Required]
    public UserStatus Status { get; set; } = UserStatus.Active;

    [Required]
    [MaxLength(256)]
    public string Name { get; set; } = string.Empty;

    [MaxLength(256)]
    public string? DisplayName { get; set; }

    [Required]
    public string PasswordHash { get; set; } = string.Empty;

    [MaxLength(256)]
    public string? Email { get; set; }

    [MaxLength(256)]
    public string? NormalizedEmail { get; set; }

    public bool EmailConfirmed { get; set; } = true;

    [Required]
    [MaxLength(32)]
    public string Group { get; set; } = AuthConstants.Roles.Normal;

    public ICollection<UserLogin> UserLogins { get; set; } = new List<UserLogin>();

    public string? SecurityStamp { get; set; }

    public string? ConcurrencyStamp { get; set; } = Guid.NewGuid().ToString();

    public int AccessFailedCount { get; set; }

    /// <summary>
    /// 自动风控锁定的到期时间；当 Status=Locked 时则表示管理员锁定的可选到期时间，null 为永久锁定。
    /// </summary>
    public DateTimeOffset? LockoutEnd { get; set; }

    public DateTimeOffset RegisterTime { get; set; } = DateTimeOffset.UtcNow;

    public DateTimeOffset? LastLoginAt { get; set; }
}
