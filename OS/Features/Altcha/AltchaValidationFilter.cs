using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using System.Text.Json;

namespace Pylaios.Features.Altcha;

[AttributeUsage(AttributeTargets.Method | AttributeTargets.Class, AllowMultiple = false)]
public class RequireAltchaAttribute : TypeFilterAttribute
{
    public RequireAltchaAttribute() : base(typeof(AltchaValidationFilter)) { }
}

public class AltchaValidationFilter : IAsyncActionFilter
{
    public async Task OnActionExecutionAsync(ActionExecutingContext ctx, ActionExecutionDelegate next)
    {
        var svc = ctx.HttpContext.RequestServices.GetRequiredService<IAltchaService>();
        var cfg = ctx.HttpContext.RequestServices.GetRequiredService<MainConfig>();
        var audit = ctx.HttpContext.RequestServices.GetService<IAuditService>();
        var ipResolver = ctx.HttpContext.RequestServices.GetService<IpResolutionService>();

        if (!cfg.Altcha.Enabled)
        {
            await next();
            return;
        }

        var payload = ExtractPayload(ctx);
        string? err = null;
        if (payload is null || !svc.VerifyPayload(payload, out err))
        {
            var ip = ipResolver?.GetClientIp(ctx.HttpContext) ?? "unknown";
            if (audit is not null)
            {
                await audit.LogAsync(new AuditLog
                {
                    EventType = AuthConstants.EventTypes.AltchaFailure,
                    UserId = null,
                    UserEmail = null,
                    IpAddress = ip,
                    Success = false,
                    Details = $"error={err ?? "missing_payload"}",
                    UserAgent = ctx.HttpContext.Request.Headers.UserAgent.ToString(),
                    Endpoint = ctx.HttpContext.Request.Path.Value ?? "/",
                    Method = ctx.HttpContext.Request.Method
                });
            }

            ctx.Result = new ObjectResult(new { Success = false, Error = "验证失败，请刷新页面重试。", ErrorCode = "altcha_invalid" })
            { StatusCode = 403 };
            return;
        }

        await next();
    }

    private static AltchaPayload? ExtractPayload(ActionExecutingContext ctx)
    {
        foreach (var arg in ctx.ActionArguments.Values)
        {
            if (arg is null) continue;
            var prop = arg.GetType().GetProperty("Altcha", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.IgnoreCase);
            if (prop is not null && prop.PropertyType == typeof(AltchaPayload))
            {
                var val = prop.GetValue(arg) as AltchaPayload;
                if (val is not null) return val;
            }
        }

        var header = ctx.HttpContext.Request.Headers["X-Altcha-Payload"].FirstOrDefault();
        if (!string.IsNullOrEmpty(header))
        {
            try
            {
                return JsonSerializer.Deserialize<AltchaPayload>(header, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            }
            catch { /* ignore */ }
        }

        var formOrQuery = ctx.HttpContext.Request.Query["altcha"].FirstOrDefault();
        if (ctx.HttpContext.Request.HasFormContentType)
        {
            formOrQuery = ctx.HttpContext.Request.Form["altcha"].FirstOrDefault() ?? formOrQuery;
        }
        if (!string.IsNullOrEmpty(formOrQuery))
        {
            try
            {
                return JsonSerializer.Deserialize<AltchaPayload>(formOrQuery, new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            }
            catch { /* ignore */ }
        }

        return null;
    }
}
