using System.Text.Json;

namespace Pylaios.Features.Admin;

public sealed class AdminBffCsrfMiddleware
{
    private readonly RequestDelegate _next;
    private readonly MainConfig _config;

    public AdminBffCsrfMiddleware(RequestDelegate next, MainConfig config)
    {
        _next = next;
        _config = config;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        if (context.Request.Path.StartsWithSegments("/api/admin")
            && !context.Request.Path.StartsWithSegments("/api/admin/bff")
            && context.Request.Cookies.ContainsKey(_config.Cookie.Name)
            && !AdminBffController.IsValidCsrf(context.Request))
        {
            context.Response.StatusCode = StatusCodes.Status403Forbidden;
            context.Response.ContentType = "application/json; charset=utf-8";
            await context.Response.WriteAsync(JsonSerializer.Serialize(new
            {
                success = false,
                error = "CSRF token missing or invalid.",
                errorCode = "csrf_invalid"
            }));
            return;
        }

        await _next(context);
    }
}
