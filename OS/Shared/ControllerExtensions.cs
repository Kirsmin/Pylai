using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Shared;

public static class ControllerExtensions
{
    public static string GetClientIp(this ControllerBase controller, IpResolutionService ipResolver)
    {
        return ipResolver.GetClientIp(controller.HttpContext);
    }





    public static async Task<UserSession> CreateUserSessionAsync(
        this ControllerBase controller,
        ApplicationDbContext context,
        User user,
        string ip,
        string sessionCookieName)
    {
        var sessionToken = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(32));
        var session = new UserSession
        {
            UserUid = user.Uid,
            TokenHash = AuthHelper.HashCode(sessionToken),
            CreatedAt = DateTimeOffset.UtcNow,
            ExpiresAt = DateTimeOffset.UtcNow.AddDays(14),
            IpAddress = ip,
            UserAgent = controller.HttpContext.Request.Headers.UserAgent.ToString()
        };
        context.UserSessions.Add(session);
        await context.SaveChangesAsync();


        var services = controller.HttpContext.RequestServices;
        var secure = CookieSecurity.IsSecure(
            services.GetRequiredService<Microsoft.AspNetCore.Hosting.IWebHostEnvironment>(),
            services.GetRequiredService<MainConfig>(),
            controller.HttpContext);

        controller.Response.Cookies.Append(sessionCookieName, sessionToken, new CookieOptions
        {
            HttpOnly = true,
            Secure = secure,
            SameSite = SameSiteMode.Lax,
            Expires = DateTimeOffset.UtcNow.AddDays(14)
        });

        return session;
    }

    public static async Task<User?> GetCurrentUserAsync(this ControllerBase controller, ApplicationDbContext context)
    {
        var uidClaim = controller.User.FindFirst(System.Security.Claims.ClaimTypes.NameIdentifier)?.Value
                    ?? controller.User.FindFirst("sub")?.Value;

        if (uidClaim is not null && Guid.TryParse(uidClaim, out var uid))
            return await context.Users.FirstOrDefaultAsync(u => u.Uid == uid && u.Status == UserStatus.Active);

        var nameClaim = controller.User.FindFirst(System.Security.Claims.ClaimTypes.Name)?.Value;
        if (!string.IsNullOrEmpty(nameClaim))
            return await context.Users.FirstOrDefaultAsync(u => u.Name == nameClaim && u.Status == UserStatus.Active);

        return null;
    }

    /// <summary>
    /// 要求已认证的活跃用户；未登录时返回统一 401（Account/Session/UserToken 控制器共用）。
    /// </summary>
    public static async Task<(User? User, IActionResult? Error)> RequireUserAsync(
        this ControllerBase controller, ApplicationDbContext context)
    {
        var user = await controller.GetCurrentUserAsync(context);
        return user is null
            ? (null, controller.Unauthorized(new { Success = false, Error = "未登录。", ErrorCode = "invalid_session" }))
            : (user, null);
    }

    public static async Task<User?> FindUserAsync(this ControllerBase controller, ApplicationDbContext context, string usernameOrEmail)
    {
        var normalized = UsernameNormalizer.Normalize(usernameOrEmail);
        return await context.Users.FirstOrDefaultAsync(
            u => (u.Name == normalized || (u.NormalizedEmail != null && u.NormalizedEmail == normalized))
                && u.Status != UserStatus.Deleted);
    }

    /// <summary>
    /// 当前请求凭据的 Step-Up 标识：Cookie 会话用 session token 哈希，UserToken 用令牌 ID。
    /// 返回 null 表示无法定位具体凭据（fail closed，不允许通过 Step-Up）。
    /// </summary>
    public static string? GetStepUpCredentialKey(this ControllerBase controller)
    {
        var config = controller.HttpContext.RequestServices.GetRequiredService<MainConfig>();
        var sessionCookie = controller.HttpContext.Request.Cookies[config.Cookie.SessionName];
        if (!string.IsNullOrEmpty(sessionCookie))
            return "sess:" + AuthHelper.HashCode(sessionCookie);

        var tokenId = controller.User.FindFirst("user_token_id")?.Value;
        if (!string.IsNullOrEmpty(tokenId))
            return "utok:" + tokenId;

        return null;
    }

    public static async Task<IActionResult?> RequireMfaStepUpAsync(
        this ControllerBase controller,
        IMfaService mfa,
        ApplicationDbContext context)
    {
        var user = await controller.GetCurrentUserAsync(context);
        if (user is null)
            return new UnauthorizedObjectResult(new { success = false, error = "Unauthorized.", errorCode = "unauthorized" });

        if (AuthConstants.Groups.Rank(user.Group) < AuthConstants.Groups.Rank(AuthConstants.Roles.Admin))
            return null;

        var credentialKey = controller.GetStepUpCredentialKey();
        if (credentialKey is null || !await mfa.HasCredentialStepUpVerifiedAsync(credentialKey))
        {
            // 账户未注册任何 MFA 方法时 step-up 无法完成（HTTP 部署下甚至无法注册），
            // 跳过要求并写审计留痕；已注册方法则维持强制。
            if (!await mfa.HasAnyCredentialAsync(user.Uid))
            {
                var services = controller.HttpContext.RequestServices;
                await controller.AuditAsync(
                    services.GetRequiredService<IAuditService>(),
                    services.GetRequiredService<IpResolutionService>(),
                    AuthConstants.EventTypes.MfaStepUpSkipped,
                    user.Uid.ToString(), user.Email, true,
                    "账户未注册任何 MFA 方法，敏感操作 MFA step-up 已跳过。");
                return null;
            }

            return new ObjectResult(new { success = false, error = "敏感操作需要 MFA 二次验证。", errorCode = "mfa_step_up_required" })
            {
                StatusCode = StatusCodes.Status403Forbidden
            };
        }

        return null;
    }

    public static Task<bool> IsEmailTakenAsync(this ApplicationDbContext context, string email)
    {
        var normalized = UsernameNormalizer.Normalize(email);
        return context.Users.AnyAsync(u => u.NormalizedEmail == normalized);
    }

    public static async Task RevokeAllSessionsAsync(this ControllerBase controller, ApplicationDbContext context, Guid uid)
    {
        await context.RevokeAllSessionsAsync(uid);
    }

    public static async Task AuditAsync(
        this ControllerBase controller,
        IAuditService auditService,
        IpResolutionService ipResolver,
        string eventType,
        string? userId,
        string? userEmail,
        bool success,
        string? details = null,
        string? sessionToken = null)
    {
        await auditService.LogAsync(new AuditLog
        {
            EventType = eventType,
            UserId = userId,
            UserEmail = userEmail,
            Endpoint = controller.HttpContext.Request.Path.Value ?? "/",
            Method = controller.HttpContext.Request.Method,
            IpAddress = ipResolver.GetClientIp(controller.HttpContext),
            UserAgent = controller.HttpContext.Request.Headers.UserAgent.ToString(),
            Success = success,
            Details = SensitiveDataRedactor.Redact(details)
        });
    }
}
