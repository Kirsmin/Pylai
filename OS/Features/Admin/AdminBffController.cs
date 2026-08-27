using System.Security.Cryptography;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Admin;

[ApiController]
[Route("api/admin/bff")]
public sealed class AdminBffController : ControllerBase
{
    private const string CsrfCookie = "Pylaios.AdminCsrf";
    private readonly MainConfig _config;

    public AdminBffController(MainConfig config)
    {
        _config = config;
    }

    [AllowAnonymous]
    [HttpGet("login")]
    public IActionResult Login([FromQuery] string? returnUrl = null)
    {
        var target = SafeReturnUrl(returnUrl);
        if (User.Identity?.IsAuthenticated == true)
            return Redirect(target);

        var loginUrl = $"{_config.Frontend.Url.TrimEnd('/')}/login?return_url={Uri.EscapeDataString(target)}";
        return Redirect(loginUrl);
    }

    [Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
    [HttpGet("csrf")]
    public IActionResult Csrf()
    {
        var token = AuthHelper.GenerateOpaqueToken(32);
        Response.Cookies.Append(CsrfCookie, token, new CookieOptions
        {
            HttpOnly = false,
            Secure = true,
            SameSite = SameSiteMode.Lax,
            Path = "/api/admin",
            IsEssential = true
        });
        return Ok(new { success = true, token });
    }

    private static string SafeReturnUrl(string? returnUrl)
        => !string.IsNullOrWhiteSpace(returnUrl)
            && returnUrl.StartsWith("/admin", StringComparison.Ordinal)
            && !returnUrl.StartsWith("//", StringComparison.Ordinal)
            ? returnUrl
            : "/admin/";

    internal static bool IsValidCsrf(HttpRequest request)
    {
        if (HttpMethods.IsGet(request.Method)
            || HttpMethods.IsHead(request.Method)
            || HttpMethods.IsOptions(request.Method)
            || !request.Cookies.TryGetValue(CsrfCookie, out var cookie)
            || string.IsNullOrEmpty(cookie))
            return HttpMethods.IsGet(request.Method)
                || HttpMethods.IsHead(request.Method)
                || HttpMethods.IsOptions(request.Method);

        var header = request.Headers["X-CSRF-Token"].FirstOrDefault();
        return !string.IsNullOrEmpty(header)
            && CryptographicOperations.FixedTimeEquals(
                System.Text.Encoding.UTF8.GetBytes(cookie),
                System.Text.Encoding.UTF8.GetBytes(header));
    }
}
