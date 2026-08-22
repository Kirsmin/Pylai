using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Pylaios.Features.Account;
using Pylaios.Features.Audit;
using Pylaios.Features.Config;
using Pylaios.Features.Database;
using Pylaios.Features.Users;
using Pylaios.Shared;

namespace Pylaios.Features.Auth;

[ApiController]
[Route("api/auth")]
public class ExternalLoginController : ControllerBase
{
    private const string ExternalStatePrefix = "oauth:external:";
    private static readonly TimeSpan ExternalStateTtl = TimeSpan.FromMinutes(5);

    private readonly SignInManager<User> _signInManager;
    private readonly UserManager<User> _userManager;
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly MainConfig _config;
    private readonly IpResolutionService _ipResolver;
    private readonly IMfaService _mfa;
    private readonly IRedisStateCache _stateCache;
    private readonly ILogger<ExternalLoginController> _logger;

    public ExternalLoginController(
        SignInManager<User> signInManager,
        UserManager<User> userManager,
        ApplicationDbContext context,
        IAuditService auditService,
        MainConfig config,
        IpResolutionService ipResolver,
        IMfaService mfa,
        IRedisStateCache stateCache,
        ILogger<ExternalLoginController> logger)
    {
        _signInManager = signInManager;
        _userManager = userManager;
        _context = context;
        _auditService = auditService;
        _config = config;
        _ipResolver = ipResolver;
        _mfa = mfa;
        _stateCache = stateCache;
        _logger = logger;
    }

    [AllowAnonymous]
    [HttpPost("external-login")]
    public async Task<IActionResult> ExternalLogin([FromBody] ExternalLoginRequest request)
    {
        if (string.IsNullOrEmpty(request.Provider))
            return BadRequest(new { Success = false, Error = "Provider is required.", ErrorCode = "invalid_request" });

        var provider = request.Provider.ToLowerInvariant() switch
        {
            "github" => "GitHub",
            "facebook" => "Facebook",
            "microsoft" => "Microsoft",
            _ => null
        };

        if (provider is null)
            return BadRequest(new { Success = false, Error = "Unsupported provider.", ErrorCode = "invalid_request" });

        var configured = provider switch
        {
            "GitHub" => !string.IsNullOrEmpty(_config.ExternalLogin.Github.ClientId),
            "Facebook" => !string.IsNullOrEmpty(_config.ExternalLogin.Facebook.AppId),
            "Microsoft" => !string.IsNullOrEmpty(_config.ExternalLogin.Microsoft.ClientId),
            _ => false
        };
        if (!configured)
            return BadRequest(new { Success = false, Error = "Provider is not configured.", ErrorCode = "invalid_request" });

        string? initiatorUid = null;
        string? sessionStepUpKey = null;
        if (User.Identity?.IsAuthenticated == true)
        {
            var initiator = await _userManager.GetUserAsync(User);
            if (initiator is null)
            {
                _logger.LogWarning("外部登录启动失败：认证 Cookie 无法解析用户");
                await _signInManager.SignOutAsync();
                return Unauthorized(ApiResponse.Fail("登录状态无效。", "session_invalid"));
            }
            initiatorUid = initiator.Uid.ToString();
            sessionStepUpKey = this.GetStepUpCredentialKey();
        }

        var flowId = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        await _stateCache.SetAsync(
            ExternalStatePrefix + flowId,
            new ExternalLoginState(provider, initiatorUid, sessionStepUpKey),
            ExternalStateTtl);

        // ASP.NET Core OAuth handler still owns its protected state/correlation cookie.
        // The opaque flow id is embedded in the protected RedirectUri and additionally
        // checked against Redis to make the application-level login/bind flow single-use.
        var redirectUrl = Url.Action(
            nameof(ExternalLoginCallback),
            null,
            new { flow = flowId },
            Request.Scheme)!;
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
    public async Task<IActionResult> ExternalLoginCallback([FromQuery] string? flow)
    {
        if (string.IsNullOrWhiteSpace(flow) || flow.Length != 64)
        {
            _logger.LogWarning("OAuth 外部登录 state 缺失或格式无效");
            return InvalidStateRedirect();
        }

        ExternalLoginState? state;
        try
        {
            state = await _stateCache.TakeAsync<ExternalLoginState>(ExternalStatePrefix + flow);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "OAuth 外部登录 state 校验失败：Redis 不可用");
            return InvalidStateRedirect();
        }

        if (state is null)
        {
            _logger.LogWarning("OAuth 外部登录 state 已过期、已使用或不存在");
            return InvalidStateRedirect();
        }

        var info = await _signInManager.GetExternalLoginInfoAsync();
        if (info is null)
        {
            _logger.LogWarning("外部登录信息获取失败");
            return RedirectToLogin("external_failed");
        }

        if (!string.Equals(info.LoginProvider, state.Provider, StringComparison.Ordinal))
        {
            _logger.LogWarning("OAuth 外部登录 Provider 与 state 不匹配 | StateProvider:{StateProvider} | Provider:{Provider}",
                state.Provider, info.LoginProvider);
            return InvalidStateRedirect();
        }

        User? currentUser = null;
        if (User.Identity?.IsAuthenticated == true)
            currentUser = await _userManager.GetUserAsync(User);

        var callbackUid = currentUser?.Uid.ToString();
        if (!string.Equals(state.InitiatorUid, callbackUid, StringComparison.Ordinal))
        {
            _logger.LogWarning("OAuth 外部登录发起身份与回调身份不匹配 | Provider:{Provider}", info.LoginProvider);
            return InvalidStateRedirect();
        }

        var providerKey = info.ProviderKey;
        var provider = info.LoginProvider;
        var ip = this.GetClientIp(_ipResolver);

        if (currentUser is not null)
        {
            var boundUser = await _userManager.FindByLoginAsync(provider, providerKey);
            if (boundUser is not null)
            {
                if (boundUser.Uid != currentUser.Uid)
                {
                    _logger.LogWarning("外部登录绑定失败：凭据已被其他账户绑定 | uid:{Uid} | Provider:{Provider}",
                        currentUser.Uid, provider);
                    return RedirectToLogin();
                }

                return RedirectToLogin();
            }

            var currentStepUpKey = this.GetStepUpCredentialKey();
            if (string.IsNullOrEmpty(state.SessionStepUpKey)
                || !string.Equals(state.SessionStepUpKey, currentStepUpKey, StringComparison.Ordinal)
                || !await _mfa.HasCredentialStepUpVerifiedAsync(state.SessionStepUpKey))
            {
                _logger.LogWarning("外部登录绑定拒绝：发起会话未通过 Step-Up 或会话已变化 | uid:{Uid} | Provider:{Provider}",
                    currentUser.Uid, provider);
                return RedirectToLogin("mfa_step_up_required", provider);
            }

            var result = await _userManager.AddLoginAsync(currentUser, info);
            if (!result.Succeeded)
            {
                _logger.LogWarning("外部登录绑定失败 | uid:{Uid} | Provider:{Provider} | 错误:{Errors}",
                    currentUser.Uid, provider, string.Join(";", result.Errors.Select(e => e.Description)));
                return RedirectToLogin();
            }

            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ExternalLoginBound,
                currentUser.Uid.ToString(), currentUser.Email, true,
                $"Provider: {provider}, Key: {providerKey}");

            _logger.LogInformation("外部登录绑定成功 | uid:{Uid} | Provider:{Provider}", currentUser.Uid, provider);

            return RedirectToLogin();
        }

