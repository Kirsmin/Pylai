using Microsoft.AspNetCore;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;
using OpenIddict.Server.AspNetCore;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Pylaios.Features.OAuth;

public class UserInfoController : Controller
{
    private readonly ApplicationDbContext _context;

    public UserInfoController(ApplicationDbContext context)
    {
        _context = context;
    }

    [HttpGet("~/connect/userinfo")]
    [HttpPost("~/connect/userinfo")]
    [IgnoreAntiforgeryToken]
    [Produces("application/json")]
    public async Task<IActionResult> UserInfo()
    {
        var result = await HttpContext.AuthenticateAsync(OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
        if (result?.Principal is not { Identity.IsAuthenticated: true })
        {
            return Challenge(OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
        }

        var subject = result.Principal.GetClaim(Claims.Subject);
        if (subject is null || !Guid.TryParse(subject, out var uid))
            return await UnauthorizedJsonAsync();

        var active = await _context.Users.AnyAsync(u => u.Uid == uid && u.Status == UserStatus.Active);
        if (!active)
            return await UnauthorizedJsonAsync();

        var claims = new Dictionary<string, object>(StringComparer.Ordinal)
        {
            [Claims.Subject] = subject!
        };

        if (result.Principal.HasScope(AuthConstants.Scopes.ProfileBasic))
        {
            var name = result.Principal.GetClaim(Claims.Name);
            if (name is not null) claims[Claims.Name] = name;

            var preferredUsername = result.Principal.GetClaim(Claims.PreferredUsername);
            if (preferredUsername is not null) claims[Claims.PreferredUsername] = preferredUsername;
        }

        if (result.Principal.HasScope(AuthConstants.Scopes.ProfileMail))
        {
            var email = result.Principal.GetClaim(Claims.Email);
            if (email is not null) claims[Claims.Email] = email;

            var emailVerified = result.Principal.GetClaim(Claims.EmailVerified);
            if (emailVerified is not null && bool.TryParse(emailVerified, out var verified))
                claims[Claims.EmailVerified] = verified;
        }

        if (result.Principal.HasScope(AuthConstants.Scopes.ProfileRole))
        {
            var roles = result.Principal.FindAll(Claims.Role).Select(c => c.Value).ToList();
            if (roles.Count > 0) claims[Claims.Role] = roles;
        }

        return Ok(claims);
    }

    private async Task<IActionResult> UnauthorizedJsonAsync()
    {
        Response.StatusCode = 401;
        Response.ContentType = "application/json";
        await Response.WriteAsync("""{"success":false,"error":"未登录或登录已失效。","errorCode":"unauthorized"}""");
        return new EmptyResult();
    }
}
