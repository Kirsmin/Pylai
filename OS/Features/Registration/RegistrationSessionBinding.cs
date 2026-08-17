namespace Pylaios.Features.Registration;

public sealed class RegistrationSessionBinding
{
    public string SessionTokenHash { get; set; } = string.Empty;
    public Guid UserUid { get; set; }
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
}
