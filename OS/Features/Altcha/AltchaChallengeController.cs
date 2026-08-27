using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Altcha;

[ApiController]
[Route("api/altcha")]
[AllowAnonymous]
public class AltchaChallengeController : ControllerBase
{
    [HttpGet("challenge")]
    public IActionResult GetChallenge([FromServices] IAltchaService svc)
    {
        return Ok(svc.GenerateChallenge());
    }
}
