namespace Pylaios.Features.Registration;

public class EmailVerificationBlock : BanEntryBase
{
    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;
}
