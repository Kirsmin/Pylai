using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Auth;

[ApiController]
[Route("api/auth/mfa")]
public sealed class MfaController : ControllerBase
{
    private readonly IMfaService _mfa;
    private readonly ApplicationDbContext _context;
    private readonly SignInManager<User> _signInManager;
    private readonly MainConfig _config;
    private readonly IAuditService _audit;
    private readonly IpResolutionService _ipResolver;
    private readonly IUserAccessRevoker _accessRevoker;
    private readonly IpRateLimitService _rateLimiter;

    public MfaController(
        IMfaService mfa,
        ApplicationDbContext context,
        SignInManager<User> signInManager,
        MainConfig config,
        IAuditService audit,
        IpResolutionService ipResolver,
        IUserAccessRevoker accessRevoker,
        IpRateLimitService rateLimiter)
    {
        _mfa = mfa;
        _context = context;
        _signInManager = signInManager;
        _config = config;
        _audit = audit;
        _ipResolver = ipResolver;
        _accessRevoker = accessRevoker;
        _rateLimiter = rateLimiter;
    }

    [AllowAnonymous]
    [HttpPost("verify")]
    public async Task<IActionResult> Verify([FromBody] MfaVerifyRequest request)
    {
        if (!await TryBeginMfaAttemptAsync("login"))
            return StatusCode(429, new ApiResponse { Success = false, Error = "MFA 尝试过于频繁，请稍后重试。", ErrorCode = "rate_limited" });

        var state = await _mfa.GetLoginStateAsync(request.TransactionId);
        if (state is null || !await _mfa.VerifyTotpAsync(state.UserUid, request.Code))
            return Unauthorized(new ApiResponse { Success = false, Error = "MFA 验证失败。", ErrorCode = "mfa_invalid" });

        return await CompleteLoginAsync(request.TransactionId, state);
    }

    [AllowAnonymous]
    [HttpGet("webauthn/assertion-options")]
    public async Task<IActionResult> AssertionOptions([FromQuery] string transactionId)
    {
        try
        {
            var options = await _mfa.BeginWebAuthnAssertionAsync(transactionId);
            return Ok(options);
        }
        catch
        {
            return BadRequest(new ApiResponse { Success = false, Error = "MFA 事务无效或已过期。", ErrorCode = "mfa_invalid" });
        }
    }

