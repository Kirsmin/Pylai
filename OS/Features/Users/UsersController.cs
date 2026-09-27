using OpenIddict.Abstractions;
using OpenIddict.Validation.AspNetCore;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Users;

/// <summary>
/// 内部服务对接用的只读用户目录：仅接受 client_credentials 换取的 OAuth2 access token。
/// 用户令牌（authorization_code / refresh_token 签发，sub 为用户 uid）一律拒绝：
/// client 令牌的 sub 是 client_id（字符串），用户令牌的 sub 是 Guid，非 Guid 才放行。
/// 只暴露 GET，无任何写操作与管理功能。
/// </summary>
[ApiController]
[Route("api/users")]
[Authorize(AuthenticationSchemes = OpenIddictValidationAspNetCoreDefaults.AuthenticationScheme)]
public class UsersController : ControllerBase
{
    private readonly ApplicationDbContext _context;

    public UsersController(ApplicationDbContext context)
    {
        _context = context;
    }

    [HttpGet]
    public async Task<IActionResult> List()
    {
        var authenticated = await HttpContext.AuthenticateAsync(
            OpenIddictValidationAspNetCoreDefaults.AuthenticationScheme);
        var principal = authenticated.Principal;
        if (principal is not { Identity.IsAuthenticated: true })
            return Unauthorized(new ApiResponse { Success = false, Error = "未登录或登录已失效。", ErrorCode = "unauthorized" });

        // Fail Closed：sub 可解析为 Guid 说明是用户令牌，拒绝。
        var subject = principal.GetClaim(OpenIddictConstants.Claims.Subject);
        if (string.IsNullOrEmpty(subject) || Guid.TryParse(subject, out _))
            return Unauthorized(new ApiResponse { Success = false, Error = "未登录或登录已失效。", ErrorCode = "unauthorized" });

        var users = await _context.Users.AsNoTracking()
            .OrderBy(u => u.RegisterTime)
            .Select(u => new UserDirectoryItem
            {
                Uid = u.Uid,
                Email = u.Email,
                Status = u.Status.ToString(),
                Group = u.Group,
                // 与 /connect/userinfo 的 profile:role 命名对齐（角色为数组，此处单元素）
                Role = new List<string> { u.Group },
                PreferredUsername = u.Name,
                Name = u.DisplayName ?? u.Name
            })
            .ToListAsync();

        return Ok(new UsersListResponse { Success = true, Users = users });
    }
}

public class UsersListResponse : ApiResponse
{
    public List<UserDirectoryItem> Users { get; set; } = [];
}

public class UserDirectoryItem
{
    public Guid Uid { get; set; }
    public string? Email { get; set; }
    public required string Status { get; set; }
    public required string Group { get; set; }
    public required List<string> Role { get; set; }
    public required string PreferredUsername { get; set; }
    public required string Name { get; set; }
}
