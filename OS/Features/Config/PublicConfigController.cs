using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Config;

[ApiController]
[Route("api/config")]
public sealed class PublicConfigController : ControllerBase
{
    private readonly MainConfig _config;

    public PublicConfigController(MainConfig config)
    {
        _config = config;
    }

    [HttpGet("public")]
    [AllowAnonymous]
    public IActionResult GetPublicConfig()
    {
        var supportEmail = Environment.GetEnvironmentVariable("PYLAI_SUPPORT_EMAIL");
        if (string.IsNullOrWhiteSpace(supportEmail))
            supportEmail = _config.Email.FromAddress;

        return Ok(new
        {
            supportEmail = supportEmail?.Trim() ?? string.Empty,
            requireInviteCode = _config.InviteCode.RequireInviteCode
        });
    }
}
