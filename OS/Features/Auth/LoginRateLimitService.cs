using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Auth;

public interface ILoginRateLimitService
{
    Task<(bool IsBanned, string? BanId)> IsIpBannedAsync(string ipAddress);
    Task<string?> GetBanRemainingAsync(string ipAddress);
    Task<RecordFailureResult> RecordFailureAsync(string ipAddress);
    Task ClearFailuresAsync(string ipAddress);
    Task<bool> RevokeByBanIdAsync(string banId);
    Task<bool> RevokeByIpAsync(string ipAddress);
}




public class LoginRateLimitService : IpBanServiceBase<LoginFailure>, ILoginRateLimitService
{
    private readonly LoginRateLimitConfig _config;

    public LoginRateLimitService(
        ApplicationDbContext context,
        MainConfig config,
        IRateLimitCacheService cache,
        IpResolutionService ipResolver,
        ILogger<LoginRateLimitService> logger)
        : base(context, cache, ipResolver, logger)
    {
        _config = config.LoginRateLimit;
    }

    protected override string BanType => "login";
    protected override string BanAuditType => "Login";
    protected override string BanIdPrefix => "BlockLogin";

    protected override bool ShouldBan(LoginFailure entity)
        => entity.FailureCount >= _config.MaxFailuresPerIp;

    protected override TimeSpan? GetBanDuration(LoginFailure entity)
    {
        var minutes = _config.BanDurationMinutes[entity.BanLevel - 1];
        return minutes < 0 ? null : TimeSpan.FromMinutes(minutes);
    }

    protected override void PrepareBan(LoginFailure entity)
    {
        var level = Math.Min(entity.BanLevel + 1, _config.BanDurationMinutes.Length);
        entity.BanLevel = level;
    }

    protected override LoginFailure CreateEntry(string ipAddress, DateTimeOffset now)
        => new() { IpAddress = ipAddress, FailureCount = 1, LastFailureAt = now };

    protected override async Task OnBanExpiredAsync(LoginFailure entity, string ipAddress)
    {

        if (entity.BanLevel <= 0 || entity.BanLevel > _config.BanDurationMinutes.Length)
            return;

        if (DateTimeOffset.UtcNow - entity.LastFailureAt >= TimeSpan.FromDays(_config.CooldownDays))
        {
            entity.BanLevel--;
            _logger.LogDebug("登录IP封禁冷却降级 | {Ip} | 新等级:{Level}", ipAddress, entity.BanLevel);
            await _context.SaveChangesAsync();
            await _cache.ClearFailureAsync(BanType, ipAddress);
        }
    }


    public async Task ClearFailuresAsync(string ipAddress)
    {
        if (_ipResolver.IsWhitelisted(ipAddress))
            return;

        await _cache.ClearFailureAsync(BanType, ipAddress);

        await _context.LoginFailures
            .Where(f => f.IpAddress == ipAddress)
            .ExecuteUpdateAsync(s => s.SetProperty(f => f.FailureCount, 0));
    }
}
