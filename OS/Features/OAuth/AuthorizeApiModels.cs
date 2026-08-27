namespace Pylaios.Features.OAuth;

internal static class ConsentState
{
    public static readonly TimeSpan PendingTtl = TimeSpan.FromMinutes(5);
    public static string Key(string requestId) => $"consent:{requestId}";
}

public class AuthorizeRequestInfoResponse : ApiResponse
{
    public string DisplayName { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? HomepageUrl { get; set; }
    public bool IsFajorCertified { get; set; }
    public string? LogoUrl { get; set; }
    public List<ScopeInfo> Scopes { get; set; } = [];
    public List<string> ExistingScopes { get; set; } = [];
    public AuthorizeUserInfo? User { get; set; }
}

public class ScopeInfo
{
    public string Name { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string Description { get; set; } = string.Empty;
}

public class AuthorizeUserInfo
{
    public Guid Uid { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? DisplayName { get; set; }
    public string? Email { get; set; }
    public string Group { get; set; } = string.Empty;
}

public class AuthorizeConsentRequest
{
    public string RequestId { get; set; } = string.Empty;
    public bool Approved { get; set; }
    public AltchaPayload? Altcha { get; set; }
}

public class AuthorizeConsentResponse : ApiResponse
{
    public string? RedirectUrl { get; set; }
}

internal class PendingAuthorizeRequest
{
    public required string ClientId { get; set; }
    public required string RedirectUri { get; set; }
    public required string Scope { get; set; }
    public string? State { get; set; }
    public required string ResponseType { get; set; }
    public string? CodeChallenge { get; set; }
    public string? CodeChallengeMethod { get; set; }
    public string? Nonce { get; set; }
    public required string UserId { get; set; }
    public required string ApplicationId { get; set; }
    public required string ApplicationName { get; set; }
    public string? Description { get; set; }
    public string? HomepageUrl { get; set; }
    public bool IsFajorCertified { get; set; }
    public List<PendingScope> Scopes { get; set; } = [];
    public bool Approved { get; set; }
}

internal class PendingScope
{
    public required string Name { get; set; }
    public required string DisplayName { get; set; }
    public required string Description { get; set; }
}
