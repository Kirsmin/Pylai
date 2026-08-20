using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;

namespace Pylaios.Shared;

/// <summary>
/// Normalizes uncaught API failures without exposing exception details.
/// Non-API exceptions are deliberately rethrown to the existing ASP.NET Core handler.
/// </summary>
public sealed class GlobalExceptionMiddleware(
    RequestDelegate next,
    ILogger<GlobalExceptionMiddleware> logger)
{
    public async Task InvokeAsync(HttpContext context)
    {
        try
        {
            await next(context);
        }
        catch (OperationCanceledException) when (context.RequestAborted.IsCancellationRequested)
        {
            throw;
        }
        catch (Exception ex) when (
            context.Request.Path.StartsWithSegments("/api") &&
            !context.Response.HasStarted)
        {
            logger.LogError(ex, "未处理 API 异常 | {Method} {Path} | TraceId:{TraceId}",
                context.Request.Method, context.Request.Path, context.TraceIdentifier);

            context.Response.Clear();
            context.Response.StatusCode = StatusCodes.Status500InternalServerError;
            await context.Response.WriteAsJsonAsync(
                ApiResponse.Fail("服务器内部错误。", "internal_error"),
                context.RequestAborted);
        }
    }
}
