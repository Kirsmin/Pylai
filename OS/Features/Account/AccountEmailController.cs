using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Pylaios.Features.Account;

/// <summary>
/// 邮箱绑定 / 更换（验证码状态机，EmailVerificationCodeService 共用）。
/// </summary>
[ApiController]
[Route("api/auth/account")]
[Authorize(AuthenticationSchemes = "Identity.Application,UserToken")]
public class AccountEmailController : ControllerBase
{
    private readonly IPasswordHasher<User> _passwordHasher;
    private readonly EmailSender _emailSender;
    private readonly ApplicationDbContext _context;
    private readonly IEmailVerificationCodeService _emailCodeService;
    private readonly IUserAccessRevoker _userAccessRevoker;
    private readonly TestModeOptions _testMode;
    private readonly ILogger<AccountEmailController> _logger;

    public AccountEmailController(
        IPasswordHasher<User> passwordHasher,
        EmailSender emailSender,
        ApplicationDbContext context,
        IEmailVerificationCodeService emailCodeService,
        IUserAccessRevoker userAccessRevoker,
        TestModeOptions testMode,
        ILogger<AccountEmailController> logger)
    {
        _passwordHasher = passwordHasher;
        _emailSender = emailSender;
        _context = context;
        _emailCodeService = emailCodeService;
        _userAccessRevoker = userAccessRevoker;
        _testMode = testMode;
        _logger = logger;
    }

    [HttpPost("email/bind")]
    public async Task<IActionResult> BindEmail([FromBody] BindEmailRequest request)
    {
        _logger.LogDebug("绑定邮箱请求 | {Email}", request.Email);

        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

        _logger.LogDebug("绑定邮箱 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        if (!ModelState.IsValid)
        {
            _logger.LogWarning("请求参数无效");
            return BadRequest(new EmailCodeResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });
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
        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

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
        _logger.LogDebug("更换邮箱请求 | {NewEmail}", request.NewEmail);

        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

        _logger.LogDebug("更换邮箱 | uid:{Uid} | 当前:{CurrentEmail}", user.Uid, user.Email);

        if (!ModelState.IsValid)
        {
            _logger.LogWarning("请求参数无效");
            return BadRequest(new EmailCodeResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });
        }

        if (!AuthHelper.IsValidEmail(request.NewEmail))
        {
            _logger.LogWarning("邮箱格式无效 | {NewEmail}", request.NewEmail ?? "null/empty");
            return BadRequest(new EmailCodeResponse { Success = false, Error = "邮箱地址格式不正确。", ErrorCode = "invalid_format" });
        }

        if (string.IsNullOrEmpty(user.Email))
        {
            _logger.LogWarning("未绑定邮箱，请先绑定 | uid:{Uid}", user.Uid);
            return BadRequest(new EmailCodeResponse { Success = false, Error = "未绑定邮箱，请先绑定邮箱。", ErrorCode = "email_required" });
        }

        if (await _context.IsEmailTakenAsync(request.NewEmail))
        {
            _logger.LogWarning("新邮箱已被其他用户占用 | uid:{Uid} | {NewEmail}", user.Uid, request.NewEmail);
            return StatusCode(403, new EmailCodeResponse { Success = false, Error = "邮箱验证已被限制，请稍后重试。", ErrorCode = "banned" });
        }

        var code = await _emailCodeService.CreateAsync($"change-email:{user.Uid}", request.NewEmail);

        _logger.LogCode(_testMode, LogLevel.Debug, "验证码生成 | uid:{Uid} | → {NewEmail}", code, user.Uid, request.NewEmail);

        var sendError = await SendEmailCodeSafeAsync(user, user.Email, code, MailThemeKind.Change, "更换邮箱");
        if (sendError is not null) return sendError;

        _logger.LogCode(_testMode, LogLevel.Information, "更换邮箱验证码已发送 | uid:{Uid} | → {NewEmail}", code, user.Uid, request.NewEmail);

        return Ok(new EmailCodeResponse { Success = true, Sent = true, PendingEmail = request.NewEmail });
    }

    [HttpPost("email/change/confirm")]
    public async Task<IActionResult> ChangeEmailConfirm([FromBody] EmailCodeRequest request)
    {
        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

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
        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

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
        await _userAccessRevoker.RevokeUserAccessAsync(user.Uid, revokeUserToken: true);

        _logger.LogInformation("邮箱更换成功 | uid:{Uid} | {Email}", user.Uid, result.Entry.Email);

        return Ok(new EmailCodeResponse { Success = true, VerifiedEmail = result.Entry.Email });
    }

    private async Task<IActionResult?> SendEmailCodeSafeAsync(User user, string email, string code, MailThemeKind kind, string action)
    {
        try
        {
            await _emailSender.SendVerificationCodeAsync(kind, email, code);
            return null;
        }
        catch (Exception)
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

    private IActionResult MapEmailCodeError(EmailCodeResult result) => result.Status switch
    {
        EmailCodeStatus.NotFound => BadRequest(new EmailCodeResponse { Success = false, Error = "验证会话已过期，请重新操作。", ErrorCode = "invalid_session" }),
        EmailCodeStatus.Expired => BadRequest(new EmailCodeResponse { Success = false, Error = "验证码已过期，请重新获取。", ErrorCode = "expired" }),
        EmailCodeStatus.MaxAttempts => BadRequest(new EmailCodeResponse { Success = false, Error = "尝试次数过多，请稍后重试。", ErrorCode = "max_attempts" }),
        _ => BadRequest(new EmailCodeResponse { Success = false, Error = "验证码错误。", ErrorCode = "wrong_code" })
    };
}
