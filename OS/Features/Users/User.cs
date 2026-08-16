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

    [Required]
    [MaxLength(32)]
    public string Group { get; set; } = AuthConstants.Roles.Normal;

    public ICollection<UserLogin> UserLogins { get; set; } = new List<UserLogin>();

    public string? SecurityStamp { get; set; }

    public string? ConcurrencyStamp { get; set; } = Guid.NewGuid().ToString();

    public int AccessFailedCount { get; set; }

    public DateTimeOffset? LockoutEnd { get; set; }

    public DateTimeOffset RegisterTime { get; set; } = DateTimeOffset.UtcNow;

    public DateTimeOffset? LastLoginAt { get; set; }
}
