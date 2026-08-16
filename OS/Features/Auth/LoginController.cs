using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Auth;

[ApiController]
[Route("api/auth")]
public class LoginController : ControllerBase
{
    private readonly IPasswordHasher<User> _passwordHasher;
    private readonly SignInManager<User> _signInManager;
    private readonly UserManager<User> _userManager;
    private readonly ILoginRateLimitService _loginRateLimitService;
    private readonly IpResolutionService _ipResolver;
    private readonly MainConfig _config;
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly ILogger<LoginController> _logger;

    public LoginController(
        IPasswordHasher<User> passwordHasher,
        SignInManager<User> signInManager,
        UserManager<User> userManager,
        ILoginRateLimitService loginRateLimitService,
        IpResolutionService ipResolver,
        MainConfig config,
        ApplicationDbContext context,
        IAuditService auditService,
        ILogger<LoginController> logger)
    {
        _passwordHasher = passwordHasher;
        _signInManager = signInManager;
        _userManager = userManager;
        _loginRateLimitService = loginRateLimitService;
        _ipResolver = ipResolver;
        _config = config;
        _context = context;
        _auditService = auditService;
        _logger = logger;
    }

    [AllowAnonymous]
    [HttpGet("password-policy")]
    public IActionResult GetPasswordPolicy()
    {
        _logger.LogDebug("密码策略请求");

        var pwd = _config.Identity.Password;
        return Ok(new PasswordPolicyResponse
        {
            Success = true,
            MinLength = pwd.RequiredLength,
            RequireDigit = pwd.RequireDigit,
            RequireLowercase = pwd.RequireLowercase,
            RequireUppercase = pwd.RequireUppercase,
            RequireNonAlphanumeric = pwd.RequireNonAlphanumeric
        });
    }

    [AllowAnonymous]
    [HttpPost("login")]
    public async Task<IActionResult> Login([FromBody] LoginRequest request)
    {
        _logger.LogDebug("登录请求");

        if (!ModelState.IsValid)
        {
            _logger.LogWarning("请求参数无效");
            return BadRequest(new LoginResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });
        }

        var ip = this.GetClientIp(_ipResolver);

