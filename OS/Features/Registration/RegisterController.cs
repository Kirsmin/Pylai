using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Pylaios.Features.Registration;

[ApiController]
[Route("api/auth/register")]
public class RegisterController : ControllerBase
{
    private readonly UserManager<User> _userManager;
    private readonly IPasswordHasher<User> _passwordHasher;
    private readonly EmailSender _emailSender;
    private readonly IInviteCodeService _inviteCodeService;
    private readonly IEmailVerificationBlockService _emailBlockService;
    private readonly IpRateLimitService _ipRateLimitService;
    private readonly IpResolutionService _ipResolver;
    private readonly RegistrationSessionService _sessionService;
    private readonly MainConfig _config;
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly TestModeOptions _testMode;
    private readonly ILogger<RegisterController> _logger;

    public RegisterController(
        UserManager<User> userManager,
        IPasswordHasher<User> passwordHasher,
        EmailSender emailSender,
        IInviteCodeService inviteCodeService,
        IEmailVerificationBlockService emailBlockService,
        IpRateLimitService ipRateLimitService,
        IpResolutionService ipResolver,
        RegistrationSessionService sessionService,
        MainConfig config,
        ApplicationDbContext context,
        IAuditService auditService,
        TestModeOptions testMode,
        ILogger<RegisterController> logger)
    {
        _userManager = userManager;
        _passwordHasher = passwordHasher;
        _emailSender = emailSender;
        _inviteCodeService = inviteCodeService;
        _emailBlockService = emailBlockService;
        _ipRateLimitService = ipRateLimitService;
        _ipResolver = ipResolver;
        _sessionService = sessionService;
        _config = config;
        _context = context;
        _auditService = auditService;
        _testMode = testMode;
        _logger = logger;
    }

    [HttpPost("init")]
    public async Task<IActionResult> RegisterInit()
    {
        _logger.LogDebug("注册初始化请求");

        var ip = this.GetClientIp(_ipResolver);
        if (await _ipRateLimitService.IsRateLimited(ip, "register", 10, TimeSpan.FromMinutes(1)))
        {
            _logger.LogWarning("注册限流触发 | IP:{Ip}", ip);
            return StatusCode(429, new RegisterInitResponse
            {
                Success = false,
                IpBanned = true,
                Error = "请求过于频繁，请稍后重试。",
                ErrorCode = "rate_limited"
            });
        }

        await _ipRateLimitService.RecordAttempt(ip, "register", TimeSpan.FromMinutes(1));

        var token = await _sessionService.CreateSessionAsync();
        _logger.LogDebug("会话创建 | token:{Token}", token[..Math.Min(16, token.Length)]);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.RegisterStarted, null, null, true, $"Session {token[..8]}... created");

        _logger.LogInformation("注册初始化");

