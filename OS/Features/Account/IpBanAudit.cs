using System.ComponentModel.DataAnnotations;

namespace Pylaios.Features.Account;

public class IpBanAudit
{
    [Key]
    public long Id { get; set; }

    [MaxLength(128)]
    public string BanId { get; set; } = string.Empty;

    [MaxLength(45)]
    public string IpAddress { get; set; } = string.Empty;

    [MaxLength(32)]
    public string BanType { get; set; } = string.Empty;

    public DateTimeOffset BannedAt { get; set; } = DateTimeOffset.UtcNow;

    public DateTimeOffset BanExpiresAt { get; set; }

    public DateTimeOffset? UnbannedAt { get; set; }
}
