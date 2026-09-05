using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Account;

[ApiController]
[Route("api/auth")]
[Authorize(AuthenticationSchemes = "Identity.Application,UserToken")]
public class SessionController : ControllerBase
{
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly IpResolutionService _ipResolver;
    private readonly SignInManager<User> _signInManager;
    private readonly MainConfig _config;
    private readonly IRedisStateCache _stateCache;
    private readonly ILogger<SessionController> _logger;

    public SessionController(
        ApplicationDbContext context,
        IAuditService auditService,
        IpResolutionService ipResolver,
        SignInManager<User> signInManager,
        MainConfig config,
        IRedisStateCache stateCache,
        ILogger<SessionController> logger)
    {
        _context = context;
        _auditService = auditService;
        _ipResolver = ipResolver;
        _signInManager = signInManager;
        _config = config;
        _stateCache = stateCache;
        _logger = logger;
    }

    [HttpPost("logout")]
    public async Task<IActionResult> Logout()
    {
        var user = await this.GetCurrentUserAsync(_context);

        var sessionCookie = Request.Cookies[_config.Cookie.SessionName];
        if (!string.IsNullOrEmpty(sessionCookie) && user is not null)
        {
            var tokenHash = AuthHelper.HashCode(sessionCookie);
            await _context.UserSessions
                .Where(s => s.TokenHash == tokenHash && s.UserUid == user.Uid && s.RevokedAt == null)
                .ExecuteUpdateAsync(setters => setters.SetProperty(s => s.RevokedAt, DateTimeOffset.UtcNow));
            await SessionCacheInvalidator.InvalidateSessionAsync(_stateCache, tokenHash);
        }

        await _signInManager.SignOutAsync();
        Response.Cookies.Delete(_config.Cookie.SessionName);

        if (user is not null)
        {
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.Logout, user.Uid.ToString(), user.Email, true);
            _logger.LogInformation("用户登出 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);
        }

        return Ok(new { Success = true });
    }

    [HttpGet("account/sessions")]
    public async Task<IActionResult> ListSessions()
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
            return Unauthorized(new { Success = false, Error = "未登录或登录已失效。", ErrorCode = "unauthorized" });

        var sessions = await _context.UserSessions
            .Where(s => s.UserUid == user.Uid && s.RevokedAt == null && s.ExpiresAt > DateTimeOffset.UtcNow)
            .OrderByDescending(s => s.CreatedAt)
            .Select(s => new
            {
                s.Id,
                s.CreatedAt,
                s.ExpiresAt,
                s.IpAddress,
                s.UserAgent
            })
            .ToListAsync();

        return Ok(new { Success = true, Sessions = sessions });
    }

    [HttpDelete("account/sessions/{id:long}")]
    public async Task<IActionResult> RevokeSession(long id)
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
            return Unauthorized(new { Success = false, Error = "未登录或登录已失效。", ErrorCode = "unauthorized" });

        var session = await _context.UserSessions
            .FirstOrDefaultAsync(s => s.Id == id && s.UserUid == user.Uid && s.RevokedAt == null);

        if (session is null)
            return NotFound(new { Success = false, Error = "会话不存在或已失效。", ErrorCode = "not_found" });

        session.RevokedAt = DateTimeOffset.UtcNow;
        await _context.SaveChangesAsync();
        await SessionCacheInvalidator.InvalidateSessionAsync(_stateCache, session.TokenHash);

        _logger.LogInformation("会话已注销 | uid:{Uid} | session:{Id}", user.Uid, id);

        return Ok(new { Success = true });
    }

    [HttpDelete("account/sessions")]
    public async Task<IActionResult> RevokeAllSessions()
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
            return Unauthorized(new { Success = false, Error = "未登录或登录已失效。", ErrorCode = "unauthorized" });

        var affected = await _context.RevokeAllSessionsAsync(user.Uid);
        await SessionCacheInvalidator.InvalidateUserSessionsAsync(_stateCache, _context, user.Uid);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.SessionsRevokedAll, user.Uid.ToString(), user.Email, true, $"Revoked {affected} sessions");

        _logger.LogInformation("全部会话已注销 | uid:{Uid} | 数量:{Count}", user.Uid, affected);

        return Ok(new { Success = true, RevokedCount = affected });
    }

}
