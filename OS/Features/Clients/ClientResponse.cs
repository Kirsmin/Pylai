namespace Pylaios.Features.Clients;

public class ClientResponse
{
    public string Id { get; set; } = string.Empty;
    public string ClientId { get; set; } = string.Empty;
    public string DisplayName { get; set; } = string.Empty;
    public string? Description { get; set; }
    public string? HomepageUrl { get; set; }
    public bool IsFajorCertified { get; set; }
    public bool IsDisabled { get; set; }
    public bool HasLogo { get; set; }
    public string Type { get; set; } = string.Empty;
    public List<string> Scopes { get; set; } = [];
    public List<string> RedirectUris { get; set; } = [];
    public List<string> PostLogoutRedirectUris { get; set; } = [];
    public List<string> GrantTypes { get; set; } = [];
    public List<string> Permissions { get; set; } = [];
}

public class ClientListResponse
{
    public List<ClientResponse> Items { get; set; } = [];
    public int Total { get; set; }
}