using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Pylaios.Features.Account;

[ApiController]
[Route("api/auth/account")]
[Authorize(AuthenticationSchemes = "Identity.Application,OpenIddict.Validation.AspNetCore")]
public class AccountController : ControllerBase
{
    private readonly IPasswordHasher<User> _passwordHasher;
    private readonly UserManager<User> _userManager;
    private readonly EmailSender _emailSender;
    private readonly ApplicationDbContext _context;
    private readonly IEmailVerificationCodeService _emailCodeService;
    private readonly IAuditService _auditService;
    private readonly IInviteCodeService _inviteCodeService;
    private readonly IUserAccessRevoker _userAccessRevoker;
    private readonly IpResolutionService _ipResolver;
    private readonly TestModeOptions _testMode;
    private readonly IOpenIddictAuthorizationManager _authorizationManager;
    private readonly IOpenIddictApplicationManager _applicationManager;
    private readonly IOpenIddictScopeManager _scopeManager;
    private readonly IOpenIddictTokenManager _tokenManager;
    private readonly ILogger<AccountController> _logger;

    public AccountController(
        IPasswordHasher<User> passwordHasher,
        UserManager<User> userManager,
        EmailSender emailSender,
        ApplicationDbContext context,
        IEmailVerificationCodeService emailCodeService,
        IAuditService auditService,
        IInviteCodeService inviteCodeService,
        IUserAccessRevoker userAccessRevoker,
        IpResolutionService ipResolver,
        TestModeOptions testMode,
        IOpenIddictAuthorizationManager authorizationManager,
        IOpenIddictApplicationManager applicationManager,
        IOpenIddictScopeManager scopeManager,
        IOpenIddictTokenManager tokenManager,
        ILogger<AccountController> logger)
    {
        _passwordHasher = passwordHasher;
        _userManager = userManager;
        _emailSender = emailSender;
        _context = context;
        _emailCodeService = emailCodeService;
        _auditService = auditService;
        _inviteCodeService = inviteCodeService;
        _userAccessRevoker = userAccessRevoker;
        _ipResolver = ipResolver;
        _testMode = testMode;
        _authorizationManager = authorizationManager;
        _applicationManager = applicationManager;
        _scopeManager = scopeManager;
        _tokenManager = tokenManager;
        _logger = logger;
    }

