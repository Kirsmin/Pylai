using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Pylaios.Features.Account;




public class UserLogin
{
    public Guid UserUid { get; set; }

    [Required]
    [MaxLength(128)]
    public string LoginProvider { get; set; } = string.Empty;

    [Required]
    [MaxLength(512)]
    public string ProviderKey { get; set; } = string.Empty;

    [MaxLength(128)]
    public string? ProviderDisplayName { get; set; }

    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;

    [ForeignKey(nameof(UserUid))]
    public User User { get; set; } = null!;
}