    [AllowAnonymous]
    [HttpPost("webauthn/verify")]
    public async Task<IActionResult> VerifyWebAuthn([FromBody] MfaWebAuthnRequest request)
    {
        if (!await _mfa.VerifyWebAuthnAssertionAsync(request.TransactionId, request.Response))
            return Unauthorized(new ApiResponse { Success = false, Error = "MFA 验证失败。", ErrorCode = "mfa_invalid" });
        var state = await _mfa.GetLoginStateAsync(request.TransactionId);
        if (state is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "MFA 事务无效或已过期。", ErrorCode = "mfa_invalid" });
        return await CompleteLoginAsync(request.TransactionId, state);
    }

    [AllowAnonymous]
    [HttpPost("totp/enroll")]
    public async Task<IActionResult> BeginTotp([FromBody] MfaEnrollmentRequest request)
    {
        var user = await ResolveUserAsync(request.TransactionId);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "MFA 事务无效或未登录。", ErrorCode = "mfa_required" });
        if (AuthConstants.Groups.Rank(user.Group) < AuthConstants.Groups.Rank(AuthConstants.Roles.Admin))
            return StatusCode(403, new ApiResponse { Success = false, Error = "只有高权限账户需要 MFA。", ErrorCode = "forbidden" });

        var enrollment = await _mfa.BeginTotpEnrollmentAsync(user.Uid, request.TransactionId);
        return Ok(new
        {
            success = true,
            enrollmentId = enrollment.EnrollmentId,
            secret = enrollment.Secret,
            otpauthUri = enrollment.Uri
        });
    }

    [AllowAnonymous]
    [HttpPost("totp/confirm")]
    public async Task<IActionResult> ConfirmTotp([FromBody] MfaEnrollmentConfirmRequest request)
    {
        var result = await _mfa.ConfirmTotpEnrollmentAsync(request.EnrollmentId, request.Code);
        if (!result.Success)
            return BadRequest(new ApiResponse { Success = false, Error = "MFA 验证失败。", ErrorCode = "mfa_invalid" });

        if (result.LoginTransactionId is not null)
        {
            var state = await _mfa.GetLoginStateAsync(result.LoginTransactionId);
            if (state is not null)
                return await CompleteLoginAsync(result.LoginTransactionId, state);
        }

        return Ok(new ApiResponse { Success = true });
    }

    [Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
    [HttpGet("status")]
    public async Task<IActionResult> Status()
    {
        var user = await ResolveUserAsync(null);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var rank = AuthConstants.Groups.Rank(user.Group);
        var required = (rank >= AuthConstants.Groups.Rank(AuthConstants.Roles.Admin) && _config.Mfa.RequireForAdmin)
            || (rank >= AuthConstants.Groups.Rank(AuthConstants.Roles.Max) && _config.Mfa.RequireWebAuthnForMax);
        var settings = await _context.UserMfaSettings.AsNoTracking().FirstOrDefaultAsync(x => x.UserUid == user.Uid);
        var webauthnCount = await _context.WebAuthnCredentials.CountAsync(x => x.UserUid == user.Uid);
        return Ok(new MfaStatusResponse
        {
            Success = true,
            Required = required,
            TotpEnabled = settings?.TotpEnabled == true && !string.IsNullOrWhiteSpace(settings.EncryptedTotpSecret),
            WebAuthnCount = webauthnCount,
            StepUpSatisfied = await _mfa.HasRecentStepUpAsync(user.Uid)
        });
    }

    [Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
    [HttpPost("step-up")]
    public async Task<IActionResult> BeginStepUp()
    {
        var user = await ResolveUserAsync(null);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var requirement = await _mfa.BeginStepUpAsync(user);
        return Ok(new
        {
            success = true,
            transactionId = requirement.TransactionId,
            methods = requirement.Methods
        });
    }

    [Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
    [HttpPost("step-up/totp")]
    public async Task<IActionResult> VerifyStepUpTotp([FromBody] MfaVerifyRequest request)
    {
        if (!await TryBeginMfaAttemptAsync("stepup"))
            return StatusCode(429, new ApiResponse { Success = false, Error = "MFA 尝试过于频繁，请稍后重试。", ErrorCode = "rate_limited" });

        if (!await _mfa.VerifyStepUpTotpAsync(request.TransactionId, request.Code))
            return Unauthorized(new ApiResponse { Success = false, Error = "MFA 验证失败。", ErrorCode = "mfa_invalid" });

        await _mfa.RemoveStepUpStateAsync(request.TransactionId);
        return Ok(new ApiResponse { Success = true });
    }

    [Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
    [HttpGet("step-up/webauthn/options")]
    public async Task<IActionResult> StepUpWebAuthnOptions([FromQuery] string transactionId)
    {
        try
        {
            var options = await _mfa.BeginStepUpWebAuthnAssertionAsync(transactionId);
            return Ok(options);
        }
        catch
        {
            return BadRequest(new ApiResponse { Success = false, Error = "MFA step-up 事务无效或已过期。", ErrorCode = "mfa_invalid" });
        }
    }

    [Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
    [HttpPost("step-up/webauthn/verify")]
    public async Task<IActionResult> VerifyStepUpWebAuthn([FromBody] MfaWebAuthnRequest request)
    {
        if (!await _mfa.VerifyStepUpWebAuthnAssertionAsync(request.TransactionId, request.Response))
            return Unauthorized(new ApiResponse { Success = false, Error = "MFA 验证失败。", ErrorCode = "mfa_invalid" });

        return Ok(new ApiResponse { Success = true });
    }

    [AllowAnonymous]
    [HttpPost("webauthn/registration-options")]
    public async Task<IActionResult> RegistrationOptions([FromBody] MfaEnrollmentRequest request)
    {
        var user = await ResolveUserAsync(request.TransactionId);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "MFA 事务无效或未登录。", ErrorCode = "mfa_required" });
        if (AuthConstants.Groups.Rank(user.Group) < AuthConstants.Groups.Rank(AuthConstants.Roles.Admin))
            return StatusCode(403, new ApiResponse { Success = false, Error = "只有高权限账户需要 MFA。", ErrorCode = "forbidden" });

        var result = await _mfa.BeginWebAuthnRegistrationAsync(user.Uid, request.TransactionId);
        return Ok(new { success = true, registrationId = result.RegistrationId, options = result.Options });
    }

    [AllowAnonymous]
    [HttpPost("webauthn/registration")]
    public async Task<IActionResult> CompleteRegistration([FromBody] MfaWebAuthnRegistrationRequest request)
    {
        var user = await ResolveUserAsync(request.TransactionId);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "MFA 事务无效或未登录。", ErrorCode = "mfa_required" });

        try
        {
            var success = await _mfa.CompleteWebAuthnRegistrationAsync(user.Uid, request.RegistrationId, request.Response);
            if (!success)
                return BadRequest(new ApiResponse { Success = false, Error = "MFA 注册失败。", ErrorCode = "mfa_invalid" });
            return Ok(new ApiResponse { Success = true });
        }
        catch
        {
            return BadRequest(new ApiResponse { Success = false, Error = "MFA 注册失败。", ErrorCode = "mfa_invalid" });
        }
    }

    private async Task<bool> TryBeginMfaAttemptAsync(string kind)
    {
        var ip = this.GetClientIp(_ipResolver);
        if (await _rateLimiter.IsRateLimited(ip, $"mfa-{kind}", 20, TimeSpan.FromMinutes(10)))
            return false;
        await _rateLimiter.RecordAttempt(ip, $"mfa-{kind}", TimeSpan.FromMinutes(10));
        return true;
    }

    private async Task<User?> ResolveUserAsync(string? transactionId)
    {
        if (!string.IsNullOrWhiteSpace(transactionId))
        {
            var state = await _mfa.GetLoginStateAsync(transactionId);
            if (state is null) return null;
            return await _context.Users.FirstOrDefaultAsync(x => x.Uid == state.UserUid);
        }

        var uid = User.FindFirstValue(ClaimTypes.NameIdentifier) ?? User.FindFirstValue("sub");
        return Guid.TryParse(uid, out var parsed)
            ? await _context.Users.FirstOrDefaultAsync(x => x.Uid == parsed)
            : null;
    }

    private async Task<IActionResult> CompleteLoginAsync(string transactionId, MfaLoginState state)
    {
        var user = await _context.Users.FirstOrDefaultAsync(x => x.Uid == state.UserUid);
        if (user is null || user.Status != UserStatus.Active)
            return Unauthorized(new ApiResponse { Success = false, Error = "登录失败。", ErrorCode = "invalid_credentials" });

        user.LastLoginAt = DateTimeOffset.UtcNow;
        user.AccessFailedCount = 0;
        user.LockoutEnd = null;
        await _context.SaveChangesAsync();
        await _accessRevoker.RevokeUserAccessAsync(user.Uid);
        await _signInManager.SignInAsync(user, state.RememberMe);
        await this.CreateUserSessionAsync(_context, user, state.IpAddress, _config.Cookie.SessionName);
        await _mfa.RemoveLoginStateAsync(transactionId);
        await this.AuditAsync(_audit, _ipResolver, AuthConstants.EventTypes.Login, user.Uid.ToString(), user.Email, true, "MFA login");

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