    [HttpPost("change-password")]
    public async Task<IActionResult> ChangePassword([FromBody] ChangePasswordRequest request)
    {
        _logger.LogDebug("修改密码请求");

        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        _logger.LogDebug("修改密码 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        if (!ModelState.IsValid)
        {
            _logger.LogWarning("请求参数无效");
            return BadRequest(new PasswordResponse { Success = false, Error = "Invalid request.", ErrorCode = "invalid_format" });
        }

        var result = _passwordHasher.VerifyHashedPassword(user, user.PasswordHash, request.CurrentPassword);
        if (result == PasswordVerificationResult.Failed)
        {
            _logger.LogWarning("当前密码验证失败 | uid:{Uid}", user.Uid);
            return BadRequest(new PasswordResponse { Success = false, Error = "当前密码错误。", ErrorCode = "wrong_code" });
        }

        var pwErrors = await AuthHelper.ValidatePasswordAsync(_userManager, user, request.NewPassword);
        if (pwErrors.Count > 0)
        {
            _logger.LogWarning("新密码不符合策略 | uid:{Uid} | 错误:{Errors}", user.Uid, string.Join("; ", pwErrors.Select(e => e.Description)));
            return BadRequest(new PasswordResponse { Success = false, Error = pwErrors[0].Description, ErrorCode = "invalid_password" });
        }

        user.PasswordHash = _passwordHasher.HashPassword(user, request.NewPassword);
        await _userAccessRevoker.RevokeUserAccessAsync(user.Uid);

        _logger.LogInformation("密码修改成功 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        return Ok(new PasswordResponse { Success = true });
    }

    [HttpPost("email/bind")]
    public async Task<IActionResult> BindEmail([FromBody] BindEmailRequest request)
    {
        _logger.LogDebug("绑定邮箱请求 | {Email}", request.Email);

        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        _logger.LogDebug("绑定邮箱 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        if (!ModelState.IsValid)
        {
            _logger.LogWarning("请求参数无效");
            return BadRequest(new EmailCodeResponse { Success = false, Error = "Invalid request.", ErrorCode = "invalid_format" });
        }

        if (!AuthHelper.IsValidEmail(request.Email))
        {
            _logger.LogWarning("邮箱格式无效 | {Email}", request.Email ?? "null/empty");
            return BadRequest(new EmailCodeResponse { Success = false, Error = "邮箱地址格式不正确。", ErrorCode = "invalid_format" });
        }

        if (!string.IsNullOrEmpty(user.Email))
        {
            _logger.LogWarning("邮箱已存在 | uid:{Uid} | {Email}", user.Uid, user.Email);
            return BadRequest(new EmailCodeResponse { Success = false, Error = "邮箱已绑定，请使用「更换邮箱」功能。", ErrorCode = "already_exists" });
        }

        if (await _context.IsEmailTakenAsync(request.Email))
        {
            _logger.LogWarning("邮箱已被其他用户占用 | uid:{Uid} | {Email}", user.Uid, request.Email);
            return StatusCode(403, new EmailCodeResponse { Success = false, Error = "邮箱验证已被限制，请稍后重试。", ErrorCode = "banned" });
        }

        var passwordResult = _passwordHasher.VerifyHashedPassword(user, user.PasswordHash, request.CurrentPassword);
        if (passwordResult == PasswordVerificationResult.Failed)
        {
            _logger.LogWarning("密码验证失败(绑定邮箱) | uid:{Uid}", user.Uid);
            return BadRequest(new EmailCodeResponse { Success = false, Error = "当前密码错误。", ErrorCode = "wrong_code" });
        }

        var code = await _emailCodeService.CreateAsync($"bind-email:{user.Uid}", request.Email);

        _logger.LogCode(_testMode, LogLevel.Debug, "验证码生成 | uid:{Uid} | → {Email}", code, user.Uid, request.Email);

        var sendError = await SendEmailCodeSafeAsync(user, request.Email, code, MailThemeKind.Bind, "绑定邮箱");
        if (sendError is not null) return sendError;

        _logger.LogCode(_testMode, LogLevel.Information, "绑定邮箱码已发送 | uid:{Uid} | → {Email}", code, user.Uid, request.Email);

        return Ok(new EmailCodeResponse { Success = true, Sent = true });
    }

    [HttpPost("email/bind/confirm")]
    public async Task<IActionResult> BindEmailConfirm([FromBody] EmailCodeRequest request)
    {
        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        var key = $"bind-email:{user.Uid}";
        var result = await _emailCodeService.VerifyAsync(key, request.Code);
        if (result.Status != EmailCodeStatus.Ok)
            return MapEmailCodeError(result);

        user.Email = result.Entry!.Email;
        user.NormalizedEmail = UsernameNormalizer.Normalize(user.Email!);
        try
        {
            await _context.SaveChangesAsync();
        }
        catch (DbUpdateException ex) when (ex.IsUniqueViolation())
        {
            return StatusCode(409, new EmailCodeResponse { Success = false, Error = "邮箱已被其他用户占用。", ErrorCode = "duplicate" });
        }
        await _emailCodeService.RemoveAsync(key);

        _logger.LogInformation("邮箱绑定成功 | uid:{Uid} | {Email}", user.Uid, result.Entry.Email);

        return Ok(new EmailCodeResponse { Success = true, VerifiedEmail = result.Entry.Email });
    }

    [HttpPost("email/change")]
    public async Task<IActionResult> ChangeEmail([FromBody] ChangeEmailRequest request)
    {
        _logger.LogDebug("更换邮箱请求 | {Email}", request.NewEmail);

        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        _logger.LogDebug("更换邮箱 | uid:{Uid} | 当前:{CurrentEmail}", user.Uid, user.Email);

        if (!ModelState.IsValid)
        {
            _logger.LogWarning("请求参数无效");
            return BadRequest(new EmailCodeResponse { Success = false, Error = "Invalid request.", ErrorCode = "invalid_format" });
        }

        if (!AuthHelper.IsValidEmail(request.NewEmail))
        {
            _logger.LogWarning("邮箱格式无效 | {Email}", request.NewEmail ?? "null/empty");
            return BadRequest(new EmailCodeResponse { Success = false, Error = "邮箱地址格式不正确。", ErrorCode = "invalid_format" });
        }

        if (string.IsNullOrEmpty(user.Email))
        {
            _logger.LogWarning("未绑定邮箱，请先绑定 | uid:{Uid}", user.Uid);
            return BadRequest(new EmailCodeResponse { Success = false, Error = "未绑定邮箱，请先绑定邮箱。", ErrorCode = "email_required" });
        }

        if (await _context.IsEmailTakenAsync(request.NewEmail))
        {
            _logger.LogWarning("新邮箱已被其他用户占用 | uid:{Uid} | {Email}", user.Uid, request.NewEmail);
            return StatusCode(403, new EmailCodeResponse { Success = false, Error = "邮箱验证已被限制，请稍后重试。", ErrorCode = "banned" });
        }

        var code = await _emailCodeService.CreateAsync($"change-email:{user.Uid}", request.NewEmail);

        _logger.LogCode(_testMode, LogLevel.Debug, "验证码生成 | uid:{Uid} | → {Email}", code, user.Uid, request.NewEmail);

        var sendError = await SendEmailCodeSafeAsync(user, user.Email, code, MailThemeKind.Change, "更换邮箱");
        if (sendError is not null) return sendError;

        _logger.LogCode(_testMode, LogLevel.Information, "更换邮箱验证码已发送 | uid:{Uid} | → {NewEmail}", code, user.Uid, request.NewEmail);

        return Ok(new EmailCodeResponse { Success = true, Sent = true, PendingEmail = request.NewEmail });
    }

    [HttpPost("email/change/confirm")]
    public async Task<IActionResult> ChangeEmailConfirm([FromBody] EmailCodeRequest request)
    {
        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        var key = $"change-email:{user.Uid}";
        var result = await _emailCodeService.VerifyAsync(key, request.Code);
        if (result.Status != EmailCodeStatus.Ok)
            return MapEmailCodeError(result);

        var newCode = await _emailCodeService.CreateAsync($"change-email-final:{user.Uid}", result.Entry!.Email);

        var sendError = await SendEmailCodeSafeAsync(user, result.Entry.Email!, newCode, MailThemeKind.Change, "确认新邮箱");
        if (sendError is not null) return sendError;
        _logger.LogCode(_testMode, LogLevel.Information, "新邮箱验证码已发送 | uid:{Uid} | → {Email}", newCode, user.Uid, result.Entry.Email);

        return Ok(new EmailCodeResponse { Success = true, Sent = true, PendingEmail = result.Entry.Email });
    }

    [HttpPost("email/change/finalize")]
    public async Task<IActionResult> ChangeEmailFinalize([FromBody] EmailCodeRequest request)
    {
        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        var key = $"change-email-final:{user.Uid}";
        var result = await _emailCodeService.VerifyAsync(key, request.Code);
        if (result.Status != EmailCodeStatus.Ok)
            return MapEmailCodeError(result);

        user.Email = result.Entry!.Email;
        user.NormalizedEmail = UsernameNormalizer.Normalize(user.Email!);
        try
        {
            await _context.SaveChangesAsync();
        }
        catch (DbUpdateException ex) when (ex.IsUniqueViolation())
        {
            return StatusCode(409, new EmailCodeResponse { Success = false, Error = "邮箱已被其他用户占用。", ErrorCode = "duplicate" });
        }
        await _emailCodeService.RemoveAsync(key);
        await _emailCodeService.RemoveAsync($"change-email:{user.Uid}");

        _logger.LogInformation("邮箱更换成功 | uid:{Uid} | {Email}", user.Uid, result.Entry.Email);

        return Ok(new EmailCodeResponse { Success = true, VerifiedEmail = result.Entry.Email });
    }

    [HttpPost("redeem")]
    public async Task<IActionResult> RedeemInviteCode([FromBody] AccountRedeemRequest request)
    {
        var invitePrefix = request.InviteCode?.Trim() ?? string.Empty;
        if (invitePrefix.Length > 3)
            invitePrefix = invitePrefix[..3];
        _logger.LogDebug("账号提权请求 | prefix:{Prefix}", invitePrefix);

        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        _logger.LogDebug("账号提权 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        var ip = this.GetClientIp(_ipResolver);
        var oldGroup = user.Group;

        var result = await _inviteCodeService.RedeemAsync(request.InviteCode, user, ip, revokeExistingAccess: true);

        if (result.IpBanned)
        {
            return StatusCode(403, new AccountRedeemResponse { Success = false, Error = "邀请码验证已被限制，请稍后重试。", ErrorCode = "banned" });
        }

        if (result.NewGroup is not null)
        {
            _logger.LogInformation("账号提权成功 | uid:{Uid} | {OldGroup} → {NewGroup}", user.Uid, oldGroup, result.NewGroup);

            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.InviteCodeRedeemed, user.Uid.ToString(), null, true,
                $"InvitePrefix: {result.Prefix}, Group: {result.NewGroup}");

            return Ok(new AccountRedeemResponse { Success = true, NewGroup = result.NewGroup });
        }

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.InviteCodeRedeemFailed, user.Uid.ToString(), null, false,
            $"InvitePrefix: {result.Prefix}, Result: {result.Message}");

        if (result.ApiError)
            return StatusCode(502, new AccountRedeemResponse { Success = false, Error = result.Message, ErrorCode = "api_error" });

        return BadRequest(new AccountRedeemResponse { Success = false, Error = "邀请码无效或已过期。", ErrorCode = "invalid_or_expired" });
    }

    [HttpGet("authorized-apps")]
    public async Task<IActionResult> GetAuthorizedApps()
    {
        _logger.LogDebug("列出已授权应用");

        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        var subject = user.Uid.ToString();
        var items = new List<(DateTimeOffset CreatedAt, AuthorizedAppItem Item)>();

        await foreach (var authorization in _authorizationManager.FindBySubjectAsync(subject))
        {
            var status = await _authorizationManager.GetStatusAsync(authorization);
            var type = await _authorizationManager.GetTypeAsync(authorization);
            if (status != Statuses.Valid || type != AuthorizationTypes.Permanent)
                continue;

            var appId = await _authorizationManager.GetApplicationIdAsync(authorization);
            if (string.IsNullOrEmpty(appId))
                continue;

            var application = await _applicationManager.FindByIdAsync(appId);
            if (application is null)
                continue;

            var clientId = await _applicationManager.GetClientIdAsync(application);
            var displayName = await _applicationManager.GetDisplayNameAsync(application) ?? clientId;
            var metadata = await _context.OAuthClientMetadata.FindAsync(appId);
            var createdAt = await _authorizationManager.GetCreationDateAsync(authorization);
            var scopes = await _authorizationManager.GetScopesAsync(authorization);
            var scopeList = new List<ScopeInfo>();

            foreach (var scope in scopes.Where(s => s is not (AuthConstants.Scopes.OpenId or AuthConstants.Scopes.OfflineAccess)))
            {
                var scopeObj = await _scopeManager.FindByNameAsync(scope);
                scopeList.Add(new ScopeInfo
                {
                    Name = scope,
                    DisplayName = scopeObj is null ? scope : await _scopeManager.GetDisplayNameAsync(scopeObj) ?? scope,
                    Description = scopeObj is null ? string.Empty : await _scopeManager.GetDescriptionAsync(scopeObj) ?? string.Empty
                });
            }

            items.Add((createdAt ?? DateTimeOffset.UtcNow, new AuthorizedAppItem
            {
                Id = await _authorizationManager.GetIdAsync(authorization) ?? appId,
                ClientId = clientId ?? string.Empty,
                DisplayName = displayName ?? string.Empty,
                Description = metadata?.Description,
                LogoUrl = $"{Request.Scheme}://{Request.Host}/api/clients/{Uri.EscapeDataString(appId)}/logo",
                IsFajorCertified = metadata?.IsFajorCertified ?? false,
                HomepageUrl = metadata?.HomepageUrl,
                AuthorizedAt = (createdAt ?? DateTimeOffset.UtcNow).ToOffset(TimeSpan.FromHours(8)).ToString("yyyy/MM/dd H:mm:ss"),
                Scopes = scopeList
            }));
        }

        var apps = items.OrderByDescending(t => t.CreatedAt).Select(t => t.Item).ToList();

        _logger.LogInformation("已授权应用列表 | uid:{Uid} | 数量:{Count}", user.Uid, apps.Count);

        return Ok(new AuthorizedAppListResponse { Success = true, Apps = apps });
    }

    [HttpDelete("authorized-apps/{id}")]
    public async Task<IActionResult> RevokeAuthorizedApp(string id)
    {
        _logger.LogDebug("撤销授权应用 | id:{Id}", id);

        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        var authorization = await _authorizationManager.FindByIdAsync(id);
        if (authorization is null)
        {
            _logger.LogWarning("授权不存在 | id:{Id}", id);
            return NotFound(new AuthorizedAppRevokeResponse { Success = false, Error = "授权不存在。", ErrorCode = "not_found" });
        }

        var subject = await _authorizationManager.GetSubjectAsync(authorization);
        if (subject != user.Uid.ToString())
        {
            _logger.LogWarning("用户与授权不匹配 | uid:{Uid} | id:{Id}", user.Uid, id);
            return Forbid();
        }

        var authorizationId = id;
        await _tokenManager.RevokeByAuthorizationIdAsync(authorizationId);

        var appId = await _authorizationManager.GetApplicationIdAsync(authorization);
        if (!string.IsNullOrEmpty(appId))
        {
            _context.ConsentAuditEvents.Add(new ConsentAuditEvent
            {
                Subject = subject,
                ClientId = appId,
                Action = ConsentAuditActions.ApplicationRevoked,
                AuthorizationId = authorizationId
            });
            await _context.SaveChangesAsync();
        }

        await _authorizationManager.DeleteAsync(authorization);

        _logger.LogInformation("撤销授权成功 | uid:{Uid} | id:{Id}", user.Uid, id);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.AuthorizationRevoked, user.Uid.ToString(), user.Email, true,
            $"Authorization: {id}");

        return Ok(new AuthorizedAppRevokeResponse { Success = true });
    }

    [HttpGet("external-logins")]
    public async Task<IActionResult> GetExternalLogins()
    {
        _logger.LogDebug("列出外部登录绑定");

        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        var logins = await _userManager.GetLoginsAsync(user);
        var items = logins.Select(l => new
        {
            provider = l.LoginProvider,
            displayName = l.ProviderDisplayName ?? l.LoginProvider,
            boundAt = _context.UserLogins
                .Where(x => x.UserUid == user.Uid
                    && x.LoginProvider == l.LoginProvider
                    && x.ProviderKey == l.ProviderKey)
                .Select(x => (DateTimeOffset?)x.CreatedAt)
                .FirstOrDefault()
        }).ToList();

        return Ok(new { Success = true, Logins = items });
    }

    [HttpDelete("external-logins/{provider}")]
    public async Task<IActionResult> RemoveExternalLogin(string provider)
    {
        _logger.LogDebug("解绑外部登录 | Provider:{Provider}", provider);

        var (user, userError) = await RequireUserAsync();
        if (userError is not null) return userError;

        var logins = await _userManager.GetLoginsAsync(user);
        var matched = logins.FirstOrDefault(l =>
            string.Equals(l.LoginProvider, provider, StringComparison.OrdinalIgnoreCase));
        if (matched is null)
        {
            return NotFound(new { Success = false, Error = "未找到该绑定。", ErrorCode = "not_found" });
        }

        await _userManager.RemoveLoginAsync(user, matched.LoginProvider, matched.ProviderKey);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ExternalLoginUnbound,
            user.Uid.ToString(), user.Email, true, $"Provider: {matched.LoginProvider}");

        _logger.LogInformation("外部登录解绑 | uid:{Uid} | Provider:{Provider}", user.Uid, provider);

        return Ok(new { Success = true });
    }

