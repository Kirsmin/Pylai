namespace Pylaios.Features.Clients;

public class OAuthClientMetadata
{
    public string ApplicationId { get; set; } = string.Empty;
    public string? Description { get; set; }
    public byte[]? Logo { get; set; }
    public string? LogoContentType { get; set; }
    public string? HomepageUrl { get; set; }
    public bool IsFajorCertified { get; set; }
    public bool IsDisabled { get; set; }
}
