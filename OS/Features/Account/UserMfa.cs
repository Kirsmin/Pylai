namespace Pylaios.Features.Account;

public sealed class UserMfaSettings
{
    public Guid UserUid { get; set; }
    public bool TotpEnabled { get; set; }
    public string? EncryptedTotpSecret { get; set; }
    public DateTimeOffset? LastVerifiedAt { get; set; }
    public long? LastTotpCounter { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset UpdatedAt { get; set; } = DateTimeOffset.UtcNow;
}

public sealed class WebAuthnCredential
{
    public long Id { get; set; }
    public Guid UserUid { get; set; }
    public byte[] CredentialId { get; set; } = [];
    public byte[] PublicKey { get; set; } = [];
    public uint SignCount { get; set; }
    public string? Transports { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? LastUsedAt { get; set; }
}
