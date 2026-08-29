using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Auth;

/// <summary>
/// 用户侧 CSRF token 签发（双提交：可读 Cookie Pylaios.Csrf + 响应体 token）。
/// Cookie 经 Identity.Application 认证发起状态修改请求时必须回传 X-CSRF-Token 头
/// （见 Shared/CookieCsrfMiddleware）；Bearer UserToken 路径不受影响。
/// </summary>
[ApiController]
public sealed class CsrfController : ControllerBase
{
    [Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
    [HttpGet("api/auth/csrf")]
    public IActionResult Issue()
    {
        var token = AuthHelper.GenerateOpaqueToken(32);
        Response.Cookies.Append(CookieCsrfMiddleware.CsrfCookieName, token, new CookieOptions
        {
            HttpOnly = false,
            Secure = true,
            SameSite = SameSiteMode.Lax,
            Path = "/",
            IsEssential = true
        });
        return Ok(new { success = true, token });
    }
}
