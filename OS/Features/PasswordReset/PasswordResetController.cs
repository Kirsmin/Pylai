using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.PasswordReset;

[ApiController]
[Route("api/auth")]
public class PasswordResetController : ControllerBase
{
    private readonly IEmailSender<User> _emailSender;
    private readonly IpRateLimitService _ipRateLimitService;
    private readonly IpResolutionService _ipResolver;
    private readonly IPasswordHasher<User> _passwordHasher;
    private readonly UserManager<User> _userManager;
    private readonly ApplicationDbContext _context;
    private readonly IEmailVerificationCodeService _emailCodeService;
    private readonly IUserAccessRevoker _userAccessRevoker;
    private readonly IAuditService _auditService;
    private readonly TestModeOptions _testMode;
    private readonly ILogger<PasswordResetController> _logger;

    public PasswordResetController(
        IEmailSender<User> emailSender,
        IpRateLimitService ipRateLimitService,
        IpResolutionService ipResolver,
        IPasswordHasher<User> passwordHasher,
        UserManager<User> userManager,
        ApplicationDbContext context,
        IEmailVerificationCodeService emailCodeService,
        IUserAccessRevoker userAccessRevoker,
        IAuditService auditService,
        TestModeOptions testMode,
        ILogger<PasswordResetController> logger)
    {
        _emailSender = emailSender;
        _ipRateLimitService = ipRateLimitService;
        _ipResolver = ipResolver;
        _passwordHasher = passwordHasher;
        _userManager = userManager;
        _context = context;
        _emailCodeService = emailCodeService;
        _userAccessRevoker = userAccessRevoker;
        _auditService = auditService;
        _testMode = testMode;
        _logger = logger;
    }

    [AllowAnonymous]
    [HttpPost("forgot-password")]
    public async Task<IActionResult> ForgotPassword([FromBody] ForgotPasswordRequest request)
    {
        _logger.LogDebug("忘记密码请求 | {Email}", request.Email);

        if (!ModelState.IsValid)
        {
            _logger.LogWarning("请求参数无效");
            return Ok(new { success = true });
        }

        if (!AuthHelper.IsValidEmail(request.Email))
        {
            _logger.LogWarning("邮箱格式无效 | {Email}", request.Email ?? "null/empty");
            return Ok(new { success = true });
        }

        var ip = this.GetClientIp(_ipResolver);
        if (await _ipRateLimitService.IsRateLimited(ip, "forgot-password", 3, TimeSpan.FromMinutes(10)))
        {
            _logger.LogWarning("密码重置限流触发 | IP:{Ip}", ip);
            return Ok(new { success = true });
        }

        await _ipRateLimitService.RecordAttempt(ip, "forgot-password", TimeSpan.FromMinutes(10));

        var normalizedEmail = UsernameNormalizer.Normalize(request.Email);

        var user = await _context.Users
            .FirstOrDefaultAsync(u => u.NormalizedEmail != null && u.NormalizedEmail == normalizedEmail
                && u.Status != UserStatus.Deleted);

        if (user is not null && !string.IsNullOrEmpty(user.Email))
        {
            var code = await _emailCodeService.CreateAsync($"password-reset:{user.Uid}", user.Email);

            _logger.LogCode(_testMode, LogLevel.Debug, "重置码生成 | uid:{Uid} | → {Email}", code, user.Uid, user.Email);

            try
            {
                await _emailSender.SendPasswordResetCodeAsync(user, user.Email, code);
                _logger.LogCode(_testMode, LogLevel.Information, "重置码已发送 → {Email} | uid:{Uid}", code, user.Uid, user.Email);
            }
            catch (Exception ex)
            {
                // 忘记密码接口保持恒成功，避免泄露邮箱是否注册；发送失败仅记录日志。
                _logger.LogError("密码重置邮件发送失败 | uid:{Uid} → {Email}", user.Uid, user.Email);
            }
        }
        else
        {
            _logger.LogDebug("邮箱未注册 | {Email}", request.Email);
        }

        return Ok(new { success = true });
    }

    [AllowAnonymous]
    [HttpPost("reset-password")]
    public async Task<IActionResult> ResetPassword([FromBody] ResetPasswordRequest request)
    {
        _logger.LogDebug("重置密码请求 | {Email}", request.Email);

        if (!ModelState.IsValid)
        {
            _logger.LogWarning("请求参数无效");
            return BadRequest(new PasswordResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });
        }

        var ip = this.GetClientIp(_ipResolver);
        if (await _ipRateLimitService.IsRateLimited(ip, "reset-password", 5, TimeSpan.FromMinutes(10)))
        {
            _logger.LogWarning("密码重置限流触发 | IP:{Ip}", ip);
            return StatusCode(429, new PasswordResponse { Success = false, Error = "请求过于频繁，请稍后重试。", ErrorCode = "rate_limited" });
        }

        await _ipRateLimitService.RecordAttempt(ip, "reset-password", TimeSpan.FromMinutes(10));

        var user = await _context.Users
            .FirstOrDefaultAsync(u => u.NormalizedEmail != null && u.NormalizedEmail == UsernameNormalizer.Normalize(request.Email)
                && u.Status != UserStatus.Deleted);

        if (user is null)
        {
            _logger.LogWarning("重置用户不存在 | {Email}", request.Email);
            return BadRequest(new PasswordResponse { Success = false, Error = "重置验证码已过期或无效。", ErrorCode = "expired" });
        }

        _logger.LogDebug("重置用户匹配 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        var key = $"password-reset:{user.Uid}";
        var result = await _emailCodeService.VerifyAsync(key, request.Code);
        if (result.Status != EmailCodeStatus.Ok)
            return MapResetCodeError(result);

        _logger.LogDebug("重置码验证通过，更新密码 | uid:{Uid}", user.Uid);

        var pwErrors = await AuthHelper.ValidatePasswordAsync(_userManager, user, request.NewPassword);
        if (pwErrors.Count > 0)
        {
            _logger.LogWarning("新密码不符合策略 | uid:{Uid} | 错误:{Errors}", user.Uid, string.Join("; ", pwErrors.Select(e => e.Description)));
            return BadRequest(new PasswordResponse { Success = false, Error = pwErrors[0].Description, ErrorCode = "invalid_password" });
        }

        user.PasswordHash = _passwordHasher.HashPassword(user, request.NewPassword);
        await _userAccessRevoker.RevokeUserAccessAsync(user.Uid);

        await _emailCodeService.RemoveAsync(key);
        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.PasswordReset, user.Uid.ToString(), user.Email, true);
        _logger.LogInformation("密码重置完成 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        return Ok(new PasswordResponse { Success = true });
    }

    private IActionResult MapResetCodeError(EmailCodeResult result) => result.Status switch
    {
        EmailCodeStatus.NotFound => BadRequest(new PasswordResponse { Success = false, Error = "重置验证码已过期或无效。", ErrorCode = "expired" }),
        EmailCodeStatus.Expired => BadRequest(new PasswordResponse { Success = false, Error = "重置验证码已过期。", ErrorCode = "expired" }),
        EmailCodeStatus.MaxAttempts => BadRequest(new PasswordResponse { Success = false, Error = "尝试次数过多，请重新发起重置。", ErrorCode = "max_attempts" }),
        _ => BadRequest(new PasswordResponse { Success = false, Error = "重置验证码错误。", ErrorCode = "wrong_code", AttemptsRemaining = result.AttemptsRemaining })
    };

}
