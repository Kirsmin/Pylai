namespace Pylaios.Features.OAuth;

public class ConsentAuditEvent
{
    public long Id { get; set; }

    public string Subject { get; set; } = string.Empty;

    public string ClientId { get; set; } = string.Empty;

    public string Action { get; set; } = string.Empty;

    public string? PreviousScopes { get; set; }

    public string? RequestedScopes { get; set; }

    public string? GrantedScopes { get; set; }

    public string? AuthorizationId { get; set; }

    public string? UserAgent { get; set; }

    public string? IpAddress { get; set; }

    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
}

public static class ConsentAuditActions
{
    public const string ConsentGranted = "ConsentGranted";
    public const string ConsentScopeMerged = "ConsentScopeMerged";
    public const string ConsentDenied = "ConsentDenied";
    public const string ApplicationRevoked = "ApplicationRevoked";
    public const string AuthorizationConsolidated = "AuthorizationConsolidated";
}
