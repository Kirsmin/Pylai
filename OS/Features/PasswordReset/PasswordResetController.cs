using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.PasswordReset;

[ApiController]
[Route("api/auth")]
public class PasswordResetController : ControllerBase
{
    private readonly EmailSender _emailSender;
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
        EmailSender emailSender,
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
        var transactionId = AuthHelper.GenerateOpaqueToken();
        var transactionKey = TransactionKey(transactionId);
        var ip = this.GetClientIp(_ipResolver);

        if (await _ipRateLimitService.IsRateLimited(ip, "forgot-password", 3, TimeSpan.FromMinutes(10)))
        {
            await _emailCodeService.CreateAsync(transactionKey, null);
            return Ok(new ForgotPasswordResponse { Success = true, TransactionId = transactionId });
        }

        await _ipRateLimitService.RecordAttempt(ip, "forgot-password", TimeSpan.FromMinutes(10));

        User? user = null;
        if (AuthHelper.IsValidEmail(request.Email ?? string.Empty))
        {
            var normalizedEmail = UsernameNormalizer.Normalize(request.Email!);
            user = await _context.Users.FirstOrDefaultAsync(u =>
                u.NormalizedEmail != null
                && u.NormalizedEmail == normalizedEmail
                && u.Status != UserStatus.Deleted);
        }

        if (user is not null && !string.IsNullOrEmpty(user.Email))
        {
            var code = await _emailCodeService.CreateAsync(transactionKey, user.Email, user.Uid);
            _logger.LogCode(_testMode, LogLevel.Debug, "重置码生成 | transaction:{Transaction}", code, transactionId[..8]);

            try
            {
                await _emailSender.SendPasswordResetCodeAsync(user, user.Email, code);
                _logger.LogInformation("密码重置邮件已发送 | uid:{Uid}", user.Uid);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "密码重置邮件发送失败 | uid:{Uid}", user.Uid);
            }
        }
        else
        {
            // 邮箱不存在：不创建验证码条目、不发送邮件，仅保持响应形状一致（防时序侧信道）。
        }

        return Ok(new ForgotPasswordResponse { Success = true, TransactionId = transactionId });
    }

    [AllowAnonymous]
    [HttpPost("reset-password")]
    public async Task<IActionResult> ResetPassword([FromBody] ResetPasswordRequest request)
    {
        if (!ModelState.IsValid)
            return BadRequest(InvalidOrExpired());

        var ip = this.GetClientIp(_ipResolver);
        if (await _ipRateLimitService.IsRateLimited(ip, "reset-password", 5, TimeSpan.FromMinutes(10)))
            return StatusCode(429, new PasswordResponse { Success = false, Error = "请求过于频繁，请稍后重试。", ErrorCode = "rate_limited" });

        await _ipRateLimitService.RecordAttempt(ip, "reset-password", TimeSpan.FromMinutes(10));

        var key = TransactionKey(request.TransactionId);

        // 1. 先只读查询验证码条目（不消费），确认事务有效并获取关联用户
        var entry = await _emailCodeService.PeekAsync(key);
        if (entry is null || entry.UserUid is null)
            return BadRequest(InvalidOrExpired());

        var user = await _context.Users.FirstOrDefaultAsync(u =>
            u.Uid == entry.UserUid.Value && u.Status != UserStatus.Deleted);
        if (user is null)
            return BadRequest(InvalidOrExpired());

        // 2. 校验密码策略（此时验证码仍未被消费，允许用户修正密码后重试）
        var pwErrors = await AuthHelper.ValidatePasswordAsync(_userManager, user, request.NewPassword);
        if (pwErrors.Count > 0)
            return BadRequest(new PasswordResponse { Success = false, Error = pwErrors[0].Description, ErrorCode = "invalid_password" });

        // 3. 密码策略通过后，才真正校验并消费验证码
        var verifyResult = await _emailCodeService.VerifyAsync(key, request.Code);
        if (verifyResult.Status != EmailCodeStatus.Ok)
            return BadRequest(InvalidOrExpired());

        // 4. 执行重置
        user.PasswordHash = _passwordHasher.HashPassword(user, request.NewPassword);
        await _userAccessRevoker.RevokeUserAccessAsync(user.Uid);
        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.PasswordReset, user.Uid.ToString(), null, true);

        _logger.LogInformation("密码重置完成 | uid:{Uid}", user.Uid);
        return Ok(new PasswordResponse { Success = true });
    }

    private static string TransactionKey(string transactionId)
        => $"password-reset-tx:{AuthHelper.HashCode(transactionId)}";

    private static PasswordResponse InvalidOrExpired()
        => new()
        {
            Success = false,
            Error = "重置事务无效或已过期。",
            ErrorCode = "invalid_or_expired"
        };
}
