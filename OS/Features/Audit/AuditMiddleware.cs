using System.Security.Claims;

namespace Pylaios.Features.Audit;

public class AuditMiddleware
{
    private readonly RequestDelegate _next;

    private static readonly string[] AuditedPaths =
    [
        "/connect/authorize",
        "/connect/token",
        "/connect/userinfo",
        "/connect/logout",
        "/connect/introspect",
        "/connect/revoke",
        "/.well-known"
    ];

    public AuditMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var shouldAudit = Array.Exists(AuditedPaths,
            p => context.Request.Path.StartsWithSegments(p, StringComparison.OrdinalIgnoreCase));

        if (!shouldAudit)
        {
            await _next(context);
            return;
        }

        var auditService = context.RequestServices.GetRequiredService<IAuditService>();

        var entry = new AuditLog
        {
            Endpoint = context.Request.Path.Value ?? "/",
            Method = context.Request.Method,
            IpAddress = context.RequestServices.GetRequiredService<IpResolutionService>().GetClientIp(context),
            UserAgent = context.Request.Headers.UserAgent.ToString(),
            Timestamp = DateTimeOffset.UtcNow
        };

        await _next(context);

        entry.StatusCode = context.Response.StatusCode;
        entry.Success = context.Response.StatusCode is >= 200 and < 400;

        if (context.User?.Identity?.IsAuthenticated == true)
        {
            entry.UserId = context.User.FindFirstValue(OpenIddict.Abstractions.OpenIddictConstants.Claims.Subject)
                        ?? context.User.FindFirstValue(ClaimTypes.NameIdentifier);
            entry.UserEmail = context.User.FindFirstValue(OpenIddict.Abstractions.OpenIddictConstants.Claims.Email)
                          ?? context.User.FindFirstValue(ClaimTypes.Email);
        }

        if (context.Request.HasFormContentType)
        {
            var clientId = context.Request.Form["client_id"].FirstOrDefault();
            if (!string.IsNullOrEmpty(clientId))
                entry.ClientId = clientId;
        }

        var path = context.Request.Path.Value ?? "";

        if (path.Contains("/token", StringComparison.OrdinalIgnoreCase))
        {
            var grantType = context.Request.HasFormContentType
                ? context.Request.Form["grant_type"].FirstOrDefault()
                : context.Request.Query["grant_type"].FirstOrDefault();
            entry.EventType = grantType switch
            {
                "authorization_code" => AuthConstants.EventTypes.TokenIssued,
                "refresh_token" => AuthConstants.EventTypes.TokenRefreshed,
                "client_credentials" => AuthConstants.EventTypes.ClientCredentialsToken,
                _ => AuthConstants.EventTypes.TokenRequest
            };
        }
        else if (path.Contains("/authorize", StringComparison.OrdinalIgnoreCase))
            entry.EventType = context.Response.StatusCode == 302 ? AuthConstants.EventTypes.AuthorizeRedirect : AuthConstants.EventTypes.Authorize;
        else if (path.Contains("/logout", StringComparison.OrdinalIgnoreCase))
            entry.EventType = AuthConstants.EventTypes.Logout;
        else if (path.Contains("/userinfo", StringComparison.OrdinalIgnoreCase))
            entry.EventType = AuthConstants.EventTypes.UserInfo;
        else if (path.Contains("/introspect", StringComparison.OrdinalIgnoreCase))
            entry.EventType = AuthConstants.EventTypes.Introspect;
        else if (path.Contains("/revoke", StringComparison.OrdinalIgnoreCase))
            entry.EventType = AuthConstants.EventTypes.Revoke;
        else if (path.Contains("/.well-known", StringComparison.OrdinalIgnoreCase))
            entry.EventType = AuthConstants.EventTypes.Discovery;
        else
            entry.EventType = AuthConstants.EventTypes.ApiCall;

        await auditService.LogAsync(entry);
    }
}
