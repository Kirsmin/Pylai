using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Identity;

namespace Pylaios.Features.Confirmation;

public class ConfirmationResult
{
    public bool Success { get; init; }
    public string? Error { get; init; }
    public string? ErrorCode { get; init; }
    public int? AttemptsRemaining { get; init; }
    public string? BanId { get; init; }
    public string? BanRemaining { get; init; }

    public static ConfirmationResult Ok() => new() { Success = true };
    public static ConfirmationResult WrongPassword(int attemptsRemaining)
        => new() { Success = false, Error = "密码错误。", ErrorCode = "wrong_code", AttemptsRemaining = attemptsRemaining };
    public static ConfirmationResult Locked(string? banRemaining)
        => new() { Success = false, Error = "尝试次数过多，操作已被限制，请24小时后重试。", ErrorCode = "confirmation_locked", BanRemaining = banRemaining };
    public static ConfirmationResult JustLocked(string banId, string? banRemaining)
        => new() { Success = false, Error = "尝试次数过多，操作已被限制，请24小时后重试。", ErrorCode = "confirmation_locked", BanId = banId, BanRemaining = banRemaining };
}

/// <summary>
/// 特殊功能密码二次验证守卫：所有需要「登录后再次验证密码」的敏感操作共用此板块。
/// </summary>
public class ConfirmationGuard
{
    private readonly IConfirmationRateLimitService _rateLimit;
    private readonly IPasswordHasher<User> _passwordHasher;
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly IpResolutionService _ipResolver;
    private readonly IHttpContextAccessor _httpContextAccessor;
    private readonly ILogger<ConfirmationGuard> _logger;

    public ConfirmationGuard(
        IConfirmationRateLimitService rateLimit,
        IPasswordHasher<User> passwordHasher,
        ApplicationDbContext context,
        IAuditService auditService,
        IpResolutionService ipResolver,
        IHttpContextAccessor httpContextAccessor,
        ILogger<ConfirmationGuard> logger)
    {
        _rateLimit = rateLimit;
        _passwordHasher = passwordHasher;
        _context = context;
        _auditService = auditService;
        _ipResolver = ipResolver;
        _httpContextAccessor = httpContextAccessor;
        _logger = logger;
    }

    public async Task<ConfirmationResult> VerifyAsync(User user, string password, string action)
    {
        var ip = _ipResolver.GetClientIp(_httpContextAccessor.HttpContext!);

        if (await _rateLimit.IsLockedAsync(user.Uid))
        {
            var remaining = await _rateLimit.GetBanRemainingAsync(user.Uid);
            _logger.LogWarning("特殊功能操作已锁定 | uid:{Uid} | 操作:{Action} | 剩余:{Remaining}", user.Uid, action, remaining);
            await AuditAsync(user, action, false, "Operation locked");
            return ConfirmationResult.Locked(remaining);
        }

        var result = _passwordHasher.VerifyHashedPassword(user, user.PasswordHash, password);
        if (result == PasswordVerificationResult.Failed)
        {
            var (attemptsRemaining, justLocked, banId, banRemaining) = await _rateLimit.RecordFailureAsync(user.Uid);

            _logger.LogWarning("特殊功能密码验证失败 | uid:{Uid} | 操作:{Action} | 剩余:{Remaining}", user.Uid, action, attemptsRemaining);

            if (justLocked)
            {
                await AuditAsync(user, action, false, $"Confirmation locked | BanId:{banId}");
                return ConfirmationResult.JustLocked(banId!, banRemaining);
            }

            await AuditAsync(user, action, false, $"Wrong password | AttemptsRemaining:{attemptsRemaining}");
            return ConfirmationResult.WrongPassword(attemptsRemaining);
        }

        if (result == PasswordVerificationResult.SuccessRehashNeeded)
        {
            user.PasswordHash = _passwordHasher.HashPassword(user, password);
            await _context.SaveChangesAsync();
        }

        await _rateLimit.ClearFailuresAsync(user.Uid);
        await AuditAsync(user, action, true, null);
        return ConfirmationResult.Ok();
    }

    private async Task AuditAsync(User user, string action, bool success, string? details)
    {
        var httpContext = _httpContextAccessor.HttpContext;
        await _auditService.LogAsync(new AuditLog
        {
            EventType = success ? AuthConstants.EventTypes.ConfirmationSucceeded : AuthConstants.EventTypes.ConfirmationFailed,
            UserId = user.Uid.ToString(),
            UserEmail = user.Email,
            Endpoint = httpContext?.Request.Path.Value ?? "/",
            Method = httpContext?.Request.Method ?? "POST",
            IpAddress = _ipResolver.GetClientIp(httpContext!),
            UserAgent = httpContext?.Request.Headers.UserAgent.ToString(),
            Success = success,
            Details = $"{action} | {details}"
        });
    }
}