        var (ipBanned, banId) = await _loginRateLimitService.IsIpBannedAsync(ip);
        if (ipBanned)
        {
            var banRemaining = await _loginRateLimitService.GetBanRemainingAsync(ip);
            _logger.LogWarning("登录IP被封禁 | IP:{Ip} | 剩余:{Remaining}", ip, banRemaining);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.LoginIpBanned, null, request.UsernameOrEmail, false, $"IP banned for login: {banRemaining}");
            return Unauthorized(new LoginResponse { Success = false, Error = "用户名或密码错误。", ErrorCode = "ip_banned", BanId = banId });
        }

        _logger.LogDebug("登录尝试 | 用户:{UsernameOrEmail} | IP:{Ip}", request.UsernameOrEmail, ip);

        var user = await this.FindUserAsync(_context, request.UsernameOrEmail);
        if (user is null)
        {
            _logger.LogWarning("用户不存在 | {UsernameOrEmail} | IP:{Ip}", request.UsernameOrEmail, ip);
            var fr1 = await _loginRateLimitService.RecordFailureAsync(ip);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.LoginFailure, null, request.UsernameOrEmail, false, "User not found");
            return Unauthorized(new LoginResponse { Success = false, Error = "用户名或密码错误。", ErrorCode = "invalid_credentials", BanId = fr1.BanId });
        }

        _logger.LogDebug("用户匹配 | uid:{Uid} | 用户:{Name} | 状态:{Status}", user.Uid, user.Name, user.Status);

        if (user.Status == UserStatus.Banned || user.Status == UserStatus.Deleted)
        {
            _logger.LogWarning("账户状态异常 | uid:{Uid} | 状态:{Status}", user.Uid, user.Status);
            var fr2 = await _loginRateLimitService.RecordFailureAsync(ip);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.LoginFailure, user.Uid.ToString(), user.Email, false, $"Account {user.Status}");
            return Unauthorized(new LoginResponse { Success = false, Error = "用户名或密码错误。", ErrorCode = "invalid_credentials", BanId = fr2.BanId });
        }

        if (user.Status == UserStatus.Locked)
        {
            var remaining = user.LockoutEnd is { } end && end > DateTimeOffset.UtcNow
                ? end - DateTimeOffset.UtcNow
                : TimeSpan.FromMinutes(_config.Identity.Lockout.DefaultTimeoutMinutes);
            _logger.LogWarning("账户被管理员锁定 | uid:{Uid} | 剩余:{Remaining}", user.Uid, remaining);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.LoginLockedOut, user.Uid.ToString(), user.Email, false, "Account locked by admin");
            return Unauthorized(new LoginResponse
            {
                Success = false,
                Error = "账号已被锁定。",
                ErrorCode = "locked_out",
                LockedOut = true,
                LockoutRemaining = remaining.ToString(@"hh\h\ mm\m\ ss\s")
            });
        }


        if (user.LockoutEnd is not null && user.LockoutEnd <= DateTimeOffset.UtcNow)
        {
            user.LockoutEnd = null;
            user.AccessFailedCount = 0;
        }

        if (user.LockoutEnd is not null && user.LockoutEnd > DateTimeOffset.UtcNow)
        {
            var remaining = user.LockoutEnd.Value - DateTimeOffset.UtcNow;
            _logger.LogWarning("账户锁定中 | uid:{Uid} | 剩余:{Remaining}", user.Uid, remaining);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.LoginLockedOut, user.Uid.ToString(), user.Email, false, "Account locked");
            return Unauthorized(new LoginResponse
            {
                Success = false,
                Error = "账号已被锁定。",
                ErrorCode = "locked_out",
                LockedOut = true,
                LockoutRemaining = remaining.ToString(@"hh\h\ mm\m\ ss\s")
            });
        }

        var passwordResult = _passwordHasher.VerifyHashedPassword(user, user.PasswordHash, request.Password);
        if (passwordResult == PasswordVerificationResult.Failed)
        {
            _logger.LogDebug("密码验证失败 | uid:{Uid} | 尝试:{Attempts}", user.Uid, user.AccessFailedCount + 1);

            user.AccessFailedCount++;
            var lockedNow = user.AccessFailedCount >= _config.Identity.Lockout.MaxFailedAttempts;
            if (lockedNow)
            {
                user.LockoutEnd = DateTimeOffset.UtcNow.AddMinutes(_config.Identity.Lockout.DefaultTimeoutMinutes);
                await _context.SaveChangesAsync();
                var fr3 = await _loginRateLimitService.RecordFailureAsync(ip);
                _logger.LogWarning("账户已锁定 | uid:{Uid} | 解锁:{LockoutEnd}", user.Uid, user.LockoutEnd);
                await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.LoginLockedOut, user.Uid.ToString(), user.Email, false, "Account locked");
                var remainingNow = user.LockoutEnd.Value - DateTimeOffset.UtcNow;
                return Unauthorized(new LoginResponse { Success = false, Error = "用户名或密码错误。", ErrorCode = "locked_out", LockedOut = true, BanId = fr3.BanId, LockoutRemaining = remainingNow.ToString(@"hh\h\ mm\m\ ss\s") });
            }

            await _context.SaveChangesAsync();
            var fr4 = await _loginRateLimitService.RecordFailureAsync(ip);
            _logger.LogDebug("密码错误 | 尝试:{Attempts}/{MaxAttempts}", user.AccessFailedCount, _config.Identity.Lockout.MaxFailedAttempts);
            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.LoginFailure, user.Uid.ToString(), user.Email, false, "Invalid password");
            return Unauthorized(new LoginResponse { Success = false, Error = "用户名或密码错误。", ErrorCode = "invalid_credentials", BanId = fr4.BanId });
        }

        if (passwordResult == PasswordVerificationResult.SuccessRehashNeeded)
        {
            user.PasswordHash = _passwordHasher.HashPassword(user, request.Password);
            _logger.LogDebug("密码重哈希完成 | uid:{Uid}", user.Uid);
        }

        user.AccessFailedCount = 0;
        user.LockoutEnd = null;
        user.LastLoginAt = DateTimeOffset.UtcNow;

        await _context.SaveChangesAsync();


        await _loginRateLimitService.ClearFailuresAsync(ip);

        await _signInManager.SignInAsync(user, isPersistent: request.RememberMe);
        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.Login, user.Uid.ToString(), user.Email, true);

        await this.CreateUserSessionAsync(_context, user, ip, _config.Cookie.SessionName);

        _logger.LogInformation("用户登录成功 | uid:{Uid} | 用户:{Name}", user.Uid, user.Name);

        return Ok(new LoginResponse
        {
            Success = true,
            Uid = user.Uid,
            Name = user.Name,
            DisplayName = user.DisplayName,
            Group = user.Group,
            Email = user.Email
        });
    }

}
