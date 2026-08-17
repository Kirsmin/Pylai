namespace Pylaios.Features.Audit;

public class AuditLog
{
    public const int DetailsMaxLength = 4000;
    public const int UserAgentMaxLength = 1024;

    public long Id { get; set; }

    public string EventType { get; set; } = string.Empty;

    public string? UserId { get; set; }

    public string? UserEmail { get; set; }

    public string? ClientId { get; set; }

    public string? Endpoint { get; set; }

    public string? Method { get; set; }

    public string? IpAddress { get; set; }

    public string? UserAgent { get; set; }

    public bool Success { get; set; }

    public int? StatusCode { get; set; }

    public string? Details { get; set; }

    public DateTimeOffset Timestamp { get; set; } = DateTimeOffset.UtcNow;
}
