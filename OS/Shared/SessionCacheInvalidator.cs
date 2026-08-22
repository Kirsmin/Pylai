using Microsoft.EntityFrameworkCore;

namespace Pylaios.Shared;

public static class SessionCacheInvalidator
{
    public const string ValidPrefix = "session-valid:";

    public static async Task InvalidateSessionAsync(IRedisStateCache cache, string tokenHash)
    {
        try
        {
            await cache.RemoveAsync(ValidPrefix + tokenHash);
        }
        catch (Exception)
        {
            // 缓存删除失败不阻断业务：键将在 TTL 内自然过期
        }
    }

    public static async Task InvalidateUserSessionsAsync(IRedisStateCache cache, ApplicationDbContext db, Guid uid)
    {
        var tokenHashes = await db.UserSessions.AsNoTracking()
            .Where(s => s.UserUid == uid && s.RevokedAt == null)
            .Select(s => s.TokenHash)
            .ToListAsync();
        foreach (var tokenHash in tokenHashes)
            await InvalidateSessionAsync(cache, tokenHash);
    }
}
