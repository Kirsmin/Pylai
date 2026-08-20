using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Auth;

[ApiController]
[Route("api/auth")]
public class ExternalLoginController : ControllerBase
{
    private readonly SignInManager<User> _signInManager;
    private readonly UserManager<User> _userManager;
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly MainConfig _config;
    private readonly IpResolutionService _ipResolver;
    private readonly IMfaService _mfa;
    private readonly ILogger<ExternalLoginController> _logger;

    public ExternalLoginController(
        SignInManager<User> signInManager,
        UserManager<User> userManager,
        ApplicationDbContext context,
        IAuditService auditService,
        MainConfig config,
        IpResolutionService ipResolver,
        IMfaService mfa,
        ILogger<ExternalLoginController> logger)
    {
        _signInManager = signInManager;
        _userManager = userManager;
        _context = context;
        _auditService = auditService;
        _config = config;
        _ipResolver = ipResolver;
        _mfa = mfa;
        _logger = logger;
    }

    [AllowAnonymous]
    [HttpPost("external-login")]
    public IActionResult ExternalLogin([FromBody] ExternalLoginRequest request)
    {
        if (string.IsNullOrEmpty(request.Provider))
            return BadRequest(new { Success = false, Error = "Provider is required." });

        var provider = request.Provider.ToLowerInvariant() switch
        {
            "github" => "GitHub",
            "facebook" => "Facebook",
            "microsoft" => "Microsoft",
            _ => null
        };

        if (provider is null)
            return BadRequest(new { Success = false, Error = "Unsupported provider." });

        var configured = provider switch
        {
            "GitHub" => !string.IsNullOrEmpty(_config.ExternalLogin.Github.ClientId),
            "Facebook" => !string.IsNullOrEmpty(_config.ExternalLogin.Facebook.AppId),
            "Microsoft" => !string.IsNullOrEmpty(_config.ExternalLogin.Microsoft.ClientId),
            _ => false
        };
        if (!configured)
            return BadRequest(new { Success = false, Error = "Provider is not configured." });

        var redirectUrl = Url.Action(nameof(ExternalLoginCallback), null, null, Request.Scheme)!;
        var properties = _signInManager.ConfigureExternalAuthenticationProperties(provider, redirectUrl);
        return Challenge(properties, provider);
    }

    [AllowAnonymous]
    [HttpGet("external-login/providers")]
    public IActionResult GetProviders()
    {
        var providers = new List<string>();
        if (!string.IsNullOrEmpty(_config.ExternalLogin.Facebook.AppId)) providers.Add("facebook");
        if (!string.IsNullOrEmpty(_config.ExternalLogin.Microsoft.ClientId)) providers.Add("microsoft");
        if (!string.IsNullOrEmpty(_config.ExternalLogin.Github.ClientId)) providers.Add("github");
        return Ok(new { Success = true, Providers = providers });
    }

    [HttpGet("external-login-callback")]
    [AllowAnonymous]
    public async Task<IActionResult> ExternalLoginCallback()
    {
        var info = await _signInManager.GetExternalLoginInfoAsync();
        if (info is null)
        {
            _logger.LogWarning("外部登录信息获取失败");
            return Redirect($"{_config.Frontend.Url}/login?error=external_failed");
        }

        var providerKey = info.ProviderKey;
        var provider = info.LoginProvider;
        var ip = this.GetClientIp(_ipResolver);


        if (User.Identity?.IsAuthenticated == true)
        {
            var currentUser = await _userManager.GetUserAsync(User);
            if (currentUser is null)
            {
                await _signInManager.SignOutAsync();
                return Redirect($"{_config.Frontend.Url}/login?error=external_failed");
            }

            var boundUser = await _userManager.FindByLoginAsync(provider, providerKey);
            if (boundUser is not null)
            {
                if (boundUser.Uid != currentUser.Uid)
                {
                    _logger.LogWarning("外部登录绑定失败：凭据已被其他账户绑定 | uid:{Uid} | Provider:{Provider}",
                        currentUser.Uid, provider);
                    return Redirect($"{_config.Frontend.Url}/login");
                }

                return Redirect($"{_config.Frontend.Url}/login");
            }

            if (!await _mfa.HasRecentStepUpAsync(currentUser.Uid))
            {
                _logger.LogWarning("外部登录绑定拒绝：未通过近期 Step-Up | uid:{Uid} | Provider:{Provider}",
                    currentUser.Uid, provider);
                return Redirect($"{_config.Frontend.Url}/login?error=mfa_step_up_required&provider={provider}");
            }

            var result = await _userManager.AddLoginAsync(currentUser, info);
            if (!result.Succeeded)
            {
                _logger.LogWarning("外部登录绑定失败 | uid:{Uid} | Provider:{Provider} | 错误:{Errors}",
                    currentUser.Uid, provider, string.Join(";", result.Errors.Select(e => e.Description)));
                return Redirect($"{_config.Frontend.Url}/login");
            }

            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ExternalLoginBound,
                currentUser.Uid.ToString(), currentUser.Email, true,
                $"Provider: {provider}, Key: {providerKey}");

            _logger.LogInformation("外部登录绑定成功 | uid:{Uid} | Provider:{Provider}", currentUser.Uid, provider);

            return Redirect($"{_config.Frontend.Url}/login");
        }


        var user = await _userManager.FindByLoginAsync(provider, providerKey);
        if (user is null)
        {
            _logger.LogWarning("外部登录拒绝：凭据未绑定任何账户 | Provider:{Provider} | Key:{Key}", provider, providerKey);
            return Redirect($"{_config.Frontend.Url}/login?error=external_login_requires_account");
        }

        if (user.Status != UserStatus.Active)
        {
            _logger.LogWarning("外部登录拒绝：账户状态异常 | uid:{Uid} | 状态:{Status}", user.Uid, user.Status);
            return Redirect($"{_config.Frontend.Url}/login?error=external_failed");
        }

        user.LastLoginAt = DateTimeOffset.UtcNow;
        await _context.SaveChangesAsync();

        await _signInManager.SignInAsync(user, isPersistent: false);
        await this.CreateUserSessionAsync(_context, user, ip, _config.Cookie.SessionName);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ExternalLoginSignedIn,
            user.Uid.ToString(), user.Email, true, $"Provider: {provider}");

        _logger.LogInformation("外部登录成功 | uid:{Uid} | Provider:{Provider}", user.Uid, provider);

        return Redirect($"{_config.Frontend.Url}/");
    }
}