        var user = await _userManager.FindByLoginAsync(provider, providerKey);
        if (user is null)
        {
            _logger.LogWarning("外部登录拒绝：凭据未绑定任何账户 | Provider:{Provider} | Key:{Key}", provider, providerKey);
            return RedirectToLogin("external_login_requires_account");
        }

        if (user.Status != UserStatus.Active)
        {
            _logger.LogWarning("外部登录拒绝：账户状态异常 | uid:{Uid} | 状态:{Status}", user.Uid, user.Status);
            return RedirectToLogin("external_failed");
        }

        var mfaRequirement = await _mfa.BeginLoginAsync(user, rememberMe: false, ip);
        if (mfaRequirement.Required)
        {
            _logger.LogInformation("外部登录需完成 MFA | uid:{Uid} | Provider:{Provider}", user.Uid, provider);
            return RedirectToLogin("mfa_required", provider, new Dictionary<string, string>
            {
                ["mfa_transaction"] = mfaRequirement.TransactionId ?? string.Empty,
                ["mfa_methods"] = string.Join(",", mfaRequirement.Methods)
            });
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

    private IActionResult RedirectToLogin(string? error = null, string? provider = null,
        Dictionary<string, string>? extraParams = null)
    {
        var url = new StringBuilder($"{_config.Frontend.Url.TrimEnd('/')}/login");
        var separator = '?';

        void Append(string key, string value)
        {
            url.Append(separator)
                .Append(Uri.EscapeDataString(key))
                .Append('=')
                .Append(Uri.EscapeDataString(value));
            separator = '&';
        }

        if (!string.IsNullOrWhiteSpace(error)) Append("error", error);
        if (!string.IsNullOrWhiteSpace(provider)) Append("provider", provider);
        if (extraParams is not null)
            foreach (var (key, value) in extraParams)
                if (!string.IsNullOrEmpty(value))
                    Append(key, value);
        return Redirect(url.ToString());
    }

    private IActionResult InvalidStateRedirect() => RedirectToLogin("invalid_state");

}

internal sealed record ExternalLoginState(string Provider, string? InitiatorUid, string? SessionStepUpKey = null);
