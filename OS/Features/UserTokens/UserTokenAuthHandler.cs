using System.Security.Claims;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Options;

namespace Pylaios.Features.UserTokens;

public class UserTokenOptions : AuthenticationSchemeOptions { }

public class UserTokenAuthHandler : AuthenticationHandler<UserTokenOptions>
{
    private const string Prefix = "UserToken";
    private const int ExpectedKeyLength = 128;

    private readonly IUserTokenService _tokenService;
    private readonly IpResolutionService _ipResolver;
    private readonly ILogger<UserTokenAuthHandler> _logger;

    public UserTokenAuthHandler(
        IOptionsMonitor<UserTokenOptions> options,
        ILoggerFactory loggerFactory,
        UrlEncoder encoder,
        IUserTokenService tokenService,
        IpResolutionService ipResolver)
        : base(options, loggerFactory, encoder)
    {
        _tokenService = tokenService;
        _ipResolver = ipResolver;
        _logger = loggerFactory.CreateLogger<UserTokenAuthHandler>();
    }

    protected override async Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        var authHeader = Request.Headers.Authorization.ToString();
        if (string.IsNullOrEmpty(authHeader))
            return AuthenticateResult.Fail("Unauthorized");

        var parts = authHeader.Split(' ', 2);
        if (parts.Length != 2 || !parts[0].Equals("Bearer", StringComparison.OrdinalIgnoreCase))
            return AuthenticateResult.Fail("Unauthorized");

        var token = parts[1];
        if (!token.StartsWith(Prefix, StringComparison.Ordinal) || token.Length != Prefix.Length + ExpectedKeyLength)
            return AuthenticateResult.Fail("Unauthorized");

        var ip = _ipResolver.GetClientIp(Context);
        var result = await _tokenService.ValidateAsync(token, ip, Request.Headers.UserAgent.ToString(), Request.Method, Request.Path.Value ?? "/");
        if (!result.Valid || result.Token is null || result.User is null)
            return AuthenticateResult.Fail("Unauthorized");

        var claims = new[]
        {
            new Claim(ClaimTypes.NameIdentifier, result.User.Uid.ToString()),
            new Claim(ClaimTypes.Name, result.User.Name),
            new Claim(ClaimTypes.Role, result.User.Group),
            new Claim("auth_scheme", "UserToken"),
            new Claim("user_token_id", result.Token.Id.ToString())
        };

        var identity = new ClaimsIdentity(claims, Scheme.Name);
        var principal = new ClaimsPrincipal(identity);
        var ticket = new AuthenticationTicket(principal, Scheme.Name);

        _logger.LogDebug("UserToken 认证成功 | TokenId:{Id} | uid:{Uid}", result.Token.Id, result.User.Uid);

        return AuthenticateResult.Success(ticket);
    }

    protected override async Task HandleChallengeAsync(AuthenticationProperties properties)
    {
        Response.StatusCode = 401;
        Response.ContentType = "application/json";
        await Response.WriteAsync("""{"success":false,"error":"Unauthorized","errorCode":"unauthorized"}""");
    }

    protected override async Task HandleForbiddenAsync(AuthenticationProperties properties)
    {
        Response.StatusCode = 403;
        Response.ContentType = "application/json";
        await Response.WriteAsync("""{"success":false,"error":"Forbidden","errorCode":"forbidden"}""");
    }
}
