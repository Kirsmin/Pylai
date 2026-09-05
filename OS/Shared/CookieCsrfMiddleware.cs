using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Pylaios.Shared;

/// <summary>
/// 用户侧 API 的 Cookie-CSRF 防护（与 Admin BFF 同一双提交模式）：
/// 凡经 Identity.Application Cookie 认证发起的状态修改请求（POST/PUT/PATCH/DELETE），
/// 必须携带 X-CSRF-Token 头并与 Pylaios.Csrf Cookie 常量时间比对；匿名与 Bearer UserToken 路径豁免。
/// /api/admin/* 由 AdminBffCsrfMiddleware 单独管辖；token 由 GET /api/auth/csrf 签发。
/// </summary>
public sealed class CookieCsrfMiddleware
{
    public const string CsrfCookieName = "Pylaios.Csrf";
    private const string HeaderName = "X-CSRF-Token";
    private readonly RequestDelegate _next;

    public CookieCsrfMiddleware(RequestDelegate next)
    {
        _next = next;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var path = context.Request.Path;
        if (path.StartsWithSegments("/api")
            && !path.StartsWithSegments("/api/admin")
            && !path.StartsWithSegments("/api/auth/csrf")
            && IsUnsafeMethod(context.Request.Method)
            && context.User.Identities.Any(i => i.AuthenticationType == Microsoft.AspNetCore.Identity.IdentityConstants.ApplicationScheme)
            && !IsValidToken(context.Request))
        {
            context.Response.StatusCode = StatusCodes.Status403Forbidden;
            context.Response.ContentType = "application/json; charset=utf-8";
            await context.Response.WriteAsync(JsonSerializer.Serialize(new
            {
                success = false,
                error = "安全校验未通过，请刷新页面后重试。",
                errorCode = "csrf_invalid"
            }));
            return;
        }

        await _next(context);
    }

    private static bool IsUnsafeMethod(string method)
        => HttpMethods.IsPost(method) || HttpMethods.IsPut(method)
            || HttpMethods.IsPatch(method) || HttpMethods.IsDelete(method);

    private static bool IsValidToken(HttpRequest request)
    {
        if (!request.Cookies.TryGetValue(CsrfCookieName, out var cookie) || string.IsNullOrEmpty(cookie))
            return false;

        var header = request.Headers[HeaderName].FirstOrDefault();
        return !string.IsNullOrEmpty(header)
            && CryptographicOperations.FixedTimeEquals(
                Encoding.UTF8.GetBytes(cookie),
                Encoding.UTF8.GetBytes(header));
    }
}
