using Microsoft.EntityFrameworkCore;

namespace Pylaios.Shared;

public record RecordFailureResult(bool JustBanned, string? BanId);





public abstract class IpBanServiceBase<T> where T : class, IIpBanEntry
{
    protected readonly ApplicationDbContext _context;
    protected readonly IRateLimitCacheService _cache;
    protected readonly IpResolutionService _ipResolver;
    protected readonly ILogger _logger;

    protected IpBanServiceBase(
        ApplicationDbContext context,
        IRateLimitCacheService cache,
        IpResolutionService ipResolver,
        ILogger logger)
    {
        _context = context;
        _cache = cache;
        _ipResolver = ipResolver;
        _logger = logger;
    }


    protected abstract string BanType { get; }


    protected abstract string BanAuditType { get; }


    protected abstract string BanIdPrefix { get; }


    protected virtual bool ResetFailureCountOnUnban => true;


    protected abstract bool ShouldBan(T entity);


    protected abstract TimeSpan? GetBanDuration(T entity);


    protected virtual void PrepareBan(T entity) { }


    protected virtual Task OnBanExpiredAsync(T entity, string ipAddress) => Task.CompletedTask;


    protected abstract T CreateEntry(string ipAddress, DateTimeOffset now);

    public async Task<(bool IsBanned, string? BanId)> IsIpBannedAsync(string ipAddress)
    {
        if (_ipResolver.IsWhitelisted(ipAddress))
            return (false, null);

        if (await _cache.IsBannedAsync(BanType, ipAddress))
        {
            var entry = await _context.Set<T>()
                .AsNoTracking()
                .FirstOrDefaultAsync(f => f.IpAddress == ipAddress);
            return (true, entry?.BanId);
        }

        var entity = await _context.Set<T>()
            .AsNoTracking()
            .FirstOrDefaultAsync(f => f.IpAddress == ipAddress);
        if (entity is null)
            return (false, null);

        if (entity.BanExpiresAt is not null && entity.BanExpiresAt > DateTimeOffset.UtcNow)
        {
            await _cache.SetBanAsync(BanType, ipAddress, entity.BanId!, entity.BanExpiresAt);
            return (true, entity.BanId);
        }

        if (entity.BanExpiresAt is not null)
            await RevokeAsync(entity);

        _context.Attach(entity);
        await OnBanExpiredAsync(entity, ipAddress);
        _context.Entry(entity).State = EntityState.Detached;
        return (false, null);
    }

    public async Task<string?> GetBanRemainingAsync(string ipAddress)
    {
        var entity = await _context.Set<T>()
            .AsNoTracking()
            .FirstOrDefaultAsync(f => f.IpAddress == ipAddress);
        if (entity?.BanExpiresAt is null)
            return null;

        var remaining = entity.BanExpiresAt.Value - DateTimeOffset.UtcNow;
        if (remaining <= TimeSpan.Zero)
        {
            await RevokeAsync(entity);
            return null;
        }

        await _cache.SetBanAsync(BanType, ipAddress, entity.BanId!, entity.BanExpiresAt);
        return remaining.ToString(@"hh\h\ mm\m\ ss\s");
    }

    public async Task<bool> RevokeByBanIdAsync(string banId)
    {
        var entry = await _context.Set<T>()
            .FirstOrDefaultAsync(f => f.BanId == banId);
        if (entry is null) return false;
        await RevokeAsync(entry);
        return true;
    }

    public async Task<bool> RevokeByIpAsync(string ipAddress)
    {
        var entry = await _context.Set<T>()
            .FirstOrDefaultAsync(f => f.IpAddress == ipAddress && f.BanId != null);
        if (entry is null) return false;
        await RevokeAsync(entry);
        return true;
    }

    public async Task RevokeAsync(T entry)
    {
        await using var tx = await _context.Database.BeginTransactionAsync();

        _context.Attach(entry);
        entry.BanExpiresAt = null;
        entry.BanId = null;
        if (ResetFailureCountOnUnban)
            entry.FailureCount = 0;

        var audit = await _context.IpBanAudits
            .Where(a => a.IpAddress == entry.IpAddress && a.BanType == BanAuditType && a.UnbannedAt == null)
            .FirstOrDefaultAsync();
        if (audit is not null)
            audit.UnbannedAt = DateTimeOffset.UtcNow;

        await _context.SaveChangesAsync();
        await tx.CommitAsync();
        _context.Entry(entry).State = EntityState.Detached;

        await _cache.ClearBanAsync(BanType, entry.IpAddress);
        await _cache.ClearFailureAsync(BanType, entry.IpAddress);
    }

