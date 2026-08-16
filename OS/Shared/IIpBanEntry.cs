using System.ComponentModel.DataAnnotations;

namespace Pylaios.Shared;

public interface IIpBanEntry
{
    string IpAddress { get; set; }
    int FailureCount { get; set; }
    DateTimeOffset? BanExpiresAt { get; set; }
    string? BanId { get; set; }
    DateTimeOffset LastFailureAt { get; set; }
}

public abstract class BanEntryBase : IIpBanEntry
{
    [Key]
    [MaxLength(45)]
    public string IpAddress { get; set; } = string.Empty;

    public int FailureCount { get; set; }

    public DateTimeOffset? BanExpiresAt { get; set; }

    [MaxLength(128)]
    public string? BanId { get; set; }

    public DateTimeOffset LastFailureAt { get; set; } = DateTimeOffset.UtcNow;
}
