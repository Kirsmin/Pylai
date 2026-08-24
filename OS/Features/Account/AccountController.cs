using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Account;

/// <summary>
/// 账户核心操作：修改登录密码、邀请码提权。
/// 邮箱绑定/更换见 AccountEmailController，授权应用见 AuthorizedAppsController，
/// 外部登录绑定见 Features/Auth/ExternalLoginController。
/// </summary>
[ApiController]
[Route("api/auth/account")]
[Authorize(AuthenticationSchemes = "Identity.Application,UserToken")]
public class AccountController : ControllerBase
{
    private readonly IPasswordHasher<User> _passwordHasher;
    private readonly UserManager<User> _userManager;
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly IInviteCodeService _inviteCodeService;
    private readonly IUserAccessRevoker _userAccessRevoker;
    private readonly IpResolutionService _ipResolver;
    private readonly ILogger<AccountController> _logger;

    public AccountController(
        IPasswordHasher<User> passwordHasher,
        UserManager<User> userManager,
        ApplicationDbContext context,
        IAuditService auditService,
        IInviteCodeService inviteCodeService,
        IUserAccessRevoker userAccessRevoker,
        IpResolutionService ipResolver,
        ILogger<AccountController> logger)
    {
        _passwordHasher = passwordHasher;
        _userManager = userManager;
        _context = context;
        _auditService = auditService;
        _inviteCodeService = inviteCodeService;
        _userAccessRevoker = userAccessRevoker;
        _ipResolver = ipResolver;
        _logger = logger;
    }

    [HttpPost("change-password")]
    public async Task<IActionResult> ChangePassword([FromBody] ChangePasswordRequest request)
    {
        _logger.LogDebug("修改密码请求");

        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

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

    [HttpPost("redeem")]
    public async Task<IActionResult> RedeemInviteCode([FromBody] AccountRedeemRequest request)
    {
        var invitePrefix = request.InviteCode?.Trim() ?? string.Empty;
        if (invitePrefix.Length > 3)
            invitePrefix = invitePrefix[..3];
        _logger.LogDebug("账号提权请求 | prefix:{Prefix}", invitePrefix);

        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

        if (string.IsNullOrWhiteSpace(request.InviteCode))
            return BadRequest(new AccountRedeemResponse { Success = false, Error = "邀请码不能为空。", ErrorCode = "invalid_format" });

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
}
