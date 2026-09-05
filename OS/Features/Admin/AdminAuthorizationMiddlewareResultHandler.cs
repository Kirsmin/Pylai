using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Authorization.Policy;

namespace Pylaios.Features.Admin;

/// <summary>
/// 管理 API（/api/admin、/api/clients）授权结果处理：
/// - 认证失败（Bearer UserToken/OAuth access_token 无效）→ 写入 AdminAuthFailures（IP 限流封禁）并返回 401 JSON；
/// - 认证成功但权限不足 → 返回 403 JSON；
/// - 其他路径保持 ASP.NET Core 默认行为。
/// </summary>
public class AdminAuthorizationMiddlewareResultHandler : IAuthorizationMiddlewareResultHandler
{
    private readonly IAuthorizationMiddlewareResultHandler _defaultHandler = new AuthorizationMiddlewareResultHandler();

    public async Task HandleAsync(
        RequestDelegate next,
        HttpContext context,
        AuthorizationPolicy policy,
        PolicyAuthorizationResult authorizeResult)
    {
        if (!context.Request.Path.StartsWithSegments("/api"))
        {
            await _defaultHandler.HandleAsync(next, context, policy, authorizeResult);
            return;
        }

        var isManagementPath = AdminApiIpBanMiddleware.IsManagementPath(context.Request.Path);

        if (authorizeResult.Challenged)
        {
            var authHeader = context.Request.Headers.Authorization.ToString();
            if (isManagementPath
                && !string.IsNullOrEmpty(authHeader) && authHeader.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase)
                && context.User.Identity?.IsAuthenticated != true)
            {
                var rateLimit = context.RequestServices.GetRequiredService<IAdminRateLimitService>();
                var auditService = context.RequestServices.GetRequiredService<IAuditService>();
                var ipResolver = context.RequestServices.GetRequiredService<IpResolutionService>();
                var logger = context.RequestServices.GetRequiredService<ILogger<AdminAuthorizationMiddlewareResultHandler>>();

                var ip = ipResolver.GetClientIp(context);
                await rateLimit.RecordFailureAsync(ip);

                await auditService.LogAsync(new AuditLog
                {
                    EventType = AuthConstants.EventTypes.AdminAuthFailed,
                    Endpoint = context.Request.Path.Value ?? "/",
                    Method = context.Request.Method,
                    IpAddress = ip,
                    UserAgent = context.Request.Headers.UserAgent.ToString(),
                    Success = false,
                    Details = "Bearer authentication failed"
                });

                logger.LogWarning("管理 API Bearer 认证失败 | IP:{Ip} | Path:{Path}", ip, context.Request.Path);
            }

            context.Response.StatusCode = 401;
            context.Response.ContentType = "application/json";
            await context.Response.WriteAsync("""{"success":false,"error":"未登录或登录已失效。","errorCode":"unauthorized"}""");
            return;
        }

        if (authorizeResult.Forbidden)
        {
            context.Response.StatusCode = 403;
            context.Response.ContentType = "application/json";
            await context.Response.WriteAsync("""{"success":false,"error":"没有权限执行此操作。","errorCode":"forbidden"}""");
            return;
        }

        await _defaultHandler.HandleAsync(next, context, policy, authorizeResult);
    }
}
