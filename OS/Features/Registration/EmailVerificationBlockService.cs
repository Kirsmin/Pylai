namespace Pylaios.Features.Registration;

public interface IEmailVerificationBlockService
{
    Task<(bool IsBanned, string? BanId)> IsIpBannedAsync(string ipAddress);
    Task<RecordFailureResult> BanNowAsync(string ipAddress);
    Task<bool> RevokeByBanIdAsync(string banId);
    Task<bool> RevokeByIpAsync(string ipAddress);
}

public class EmailVerificationBlockService : IpBanServiceBase<EmailVerificationBlock>, IEmailVerificationBlockService
{
    private readonly MainConfig _config;

    public EmailVerificationBlockService(
        ApplicationDbContext context,
        MainConfig config,
        IRateLimitCacheService cache,
        IpResolutionService ipResolver,
        ILogger<EmailVerificationBlockService> logger)
        : base(context, cache, ipResolver, logger)
    {
        _config = config;
    }

    protected override string BanType => "email";
    protected override string BanAuditType => "EmailVerify";
    protected override string BanIdPrefix => "BlockEmail";

    protected override bool ShouldBan(EmailVerificationBlock entity) => false;

    protected override TimeSpan? GetBanDuration(EmailVerificationBlock entity)
        => TimeSpan.FromHours(_config.InviteCode.EmailCodeBanDurationHours);

    protected override EmailVerificationBlock CreateEntry(string ipAddress, DateTimeOffset now)
        => new() { IpAddress = ipAddress, FailureCount = 0, LastFailureAt = now };
}
