using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Account;

[ApiController]
[Route("api/auth/account")]
[Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
public sealed class CurrentAccountController : ControllerBase
{
    private readonly ApplicationDbContext _context;

    public CurrentAccountController(ApplicationDbContext context)
    {
        _context = context;
    }

    [HttpGet]
    public async Task<IActionResult> GetCurrentAccount()
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
            return Unauthorized(new { Error = "未登录或会话已失效。", ErrorCode = "unauthorized" });

        return Ok(new
        {
            user = new
            {
                uid = user.Uid,
                name = user.Name,
                displayName = user.DisplayName ?? user.Name,
                email = user.Email ?? string.Empty,
                group = user.Group
            }
        });
    }
}