    private async Task<IActionResult?> SendEmailCodeSafeAsync(User user, string email, string code, MailThemeKind kind, string action)
    {
        try
        {
            await _emailSender.SendVerificationCodeAsync(kind, email, code);
            return null;
        }
        catch (Exception ex)
        {
            _logger.LogError("邮件发送失败 | 操作:{Action} uid:{Uid} → {Email}", action, user.Uid, email);
            return StatusCode(503, new EmailCodeResponse
            {
                Success = false,
                Error = "邮件发送失败，请检查 SMTP 配置或稍后重试。",
                ErrorCode = "email_send_failed"
            });
        }
    }

    private async Task<(User? User, IActionResult? Error)> RequireUserAsync()
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
        {
            _logger.LogWarning("用户未认证");
            return (null, Unauthorized(new { Success = false, Error = "未登录。", ErrorCode = "invalid_session" }));
        }
        return (user, null);
    }

    private IActionResult MapEmailCodeError(EmailCodeResult result) => result.Status switch
    {
        EmailCodeStatus.NotFound => BadRequest(new EmailCodeResponse { Success = false, Error = "验证会话已过期，请重新操作。", ErrorCode = "invalid_session" }),
        EmailCodeStatus.Expired => BadRequest(new EmailCodeResponse { Success = false, Error = "验证码已过期，请重新获取。", ErrorCode = "expired" }),
        EmailCodeStatus.MaxAttempts => BadRequest(new EmailCodeResponse { Success = false, Error = "尝试次数过多，请稍后重试。", ErrorCode = "max_attempts" }),
        _ => BadRequest(new EmailCodeResponse { Success = false, Error = "验证码错误。", ErrorCode = "wrong_code" })
    };
}
