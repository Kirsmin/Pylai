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

    public static async Task<User?> FindUserAsync(this ControllerBase controller, ApplicationDbContext context, string usernameOrEmail)
    {
        var normalized = UsernameNormalizer.Normalize(usernameOrEmail);
        return await context.Users.FirstOrDefaultAsync(
            u => (u.Name == normalized || (u.NormalizedEmail != null && u.NormalizedEmail == normalized))
                && u.Status != UserStatus.Deleted);
    }

    public static async Task<IActionResult?> RequireMfaStepUpAsync(
        this ControllerBase controller,
        IMfaService mfa,
        ApplicationDbContext context)
    {
        if (controller.User.FindFirst("auth_scheme")?.Value == LocalManageToken.Scheme)
            return null;

        var user = await controller.GetCurrentUserAsync(context);
        if (user is null)
            return new UnauthorizedObjectResult(new { success = false, error = "Unauthorized.", errorCode = "unauthorized" });

        if (AuthConstants.Groups.Rank(user.Group) < AuthConstants.Groups.Rank(AuthConstants.Roles.Admin))
            return null;

        if (await mfa.HasRecentStepUpAsync(user.Uid))
            return null;

        return new ObjectResult(new { success = false, error = "敏感操作需要 MFA 二次验证。", errorCode = "mfa_step_up_required" })
        {
            StatusCode = StatusCodes.Status403Forbidden
        };
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
