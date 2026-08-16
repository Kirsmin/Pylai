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

    public SessionValidationMiddleware(RequestDelegate next, MainConfig config)
    {
        _next = next;
        _sessionCookieName = config.Cookie.SessionName;
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

            var uid = context.User.FindFirstValue(OpenIddictConstants.Claims.Subject)
                   ?? context.User.FindFirstValue(ClaimTypes.NameIdentifier);

            var dbContext = context.RequestServices.GetRequiredService<ApplicationDbContext>();


            var tokenHash = AuthHelper.HashCode(sessionCookie);
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
