using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;

namespace Pylaios.Shared;

public interface IUserAccessRevoker
{
    /// <summary>
    /// 吊销用户全部访问凭据：Cookie 会话、OAuth token/authorization、UserToken。
    /// manageTransaction=false 时由调用方提供外层事务。
    /// </summary>
    Task RevokeUserAccessAsync(Guid uid, bool revokeUserToken = true, bool manageTransaction = true);
}

public sealed class UserAccessRevoker : IUserAccessRevoker
{
    private readonly ApplicationDbContext _context;
    private readonly IOpenIddictTokenManager _tokenManager;
    private readonly IOpenIddictAuthorizationManager _authorizationManager;
    private readonly ILogger<UserAccessRevoker> _logger;

    public UserAccessRevoker(
        ApplicationDbContext context,
        IOpenIddictTokenManager tokenManager,
        IOpenIddictAuthorizationManager authorizationManager,
        ILogger<UserAccessRevoker> logger)
    {
        _context = context;
        _tokenManager = tokenManager;
        _authorizationManager = authorizationManager;
        _logger = logger;
    }

    public async Task RevokeUserAccessAsync(Guid uid, bool revokeUserToken = true, bool manageTransaction = true)
    {
        if (manageTransaction)
        {
            await using var tx = await _context.Database.BeginTransactionAsync();
            await RevokeCoreAsync(uid, revokeUserToken);
            await tx.CommitAsync();
            return;
        }

        await RevokeCoreAsync(uid, revokeUserToken);
    }

    private async Task RevokeCoreAsync(Guid uid, bool revokeUserToken)
    {
        var now = DateTimeOffset.UtcNow;
        var subject = uid.ToString();

        var user = await _context.Users.FindAsync(uid);
        if (user is not null)
            user.SecurityStamp = Guid.NewGuid().ToString();

        await _context.UserSessions
            .Where(s => s.UserUid == uid && s.RevokedAt == null)
            .ExecuteUpdateAsync(setters => setters.SetProperty(s => s.RevokedAt, now));

        if (revokeUserToken)
        {
            await _context.UserTokens
                .Where(t => t.UserUid == uid && t.RevokedAt == null)
                .ExecuteUpdateAsync(setters => setters.SetProperty(t => t.RevokedAt, now));
        }

        await _tokenManager.RevokeBySubjectAsync(subject);
        await _authorizationManager.RevokeBySubjectAsync(subject);

        await _context.SaveChangesAsync();
        _logger.LogInformation("用户访问凭据已全部吊销 | uid:{Uid}", uid);
    }
}
