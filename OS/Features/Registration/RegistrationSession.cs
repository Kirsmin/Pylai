namespace Pylaios.Features.Registration;

public class RegistrationSession
{
    public int Step { get; set; } = 1;
    public string? InviteCode { get; set; }
    public string? InviteCodeType { get; set; }
    public string? NormalizedName { get; set; }
    public string? DisplayName { get; set; }
    public Guid? UserUid { get; set; }
    public int EmailChangeCount { get; set; }
    public int EmailCodeAttempts { get; set; }
    public string? EmailCodeHash { get; set; }
    public DateTimeOffset? EmailCodeExpires { get; set; }
    public string? PendingEmail { get; set; }
    public bool Completed { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
}