        return Ok(new RegisterInitResponse
        {
            Success = true,
            SessionToken = token,
            IpBanned = false
        });
    }

    [HttpPost("send-email-code")]
    public async Task<IActionResult> SendEmailCode([FromBody] SendEmailCodeRequest request)
    {
        _logger.LogDebug("发送邮箱码请求 | token:{Token}", LogToken(request.SessionToken));

        var (session, sessionError) = await RequireSessionAsync(request.SessionToken, 1);
        if (session is null) return sessionError!;

        var ip = this.GetClientIp(_ipResolver);

        var (ipBanned, _) = await _emailBlockService.IsIpBannedAsync(ip);
        if (ipBanned)
        {
            _logger.LogWarning("IP已被邮箱验证封禁 | {Ip}", ip);
            return StatusCode(403, new SendEmailCodeResponse { Success = false, Error = "邮箱验证已被限制，请稍后重试。", ErrorCode = "banned" });
        }

        if (string.IsNullOrEmpty(request.Email) || !AuthHelper.IsValidEmail(request.Email))
        {
            _logger.LogWarning("邮箱格式无效 | {Email}", request.Email ?? "null/empty");
            return BadRequest(new SendEmailCodeResponse { Success = false, Error = "邮箱地址格式不正确。", ErrorCode = "invalid_format" });
        }

        if (session.EmailChangeCount >= 2)
        {
            _logger.LogWarning("邮箱更换已达上限 | 次数:{Changes}", session.EmailChangeCount);
            return BadRequest(new SendEmailCodeResponse
            {
                Success = false,
                Error = "已达到邮箱更换次数上限。",
                ErrorCode = "max_changes",
                ChangesRemaining = 0
            });
        }

        var code = AuthHelper.GenerateCode();
        _logger.LogCode(_testMode, LogLevel.Debug, "验证码生成 → {Email}", code, request.Email);

        session.PendingEmail = request.Email;
        session.EmailCodeHash = AuthHelper.HashCode(code);
        session.EmailCodeExpires = DateTimeOffset.UtcNow.AddMinutes(_config.Identity.EmailCodeExpireMinutes);
        session.EmailCodeAttempts = 0;
        session.Step = 2;
        await _sessionService.UpdateSessionAsync(request.SessionToken, session);

        if (await _context.IsEmailTakenAsync(request.Email))
        {
            _logger.LogWarning("邮箱已被占用 | {Email}（等效正常流程处理，不触发真实发送）", request.Email);
            await Task.Delay(Random.Shared.Next(150, 300));
            return Ok(new SendEmailCodeResponse
            {
                Success = true,
                ChangesRemaining = 2 - session.EmailChangeCount
            });
        }

        var dummy = new User();
        try
        {
            await _emailSender.SendRegisterCodeAsync(dummy, request.Email, code);
        }
        catch (Exception)
        {
            _logger.LogError("验证码邮件发送失败 | → {Email}", request.Email);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailVerificationSent, null, request.Email, false, "SMTP send failed", request.SessionToken);
            return StatusCode(503, new SendEmailCodeResponse
            {
                Success = false,
                Error = "邮件发送失败，请检查 SMTP 配置或稍后重试。",
                ErrorCode = "email_send_failed"
            });
        }

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailVerificationSent, null, request.Email, true, null, request.SessionToken);

        _logger.LogCode(_testMode, LogLevel.Information, "验证码已发送 → {Email}", code, request.Email);

        return Ok(new SendEmailCodeResponse
        {
            Success = true,
            ChangesRemaining = 2 - session.EmailChangeCount
        });
    }

    [HttpPost("verify-email")]
    public async Task<IActionResult> VerifyEmail([FromBody] VerifyEmailRequest request)
    {
        _logger.LogDebug("验证邮箱请求 | token:{Token}", LogToken(request.SessionToken));

        var (session, sessionError) = await RequireSessionAsync(request.SessionToken, 2);
        if (session is null) return sessionError!;

        if (session.EmailCodeExpires is null || session.EmailCodeExpires < DateTimeOffset.UtcNow)
        {
            _logger.LogWarning("验证码已过期");
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailVerificationExpired, null, session.PendingEmail, false, null, request.SessionToken);
            return BadRequest(new VerifyEmailResponse { Success = false, Error = "验证码已过期，请重新获取。", ErrorCode = "expired" });
        }

        if (session.EmailCodeAttempts >= 5)
        {
            _logger.LogWarning("验证尝试已达上限 | 尝试:{Attempts}", session.EmailCodeAttempts);

            if (session.EmailChangeCount >= 2)
            {
                var ip = this.GetClientIp(_ipResolver);
                await _emailBlockService.BanNowAsync(ip);

                _logger.LogWarning("邮箱验证耗尽，IP封禁 | {Ip}", ip);

                await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailVerificationIpBanned, null, session.PendingEmail, false,
                    $"IP {ip} banned for 24h after email exhaustion", request.SessionToken);
                await _sessionService.RemoveSessionAsync(request.SessionToken);
                return BadRequest(new VerifyEmailResponse { Success = false, Error = "尝试次数过多，请24小时后重试。", ErrorCode = "max_attempts" });
            }

            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailVerificationMaxAttempts, null, session.PendingEmail, false,
                $"Attempts: {session.EmailCodeAttempts}, ChangesUsed: {session.EmailChangeCount}", request.SessionToken);
            return BadRequest(new VerifyEmailResponse { Success = false, Error = "验证码错误次数过多，请更换邮箱后重试。", ErrorCode = "max_attempts" });
        }

        session.EmailCodeAttempts++;
        await _sessionService.UpdateSessionAsync(request.SessionToken, session);

        _logger.LogDebug("验证码校验中 | 尝试:{Attempts}/5 | → {Email}", session.EmailCodeAttempts, session.PendingEmail);

        if (!AuthHelper.CodeEquals(session.EmailCodeHash!, AuthHelper.HashCode(request.Code)))
        {
            var remaining = 5 - session.EmailCodeAttempts;
            _logger.LogWarning("验证码错误 | 尝试:{Attempts} | 剩余:{Remaining}", session.EmailCodeAttempts, remaining);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailVerificationFailed, null, session.PendingEmail, false, $"Remaining: {remaining}", request.SessionToken);
            return BadRequest(new VerifyEmailResponse
            {
                Success = false,
                Error = "验证码错误。",
                ErrorCode = "wrong_code"
            });
        }

        session.Step = 3;
        session.EmailCodeHash = null;
        session.EmailCodeExpires = null;
        await _sessionService.UpdateSessionAsync(request.SessionToken, session);

        _logger.LogInformation("邮箱验证通过 | {Email}", session.PendingEmail);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailVerificationSuccess, null, session.PendingEmail, true, null, request.SessionToken);
        return Ok(new VerifyEmailResponse { Success = true });
    }

    [HttpPost("change-email")]
    public async Task<IActionResult> ChangeRegistrationEmail([FromBody] ChangeRegistrationEmailRequest request)
    {
        _logger.LogDebug("注册中更换邮箱请求 | {Email} | token:{Token}",
            request.NewEmail, LogToken(request.SessionToken));

        var (session, sessionError) = await RequireSessionAsync(request.SessionToken, 2);
        if (session is null) return sessionError!;

        if (session.EmailChangeCount >= 2)
        {
            _logger.LogWarning("邮箱更换已达上限 | 次数:{Changes}", session.EmailChangeCount);
            return BadRequest(new ChangeRegistrationEmailResponse
            {
                Success = false,
                ChangesRemaining = 0,
                Error = "已达到邮箱更换次数上限。",
                ErrorCode = "max_changes"
            });
        }

        if (string.IsNullOrEmpty(request.NewEmail) || !AuthHelper.IsValidEmail(request.NewEmail))
        {
            _logger.LogWarning("邮箱格式无效 | {Email}", request.NewEmail ?? "null/empty");
            return BadRequest(new ChangeRegistrationEmailResponse { Success = false, Error = "邮箱地址格式不正确。", ErrorCode = "invalid_format" });
        }

        if (await _context.IsEmailTakenAsync(request.NewEmail))
        {
            _logger.LogWarning("邮箱已被占用 | {Email}", request.NewEmail);
            return StatusCode(403, new ChangeRegistrationEmailResponse { Success = false, Error = "邮箱验证已被限制，请稍后重试。", ErrorCode = "banned" });
        }

        var code = AuthHelper.GenerateCode();
        _logger.LogCode(_testMode, LogLevel.Debug, "验证码生成 → {Email}", code, request.NewEmail);

        session.PendingEmail = request.NewEmail;
        session.EmailCodeHash = AuthHelper.HashCode(code);
        session.EmailCodeExpires = DateTimeOffset.UtcNow.AddMinutes(_config.Identity.EmailCodeExpireMinutes);
        session.EmailCodeAttempts = 0;
        session.EmailChangeCount++;

        var remaining = 2 - session.EmailChangeCount;
        await _sessionService.UpdateSessionAsync(request.SessionToken, session);

        var dummy = new User();
        try
        {
            await _emailSender.SendRegisterCodeAsync(dummy, request.NewEmail, code);
        }
        catch (Exception)
        {
            _logger.LogError("更换邮箱验证码发送失败 | → {NewEmail}", request.NewEmail);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailChanged, null, request.NewEmail, false, "SMTP send failed", request.SessionToken);
            return StatusCode(503, new ChangeRegistrationEmailResponse
            {
                Success = false,
                Error = "邮件发送失败，请检查 SMTP 配置或稍后重试。",
                ErrorCode = "email_send_failed",
                ChangesRemaining = remaining
            });
        }

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.EmailChanged, null, request.NewEmail, true, $"Change #{session.EmailChangeCount}", request.SessionToken);

        _logger.LogCode(_testMode, LogLevel.Information,
            "更换邮箱验证码已发送 → {NewEmail} | 剩余更换:{Remaining}", code, request.NewEmail, remaining);

        return Ok(new ChangeRegistrationEmailResponse { Success = true, ChangesRemaining = remaining });
    }

    [HttpPost("check-username")]
    public async Task<IActionResult> CheckUsername([FromBody] UsernameCheckRequest request)
    {
        _logger.LogDebug("用户名检查请求 | {Username}", request.Username);

        var (session, sessionError) = await RequireSessionAsync(request.SessionToken, 3, unauthorized: true);
        if (session is null) return sessionError!;

        var ip = this.GetClientIp(_ipResolver);
        if (await _ipRateLimitService.IsRateLimited(ip, "check-username", _config.InviteCode.UsernameCheckMaxPerHourPerIp, TimeSpan.FromHours(1)))
        {
            _logger.LogWarning("用户名检查限流 | IP:{Ip}", ip);
            return StatusCode(429, new UsernameCheckResponse { Success = false, Error = "请求过于频繁，请稍后重试。", ErrorCode = "rate_limited" });
        }

        await _ipRateLimitService.RecordAttempt(ip, "check-username", TimeSpan.FromHours(1));

        var (valid, error) = UsernameNormalizer.Validate(request.Username);
        if (!valid)
        {
            _logger.LogWarning("用户名格式无效 | {Username} | {Error}", request.Username, error);
            return BadRequest(new UsernameCheckResponse { Success = false, Error = error, ErrorCode = "invalid_format" });
        }

        var normalized = UsernameNormalizer.Normalize(request.Username);
        _logger.LogDebug("用户名标准化 | {Original} → {Normalized}", request.Username, normalized);

        var exists = await _context.Users.AnyAsync(u => u.Name == normalized);
        if (exists)
        {
            _logger.LogWarning("用户名已被占用 | {Normalized}", normalized);
            return BadRequest(new UsernameCheckResponse { Success = false, Error = "用户名已被占用。", ErrorCode = "duplicate" });
        }

        session.NormalizedName = normalized;
        session.DisplayName = request.Username;
        session.Step = 4;
        await _sessionService.UpdateSessionAsync(request.SessionToken, session);

        _logger.LogDebug("用户名可用 | {Normalized} | 显示名:{DisplayName}", normalized, request.Username);

        return Ok(new UsernameCheckResponse { Success = true, NormalizedName = normalized, DisplayName = request.Username });
    }

    [HttpPost("create")]
    public async Task<IActionResult> CreateAccount([FromBody] CreateAccountRequest request)
    {
        _logger.LogDebug("创建账户请求 | token:{Token}", LogToken(request.SessionToken));

        var (session, sessionError) = await RequireSessionAsync(request.SessionToken, 4);
        if (session is null) return sessionError!;

        if (string.IsNullOrEmpty(request.Password))
        {
            _logger.LogWarning("密码为空");
            return BadRequest(new CreateAccountResponse { Success = false, Error = "密码不能为空。", ErrorCode = "invalid_format" });
        }

        var tempUser = new User { Name = session.NormalizedName!, SecurityStamp = Guid.NewGuid().ToString() };
        var pwErrors = await AuthHelper.ValidatePasswordAsync(_userManager, tempUser, request.Password);
        if (pwErrors.Count > 0)
        {
            _logger.LogWarning("密码格式无效 | 错误:{Errors}", string.Join("; ", pwErrors.Select(e => e.Description)));
            return BadRequest(new CreateAccountResponse { Success = false, Error = pwErrors[0].Description, ErrorCode = "invalid_password" });
        }

        var user = new User
        {
            Status = UserStatus.Active,
            Name = session.NormalizedName!,
            DisplayName = session.DisplayName ?? session.NormalizedName,
            Group = AuthConstants.Roles.Normal,
            SecurityStamp = Guid.NewGuid().ToString(),
            RegisterTime = DateTimeOffset.UtcNow
        };

        if (session.PendingEmail is not null)
        {
            user.Email = session.PendingEmail;
            user.NormalizedEmail = UsernameNormalizer.Normalize(session.PendingEmail);
        }

        user.PasswordHash = _passwordHasher.HashPassword(user, request.Password);

        var sessionTokenHash = AuthHelper.HashCode(request.SessionToken);
        var binding = new RegistrationSessionBinding
        {
            SessionTokenHash = sessionTokenHash,
            UserUid = user.Uid
        };

        for (var attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                await using var transaction = await _context.Database.BeginTransactionAsync();
                _context.Users.Add(user);
                _context.RegistrationSessionBindings.Add(binding);
                await _context.SaveChangesAsync();
                await transaction.CommitAsync();
                break;
            }
            catch (DbUpdateException ex) when (ex.IsUniqueViolation())
            {
                _context.ChangeTracker.Clear();
                return Conflict(new CreateAccountResponse
                {
                    Success = false,
                    Error = "用户名或邮箱已被占用。",
                    ErrorCode = "duplicate"
                });
            }
            catch (DbUpdateException ex)
            {
                _context.ChangeTracker.Clear();
                if (attempt == 0 && ex.SqlState() is "40P01" or "40001")
                {
                    _logger.LogWarning("注册入库并发冲突（死锁/序列化），重试 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);
                    continue;
                }
                _logger.LogError(ex, "注册入库最终失败 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);
                return Conflict(new CreateAccountResponse
                {
                    Success = false,
                    Error = "用户名或邮箱已被占用。",
                    ErrorCode = "duplicate"
                });
            }
            catch (PostgresException ex) when (ex.SqlState is "53300" or "08006" or "08001" or "08004")
            {
                _logger.LogError("数据库连接不可用（{SqlState}），注册暂时拒绝 | uid:{Uid}", ex.SqlState, user.Uid);
                return StatusCode(503, new CreateAccountResponse
                {
                    Success = false,
                    Error = "服务器繁忙，请稍后重试。",
                    ErrorCode = "server_busy"
                });
            }
        }

        _logger.LogDebug("用户创建 | uid:{Uid} | 用户:{Name} | {Email}", user.Uid, user.Name, user.Email);

        session.UserUid = user.Uid;
        session.Step = 5;
        try
        {
            await _sessionService.UpdateSessionAsync(request.SessionToken, session);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "用户已创建，但 Redis 注册会话更新失败 | uid:{Uid}", user.Uid);
        }

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.UserCreated, user.Uid.ToString(), user.Email, true,
            $"Name: {user.Name}, Group: normal");

        _logger.LogInformation("用户创建完成 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        return Ok(new CreateAccountResponse
        {
            Success = true,
            Uid = user.Uid,
            Name = user.Name,
            DisplayName = user.DisplayName,
            Group = AuthConstants.Roles.Normal
        });
    }

    [HttpPost("redeem-invite")]
    public async Task<IActionResult> RedeemInviteCode([FromBody] InviteCodeRedeemRequest request)
    {
        _logger.LogDebug("邀请码提权请求 | token:{Token}", LogToken(request.SessionToken));

        var (session, sessionError) = await RequireSessionAsync(request.SessionToken, 5);
        if (session is null) return sessionError!;

        if (string.IsNullOrEmpty(request.InviteCode))
        {
            session.Step = 6;
            await _sessionService.UpdateSessionAsync(request.SessionToken, session);
            _logger.LogDebug("用户跳过邀请码 | uid:{Uid}", session.UserUid);
            return Ok(new InviteCodeRedeemResponse { Success = true, Skipped = true });
        }

        var ip = this.GetClientIp(_ipResolver);

        var invitePrefix = request.InviteCode.Trim();
        if (invitePrefix.Length > 3)
            invitePrefix = invitePrefix[..3];
        _logger.LogDebug("邀请码核销请求 | prefix:{Prefix} | uid:{Uid} | IP:{Ip}", invitePrefix, session.UserUid, ip);

        if (session.UserUid is null)
            return BadRequest(new InviteCodeRedeemResponse { Success = false, Error = "invalid_or_expired", ErrorCode = "invalid_session" });

        var user = await _context.Users.FindAsync(session.UserUid.Value);
        if (user is null)
        {
            _logger.LogWarning("用户不存在 | uid:{Uid}", session.UserUid);
            return BadRequest(new InviteCodeRedeemResponse { Success = false, Error = "用户不存在。", ErrorCode = "invalid_session" });
        }

        var result = await _inviteCodeService.RedeemAsync(request.InviteCode, user, ip);

        if (result.IpBanned)
        {
            return StatusCode(403, new InviteCodeRedeemResponse { Success = false, Error = "邀请码验证已被限制，请稍后重试。", ErrorCode = "banned" });
        }

        if (result.NewGroup is not null)
        {
            session.InviteCodePrefix = result.Prefix;
            session.InviteCodeType = result.NewGroup;
            session.Step = 6;
            await _sessionService.UpdateSessionAsync(request.SessionToken, session);

            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.InviteCodeRedeemed, user.Uid.ToString(), null, true,
                $"InvitePrefix: {result.Prefix}, Group: {result.NewGroup}");

            _logger.LogInformation("邀请码提权成功 | uid:{Uid} | 组:{Group}", session.UserUid, result.NewGroup);

            return Ok(new InviteCodeRedeemResponse { Success = true, NewGroup = result.NewGroup });
        }

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.InviteCodeRedeemFailed, user.Uid.ToString(), null, false,
            $"InvitePrefix: {result.Prefix}, Result: {result.Message}");

        if (result.ApiError)
            return StatusCode(502, new InviteCodeRedeemResponse { Success = false, Error = result.Message, ErrorCode = "api_error" });

        return BadRequest(new InviteCodeRedeemResponse { Success = false, Error = "邀请码无效或已过期。", ErrorCode = "invalid_or_expired" });
    }

    [HttpPost("complete")]
    public async Task<IActionResult> CompleteRegistration([FromBody] RegisterCompleteRequest request)
    {
        _logger.LogDebug("注册完成请求 | token:{Token}", LogToken(request.SessionToken));

        var (session, sessionError) = await RequireSessionAsync(request.SessionToken);
        if (session is null) return sessionError!;

        if (session.Completed)
        {
            _logger.LogWarning("注册已完成，无需重复");
            return BadRequest(new RegisterCompleteResponse { Success = false, Error = "注册已完成后，无需重复提交。", ErrorCode = "wrong_step" });
        }

        if (session.Step != 6)
        {
            _logger.LogWarning("步骤错误(complete) | 期望:6 | 实际:{Actual}", session.Step);
            return BadRequest(new RegisterCompleteResponse { Success = false, Error = "操作步骤错误，请按正确流程操作。", ErrorCode = "wrong_step" });
        }

        session.Completed = true;
        session.Step = 7;
        await _sessionService.UpdateSessionAsync(request.SessionToken, session);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.RegisterCompleted, session.UserUid.ToString(), session.PendingEmail, true,
            $"Name: {session.NormalizedName}, Group: {session.InviteCodeType ?? "normal"}");

        _logger.LogInformation("注册完成 | uid:{Uid} | 用户:{Name}", session.UserUid, session.NormalizedName);

        return Ok(new RegisterCompleteResponse { Success = true, Completed = true });
    }

    [HttpGet("status")]
    public async Task<IActionResult> GetStatus([FromQuery] string? session_token)
    {
        _logger.LogDebug("注册状态请求 | token:{Token}", LogToken(session_token));

        var session = await _sessionService.GetSessionAsync(session_token);
        if (session is null)
        {
            _logger.LogWarning("会话已过期");
            return NotFound(new RegistrationStatusResponse { Success = false, Error = "会话已过期或无效，请刷新页面重试。", ErrorCode = "invalid_session" });
        }

        return Ok(new RegistrationStatusResponse
        {
            Success = true,
            Step = session.Step,
            InviteCodeType = session.InviteCodeType,
            NormalizedName = session.NormalizedName,
            DisplayName = session.DisplayName,
            AccountCreated = session.UserUid is not null,
            PendingEmail = session.PendingEmail,
            EmailCodeAttempts = session.EmailCodeAttempts,
            EmailChangeCount = session.EmailChangeCount,
            Completed = session.Completed
        });
    }

    private static string LogToken(string? token)
        => token?[..Math.Min(16, token.Length)] ?? "null";

    private async Task<(RegistrationSession? Session, IActionResult? Error)> RequireSessionAsync(
        string? token, int? step = null, bool unauthorized = false)
    {
        var session = await _sessionService.GetSessionAsync(token);
        if (session is null)
        {
            _logger.LogWarning("会话已过期");
            var err = new { Success = false, Error = "会话已过期或无效，请刷新页面重试。", ErrorCode = "invalid_session" };
            return (null, unauthorized ? Unauthorized(err) : BadRequest(err));
        }

        if (session.UserUid is not null)
        {
            var binding = await _context.RegistrationSessionBindings.AsNoTracking()
                .FirstOrDefaultAsync(b => b.SessionTokenHash == AuthHelper.HashCode(token!));
            if (binding is null || binding.UserUid != session.UserUid.Value)
            {
                _logger.LogWarning("注册会话绑定校验失败");
                var err = new { Success = false, Error = "注册会话已失效，请重新开始。", ErrorCode = "invalid_session" };
                return (null, unauthorized ? Unauthorized(err) : BadRequest(err));
            }
        }

        if (step is not null && session.Step != step)
        {
            _logger.LogWarning("步骤错误 | 期望:{Expected} | 实际:{Actual}", step, session.Step);
            var err = new { Success = false, Error = "操作步骤错误，请按正确流程操作。", ErrorCode = "wrong_step" };
            return (null, BadRequest(err));
        }

        return (session, null);
    }

}
