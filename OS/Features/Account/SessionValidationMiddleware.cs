using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;

namespace Pylaios.Features.Account;






public class SessionValidationMiddleware
{
    private readonly RequestDelegate _next;
    private readonly string _sessionCookieName;
    private readonly ILogger<SessionValidationMiddleware> _logger;

    public SessionValidationMiddleware(RequestDelegate next, MainConfig config, ILogger<SessionValidationMiddleware> logger)
    {
        _next = next;
        _sessionCookieName = config.Cookie.SessionName;
        _logger = logger;
    }

    public async Task InvokeAsync(HttpContext context)
    {

        if (context.User.Identity?.IsAuthenticated == true
            && string.Equals(context.User.Identity.AuthenticationType,
                IdentityConstants.ApplicationScheme, StringComparison.Ordinal))
        {
            var sessionCookie = context.Request.Cookies[_sessionCookieName];
            if (string.IsNullOrEmpty(sessionCookie))
            {

                await SignOutAndRejectAsync(context, "Session cookie missing.");
                return;
            }

            var tokenHash = AuthHelper.HashCode(sessionCookie);
            var cacheKey = SessionCacheInvalidator.ValidPrefix + tokenHash;
            var stateCache = context.RequestServices.GetRequiredService<IRedisStateCache>();

            if (await stateCache.GetAsync<bool>(cacheKey))
            {
                await _next(context);
                return;
            }

            try
            {
                var uid = context.User.FindFirstValue(OpenIddictConstants.Claims.Subject)
                       ?? context.User.FindFirstValue(ClaimTypes.NameIdentifier);

                var dbContext = context.RequestServices.GetRequiredService<ApplicationDbContext>();

                var session = await dbContext.UserSessions
                    .FirstOrDefaultAsync(s => s.TokenHash == tokenHash
                        && s.RevokedAt == null
                        && s.ExpiresAt > DateTimeOffset.UtcNow);

                if (session is null
                    || (uid is not null && session.UserUid.ToString() != uid))
                {
                    await SignOutAndRejectAsync(context, "Session expired or revoked.");
                    return;
                }

                try
                {
                    await stateCache.SetAsync(cacheKey, true, TimeSpan.FromSeconds(60));
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "会话验证结果写入缓存失败 | tokenHash:{Hash}", tokenHash[..8]);
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "会话验证数据库查询失败，拒绝放行 | tokenHash:{Hash}", tokenHash[..8]);
                await SignOutAndRejectAsync(context, "Session validation failed.");
                return;
            }
        }

        await _next(context);
    }

    private static async Task SignOutAndRejectAsync(HttpContext context, string reason)
    {
        var signInManager = context.RequestServices.GetRequiredService<SignInManager<User>>();
        await signInManager.SignOutAsync();
        var sessionName = context.RequestServices.GetRequiredService<MainConfig>().Cookie.SessionName;
        context.Response.Cookies.Delete(sessionName);

        await context.SignOutAsync(IdentityConstants.ApplicationScheme);

        context.Response.StatusCode = 401;
        context.Response.ContentType = "application/json";
        await context.Response.WriteAsync("""{"success":false,"error":"Session expired or revoked.","errorCode":"session_invalid"}""");
    }
}
