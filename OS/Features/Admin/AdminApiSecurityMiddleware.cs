using Microsoft.AspNetCore.Http;

namespace Pylaios.Features.Admin;

/// <summary>
/// 管理 API 前置守卫：/api/admin、/api/clients 等管理路径在进入认证前先检查
/// AdminAuthFailures IP 封禁（UserToken/OAuth 认证失败统一封禁）。
/// </summary>
public class AdminApiIpBanMiddleware
{
    private readonly RequestDelegate _next;

    public AdminApiIpBanMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context, IAdminRateLimitService rateLimit, IpResolutionService ipResolver, ILogger<AdminApiIpBanMiddleware> logger)
    {
        if (!IsManagementPath(context.Request.Path))
        {
            await _next(context);
            return;
        }

        var ip = ipResolver.GetClientIp(context);
        var (banned, _) = await rateLimit.IsIpBannedAsync(ip);
        if (banned)
        {
            logger.LogWarning("管理 API IP 已封禁 | IP:{Ip} | Path:{Path}", ip, context.Request.Path);
            context.Response.StatusCode = 401;
            context.Response.ContentType = "application/json";
            await context.Response.WriteAsync("""{"success":false,"error":"Unauthorized","errorCode":"unauthorized"}""");
            return;
        }

        await _next(context);
    }

    internal static bool IsManagementPath(PathString path)
        => path.StartsWithSegments("/api/admin") || path.StartsWithSegments("/api/clients");
}

