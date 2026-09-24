using Microsoft.EntityFrameworkCore;
using OpenIddict.EntityFrameworkCore.Models;

namespace Pylaios.Shared;

public interface IUserHardDeleter
{
    /// <summary>
    /// 物理删除用户及其全部关联数据（会话 / UserToken / MFA / 外部登录 / OAuth 授权等），不可恢复。
    /// 用户名与邮箱唯一约束随记录删除立即释放，可被重新注册；审计日志为字符串引用，保留。
    /// </summary>
    Task HardDeleteAsync(Guid uid);
}

public sealed class UserHardDeleter : IUserHardDeleter
{
    private readonly ApplicationDbContext _context;
    private readonly IRedisStateCache _stateCache;
    private readonly ILogger<UserHardDeleter> _logger;

    public UserHardDeleter(
        ApplicationDbContext context,
        IRedisStateCache stateCache,
        ILogger<UserHardDeleter> logger)
    {
        _context = context;
        _stateCache = stateCache;
        _logger = logger;
    }

    public async Task HardDeleteAsync(Guid uid)
    {
        // Redis 会话缓存先行失效（缓存删除失败不阻断，键在 TTL 内自然过期）
        await SessionCacheInvalidator.InvalidateUserSessionsAsync(_stateCache, _context, uid);

        var subject = uid.ToString();
        await using var tx = await _context.Database.BeginTransactionAsync();

        // OAuth token / 授权（Subject 字符串引用，无 FK；先 token 后 authorization 避免 FK 冲突）
        await _context.Set<OpenIddictEntityFrameworkCoreToken>()
            .Where(t => t.Subject == subject)
            .ExecuteDeleteAsync();
        await _context.Set<OpenIddictEntityFrameworkCoreAuthorization>()
            .Where(a => a.Subject == subject)
            .ExecuteDeleteAsync();

        // UserToken 使用记录 → UserToken（无 FK，需显式删除）
        var tokenIds = await _context.UserTokens
            .Where(t => t.UserUid == uid)
            .Select(t => t.Id)
            .ToListAsync();
        if (tokenIds.Count > 0)
            await _context.UserTokenUsages.Where(u => tokenIds.Contains(u.UserTokenId)).ExecuteDeleteAsync();
        await _context.UserTokens.Where(t => t.UserUid == uid).ExecuteDeleteAsync();

        // 其余关联数据（部分表 DB 层有级联，显式删除保证不依赖隐式行为）
        await _context.UserSessions.Where(s => s.UserUid == uid).ExecuteDeleteAsync();
        await _context.UserLogins.Where(l => l.UserUid == uid).ExecuteDeleteAsync();
        await _context.UserMfaSettings.Where(m => m.UserUid == uid).ExecuteDeleteAsync();
        await _context.WebAuthnCredentials.Where(c => c.UserUid == uid).ExecuteDeleteAsync();
        await _context.RegistrationSessionBindings.Where(b => b.UserUid == uid).ExecuteDeleteAsync();
        await _context.ConfirmationFailures.Where(c => c.UserUid == uid).ExecuteDeleteAsync();

        await _context.Users.Where(u => u.Uid == uid).ExecuteDeleteAsync();

        await tx.CommitAsync();
        _logger.LogInformation("用户已硬删除 | uid:{Uid}", uid);
    }
}
