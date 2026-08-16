using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Confirmation;

public interface IConfirmationRateLimitService
{
    Task<bool> IsLockedAsync(Guid userUid);
    Task<string?> GetBanRemainingAsync(Guid userUid);
    Task<(int AttemptsRemaining, bool JustLocked, string? BanId, string? BanRemaining)> RecordFailureAsync(Guid userUid);
    Task ClearFailuresAsync(Guid userUid);
    Task<bool> RevokeByBanIdAsync(string banId);
    Task<bool> RevokeByUserAsync(Guid userUid);
    Task<List<ConfirmationBanInfo>> GetActiveBansAsync();
}

public class ConfirmationBanInfo
{
    public Guid UserUid { get; set; }
    public string? UserName { get; set; }
    public string? DisplayName { get; set; }
    public int FailureCount { get; set; }
    public DateTimeOffset? BanExpiresAt { get; set; }
    public string? BanId { get; set; }
}

public class ConfirmationRateLimitService : IConfirmationRateLimitService
{
    private readonly ApplicationDbContext _context;
    private readonly ConfirmationRateLimitConfig _config;
    private readonly ILogger<ConfirmationRateLimitService> _logger;

    public ConfirmationRateLimitService(
        ApplicationDbContext context,
        MainConfig config,
        ILogger<ConfirmationRateLimitService> logger)
    {
        _context = context;
        _config = config.ConfirmationRateLimit;
        _logger = logger;
    }

    public async Task<bool> IsLockedAsync(Guid userUid)
    {
        var entity = await _context.ConfirmationFailures
            .AsNoTracking()
            .FirstOrDefaultAsync(f => f.UserUid == userUid);
        if (entity?.BanExpiresAt is null)
            return false;

        if (entity.BanExpiresAt > DateTimeOffset.UtcNow)
            return true;

        await ClearFailuresAsync(userUid);
        return false;
    }

    public async Task<string?> GetBanRemainingAsync(Guid userUid)
    {
        var entity = await _context.ConfirmationFailures
            .AsNoTracking()
            .FirstOrDefaultAsync(f => f.UserUid == userUid);
        if (entity?.BanExpiresAt is null)
            return null;

        var remaining = entity.BanExpiresAt.Value - DateTimeOffset.UtcNow;
        return remaining > TimeSpan.Zero ? remaining.ToString(@"hh\h\ mm\m\ ss\s") : null;
    }

    public async Task<(int AttemptsRemaining, bool JustLocked, string? BanId, string? BanRemaining)> RecordFailureAsync(Guid userUid)
    {
        var now = DateTimeOffset.UtcNow;
        var existing = await _context.ConfirmationFailures.AsNoTracking()
            .FirstOrDefaultAsync(f => f.UserUid == userUid);

        if (existing is null)
        {
            var insert = new ConfirmationFailure { UserUid = userUid, FailureCount = 1, LastFailureAt = now };
            _context.ConfirmationFailures.Add(insert);
            try
            {
                await _context.SaveChangesAsync();
            }
            catch (DbUpdateException ex) when (ex.IsUniqueViolation())
            {
                _context.Entry(insert).State = EntityState.Detached;
                await _context.ConfirmationFailures
                    .Where(f => f.UserUid == userUid)
                    .ExecuteUpdateAsync(setters => setters
                        .SetProperty(f => f.FailureCount, f => f.FailureCount + 1)
                        .SetProperty(f => f.LastFailureAt, now));
            }
        }
        else
        {
            if (existing.BanExpiresAt is not null && existing.BanExpiresAt <= now)
            {
                await _context.ConfirmationFailures
                    .Where(f => f.UserUid == userUid)
                    .ExecuteUpdateAsync(setters => setters
                        .SetProperty(f => f.FailureCount, 0)
                        .SetProperty(f => f.BanId, (string?)null)
                        .SetProperty(f => f.BanExpiresAt, (DateTimeOffset?)null));
            }

            await _context.ConfirmationFailures
                .Where(f => f.UserUid == userUid)
                .ExecuteUpdateAsync(setters => setters
                    .SetProperty(f => f.FailureCount, f => f.FailureCount + 1)
                    .SetProperty(f => f.LastFailureAt, now));
        }

        var entity = await _context.ConfirmationFailures.AsNoTracking()
            .FirstOrDefaultAsync(f => f.UserUid == userUid);
        if (entity is null)
            return (Math.Max(0, _config.MaxFailures - 1), false, null, null);

        if (entity.FailureCount >= _config.MaxFailures && entity.BanId is null)
        {
            var banId = "BlockConfirm" + Guid.NewGuid().ToString("N");
            var banExpiresAt = now.AddHours(_config.BanDurationHours);
            var banned = await _context.ConfirmationFailures
                .Where(f => f.UserUid == userUid && f.BanId == null && f.FailureCount >= _config.MaxFailures)
                .ExecuteUpdateAsync(setters => setters
                    .SetProperty(f => f.BanId, banId)
                    .SetProperty(f => f.BanExpiresAt, banExpiresAt));

            if (banned > 0)
            {
                _logger.LogWarning("特殊功能确认操作已锁定 | uid:{Uid} | 失败次数:{Count} | 解除:{Unlock}",
                    userUid, entity.FailureCount, banExpiresAt);
                return (0, true, banId, _config.BanDurationHours + "h");
            }
        }

        return (Math.Max(0, _config.MaxFailures - entity.FailureCount), false, null, null);
    }

    public async Task ClearFailuresAsync(Guid userUid)
    {
        var entity = await _context.ConfirmationFailures.FirstOrDefaultAsync(f => f.UserUid == userUid);
        if (entity is null)
            return;

        entity.FailureCount = 0;
        entity.BanId = null;
        entity.BanExpiresAt = null;
        await _context.SaveChangesAsync();
    }

    public async Task<bool> RevokeByBanIdAsync(string banId)
    {
        var entity = await _context.ConfirmationFailures.FirstOrDefaultAsync(f => f.BanId == banId);
        if (entity is null)
            return false;

        entity.FailureCount = 0;
        entity.BanId = null;
        entity.BanExpiresAt = null;
        await _context.SaveChangesAsync();
        return true;
    }

    public async Task<bool> RevokeByUserAsync(Guid userUid)
    {
        var entity = await _context.ConfirmationFailures.FirstOrDefaultAsync(f => f.UserUid == userUid);
        if (entity is null || entity.BanId is null)
            return false;

        entity.FailureCount = 0;
        entity.BanId = null;
        entity.BanExpiresAt = null;
        await _context.SaveChangesAsync();
        return true;
    }

    public async Task<List<ConfirmationBanInfo>> GetActiveBansAsync()
    {
        var now = DateTimeOffset.UtcNow;
        return await _context.ConfirmationFailures
            .Where(f => f.BanId != null && (f.BanExpiresAt == null || f.BanExpiresAt > now))
            .Join(_context.Users, f => f.UserUid, u => u.Uid, (f, u) => new ConfirmationBanInfo
            {
                UserUid = f.UserUid,
                UserName = u.Name,
                DisplayName = u.DisplayName,
                FailureCount = f.FailureCount,
                BanExpiresAt = f.BanExpiresAt,
                BanId = f.BanId
            })
            .ToListAsync();
    }
}
