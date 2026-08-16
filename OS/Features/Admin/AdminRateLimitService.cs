using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Admin;

public interface IAdminRateLimitService
{
    Task<(bool IsBanned, string? BanId)> IsIpBannedAsync(string ipAddress);
    Task<RecordFailureResult> RecordFailureAsync(string ipAddress);
    Task<bool> RevokeByBanIdAsync(string banId);
    Task<bool> RevokeByIpAsync(string ipAddress);
}




public class AdminRateLimitService : IpBanServiceBase<AdminAuthFailure>, IAdminRateLimitService
{
    private readonly AdminRateLimitConfig _config;

    public AdminRateLimitService(
        ApplicationDbContext context,
        MainConfig config,
        IRateLimitCacheService cache,
        IpResolutionService ipResolver,
        ILogger<AdminRateLimitService> logger)
        : base(context, cache, ipResolver, logger)
    {
        _config = config.AdminRateLimit;
    }

    protected override string BanType => "admin";
    protected override string BanAuditType => "AdminAuth";
    protected override string BanIdPrefix => "BlockAdmin";


    protected override bool ResetFailureCountOnUnban => false;

    protected override bool ShouldBan(AdminAuthFailure entity)
        => entity.FailureCount >= _config.MaxFailuresFirstBan;

    protected override TimeSpan? GetBanDuration(AdminAuthFailure entity)
        => entity.FailureCount >= _config.MaxFailuresSecondBan
            ? TimeSpan.FromHours(_config.SecondBanDurationHours)
            : TimeSpan.FromSeconds(_config.FirstBanDurationSeconds);

    protected override AdminAuthFailure CreateEntry(string ipAddress, DateTimeOffset now)
        => new() { IpAddress = ipAddress, FailureCount = 1, LastFailureAt = now };
}
