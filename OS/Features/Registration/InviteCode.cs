namespace Pylaios.Features.Registration;




public class InviteCode
{
    public Guid Id { get; set; } = Guid.NewGuid();

    // Only the HMAC and the first three characters are persisted.
    public string CodeHash { get; set; } = string.Empty;

    public string Prefix { get; set; } = string.Empty;

    public string Group { get; set; } = AuthConstants.Roles.Normal;

    public int MaxRedemptions { get; set; } = 10;

    public int UsedCount { get; set; }

    public List<string> UsedBy { get; set; } = [];

    public InviteCodeStatus Status { get; set; } = InviteCodeStatus.Active;

    public DateTimeOffset ExpiresAt { get; set; }
}

public enum InviteCodeStatus
{
    Active,
    Revoked
}
