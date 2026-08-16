namespace Pylaios.Features.Clients;

public class ClientCreateRequest
{
    public string ClientId { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string ClientSecret { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? HomepageUrl { get; set; }
    public bool IsFajorCertified { get; set; }
    public string Type { get; set; } = "Confidential";
    public List<string> Scopes { get; set; } = ["openid", "profile:basic", "profile:mail", "profile:role", "offline_access"];
    public List<string> RedirectUris { get; set; } = [];
    public List<string> PostLogoutRedirectUris { get; set; } = [];
    public List<string> GrantTypes { get; set; } = ["authorization_code", "refresh_token"];
    public List<string> Permissions { get; set; } = [];
}

public class ClientUpdateRequest
{
    public string? DisplayName { get; set; }
    public string? ClientSecret { get; set; }
    public string? Description { get; set; }
    public string? HomepageUrl { get; set; }
    public bool? IsFajorCertified { get; set; }
    public List<string>? Scopes { get; set; }
    public List<string>? RedirectUris { get; set; }
    public List<string>? PostLogoutRedirectUris { get; set; }
    public List<string>? GrantTypes { get; set; }
    public List<string>? Permissions { get; set; }
}