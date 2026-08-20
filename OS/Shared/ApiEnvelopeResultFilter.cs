using Microsoft.AspNetCore.Http;
using System.Reflection;
using System.Text.Json.Nodes;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.Extensions.Options;

namespace Pylaios.Shared;

/// <summary>
/// Removes the legacy top-level transport envelope field "success" from /api JSON responses.
/// Nested domain fields named "success" are intentionally preserved.
/// </summary>
public sealed class ApiEnvelopeResultFilter : IResultFilter
{
    private readonly System.Text.Json.JsonSerializerOptions _jsonOptions;

    public ApiEnvelopeResultFilter(IOptions<JsonOptions> options)
    {
        _jsonOptions = options.Value.JsonSerializerOptions;
    }

    public void OnResultExecuting(ResultExecutingContext context)
    {
        if (!context.HttpContext.Request.Path.StartsWithSegments("/api")
            || context.Result is not ObjectResult { Value: not null } result)
            return;

        var valueType = result.Value.GetType();
        if (!HasLegacySuccessProperty(valueType))
            return;

        var node = System.Text.Json.JsonSerializer.SerializeToNode(result.Value, valueType, _jsonOptions);
        if (node is not JsonObject obj)
            return;

        obj.Remove("success");
        obj.Remove("Success");

        // Preserve protocol/shape errors as 400, but express ordinary business validation
        // failures with 422 so callers only need HTTP status + errorCode.
        if (result.StatusCode == StatusCodes.Status400BadRequest
            && TryGetErrorCode(obj, out var errorCode)
            && errorCode is not ("invalid_request" or "invalid_format"))
        {
            result.StatusCode = StatusCodes.Status422UnprocessableEntity;
        }

        result.Value = obj;
        result.DeclaredType = typeof(JsonObject);
    }

    public void OnResultExecuted(ResultExecutedContext context) { }

    private static bool HasLegacySuccessProperty(Type type)
        => type.GetProperty("Success", BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase) is not null;

    private static bool TryGetErrorCode(JsonObject obj, out string? errorCode)
    {
        errorCode = null;
        var node = obj["errorCode"] ?? obj["ErrorCode"];
        if (node is not JsonValue value || !value.TryGetValue<string>(out var code) || string.IsNullOrWhiteSpace(code))
            return false;
        errorCode = code;
        return true;
    }
}