    public async Task<RecordFailureResult> BanNowAsync(string ipAddress)
    {
        var now = DateTimeOffset.UtcNow;
        var existing = await _context.Set<T>()
            .AsNoTracking()
            .FirstOrDefaultAsync(f => f.IpAddress == ipAddress);

        var entity = existing ?? CreateEntry(ipAddress, now);
        if (existing is null)
            _context.Set<T>().Add(entity);

        return await ApplyBanAsync(entity, ipAddress);
    }

    public async Task<RecordFailureResult> RecordFailureAsync(string ipAddress)
    {
        var now = DateTimeOffset.UtcNow;
        await _cache.IncrementFailureAsync(BanType, ipAddress);

        await using var tx = await _context.Database.BeginTransactionAsync();

        var rows = await _context.Set<T>()
            .Where(f => f.IpAddress == ipAddress)
            .ExecuteUpdateAsync(s => s
                .SetProperty(f => f.FailureCount, f => f.FailureCount + 1)
                .SetProperty(f => f.LastFailureAt, now));

        if (rows == 0)
        {
            var entry = CreateEntry(ipAddress, now);
            _context.Set<T>().Add(entry);
            try
            {
                await _context.SaveChangesAsync();
            }
            catch (DbUpdateException)
            {
                await tx.RollbackAsync();
                await using var retryTx = await _context.Database.BeginTransactionAsync();
                await _context.Set<T>()
                    .Where(f => f.IpAddress == ipAddress)
                    .ExecuteUpdateAsync(s => s
                        .SetProperty(f => f.FailureCount, f => f.FailureCount + 1)
                        .SetProperty(f => f.LastFailureAt, now));
                await retryTx.CommitAsync();
                return new RecordFailureResult(false, null);
            }
        }

        await tx.CommitAsync();
        await tx.DisposeAsync();


        var entity = await _context.Set<T>()
            .AsNoTracking()
            .FirstOrDefaultAsync(f => f.IpAddress == ipAddress);
        if (entity is null)
            return new RecordFailureResult(false, null);

        await _cache.SetFailureCountAsync(BanType, ipAddress, entity.FailureCount, entity.LastFailureAt);

        if (ShouldBan(entity) && entity.BanId is null)
        {
            return await ApplyBanAsync(entity, ipAddress);
        }

        return new RecordFailureResult(false, null);
    }

    private async Task<RecordFailureResult> ApplyBanAsync(T entity, string ipAddress)
    {
        await using var banTx = await _context.Database.BeginTransactionAsync();



        if (_context.Entry(entity).State == EntityState.Detached)
            _context.Attach(entity);
        PrepareBan(entity);
        var duration = GetBanDuration(entity);

        var banId = BanIdPrefix + Guid.NewGuid().ToString("N");
        DateTimeOffset? banExpiresAt = duration is null ? null : DateTimeOffset.UtcNow.Add(duration.Value);

        entity.BanId = banId;
        entity.BanExpiresAt = banExpiresAt;

        _context.IpBanAudits.Add(new IpBanAudit
        {
            BanId = banId,
            IpAddress = ipAddress,
            BanType = BanAuditType,
            BannedAt = DateTimeOffset.UtcNow,
            BanExpiresAt = banExpiresAt ?? DateTimeOffset.MaxValue
        });

        _logger.LogWarning("IP封禁({Type}) | {Ip} | BanId:{BanId} | 失败次数:{Count}",
            BanAuditType, ipAddress, banId, entity.FailureCount);

        await _context.SaveChangesAsync();
        await banTx.CommitAsync();

        _context.Entry(entity).State = EntityState.Detached;

        await _cache.SetBanAsync(BanType, ipAddress, banId, banExpiresAt);
        return new RecordFailureResult(true, banId);
    }
}
