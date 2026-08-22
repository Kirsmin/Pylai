using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Admin;

[ApiController]
[Route("api/admin/users")]
[Authorize(Policy = AuthConstants.Policies.AdminUserApi)]
public class AdminUsersController : ControllerBase
{
    private readonly ApplicationDbContext _context;
    private readonly UserManager<User> _userManager;
    private readonly IPasswordHasher<User> _passwordHasher;
    private readonly IUserTokenService _userTokenService;
    private readonly IUserAccessRevoker _userAccessRevoker;
    private readonly IMfaService _mfa;
    private readonly IRedisStateCache _stateCache;
    private readonly IAuditService _auditService;
    private readonly IpResolutionService _ipResolver;
    private readonly ILogger<AdminUsersController> _logger;

    public AdminUsersController(
        ApplicationDbContext context,
        UserManager<User> userManager,
        IPasswordHasher<User> passwordHasher,
        IUserTokenService userTokenService,
        IUserAccessRevoker userAccessRevoker,
        IMfaService mfa,
        IRedisStateCache stateCache,
        IAuditService auditService,
        IpResolutionService ipResolver,
        ILogger<AdminUsersController> logger)
    {
        _context = context;
        _userManager = userManager;
        _passwordHasher = passwordHasher;
        _userTokenService = userTokenService;
        _userAccessRevoker = userAccessRevoker;
        _mfa = mfa;
        _stateCache = stateCache;
        _auditService = auditService;
        _ipResolver = ipResolver;
        _logger = logger;
    }

    [HttpGet]
    public async Task<IActionResult> List(
        [FromQuery] string? group = null,
        [FromQuery] string? status = null,
        [FromQuery] string? search = null,
        [FromQuery] int skip = 0,
        [FromQuery] int take = 20)
    {
        var current = await this.GetCurrentUserAsync(_context);
        if (current is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var query = _context.Users.AsNoTracking();
        if (current.Group == AuthConstants.Roles.Admin)
            query = query.Where(u => u.Group == AuthConstants.Roles.Normal);

        if (!string.IsNullOrEmpty(group))
            query = query.Where(u => u.Group == group);
        if (!string.IsNullOrEmpty(status))
        {
            if (!Enum.TryParse<UserStatus>(status, true, out var parsed))
                return BadRequest(new ApiResponse { Success = false, Error = "无效的用户状态。", ErrorCode = "invalid_request" });
            query = query.Where(u => u.Status == parsed);
        }
        if (!string.IsNullOrEmpty(search))
        {
            var normalized = UsernameNormalizer.Normalize(search);
            query = query.Where(u => u.Name.Contains(normalized) || (u.DisplayName != null && u.DisplayName.Contains(search)) || (u.Email != null && u.Email.Contains(search)));
        }

        var total = await query.CountAsync();
        var users = await query.OrderByDescending(u => u.RegisterTime)
            .Skip(Math.Max(0, skip)).Take(Math.Clamp(take, 1, 100))
            .Select(u => new AdminUserListItem
            {
                Uid = u.Uid,
                Name = u.Name,
                DisplayName = u.DisplayName,
                Email = u.Email,
                Group = u.Group,
                Status = u.Status.ToString(),
                RegisterTime = u.RegisterTime.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                LastLoginAt = u.LastLoginAt.HasValue ? u.LastLoginAt.Value.ToString("yyyy-MM-dd HH:mm:ss UTC") : null
            })
            .ToListAsync();

        return Ok(new AdminUserListResponse { Success = true, Total = total, Users = users });
    }

    [HttpGet("{uid:guid}")]
    public async Task<IActionResult> Detail(Guid uid)
    {
        var (current, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (current is null || target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var logins = await _context.UserLogins
            .Where(l => l.UserUid == target.Uid)
            .Select(l => new AdminUserExternalLogin
            {
                Provider = l.LoginProvider,
                ProviderDisplayName = l.ProviderDisplayName,
                BoundAt = l.CreatedAt.ToString("yyyy-MM-dd HH:mm:ss UTC")
            })
            .ToListAsync();

        var activeSessions = await _context.UserSessions
            .CountAsync(s => s.UserUid == target.Uid && s.RevokedAt == null && s.ExpiresAt > DateTimeOffset.UtcNow);

        var tokenStatus = await _userTokenService.GetStatusAsync(target.Uid);
        AdminUserTokenInfo? tokenInfo = null;
        if (tokenStatus is not null)
        {
            var (usage, totalUsage) = await _userTokenService.GetUsageAsync(tokenStatus.Id, 0, 20);
            tokenInfo = new AdminUserTokenInfo
            {
                Exists = true,
                TokenPrefix = $"UserToken {tokenStatus.TokenPrefix}…",
                CreatedAt = tokenStatus.CreatedAt,
                RefreshedAt = tokenStatus.RefreshedAt,
                ExpiresAt = tokenStatus.ExpiresAt,
                LastUsedAt = tokenStatus.LastUsedAt,
                LastIpAddress = tokenStatus.LastIpAddress,
                TotalUsage = totalUsage,
                Usage = usage.Select(u => new AdminUserTokenUsageItem
                {
                    Id = u.Id,
                    TokenPrefix = $"UserToken {u.TokenPrefix}…",
                    OccurredAt = u.OccurredAt.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                    Method = u.Method,
                    Endpoint = u.Endpoint,
                    IpAddress = u.IpAddress,
                    UserAgent = u.UserAgent
                }).ToList()
            };
        }

        var detail = new AdminUserDetail
        {
            Uid = target.Uid,
            Name = target.Name,
            DisplayName = target.DisplayName,
            Email = target.Email,
            Group = target.Group,
            Status = target.Status.ToString(),
            RegisterTime = target.RegisterTime.ToString("yyyy-MM-dd HH:mm:ss UTC"),
            LastLoginAt = target.LastLoginAt.HasValue ? target.LastLoginAt.Value.ToString("yyyy-MM-dd HH:mm:ss UTC") : null,
            LockoutEnd = target.LockoutEnd,
            AccessFailedCount = target.AccessFailedCount,
            ActiveSessions = activeSessions,
            ExternalLogins = logins,
            Token = tokenInfo
        };

        return Ok(new AdminUserDetailResponse { Success = true, User = detail });
    }

    [HttpPatch("{uid:guid}")]
    public async Task<IActionResult> Update(Guid uid, [FromBody] AdminUserUpdateRequest request)
    {
        var (current, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (current is null || target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var isMax = current.Group == AuthConstants.Roles.Max;
        var accessChanged = false;

        if (!isMax && (request.Group is not null || request.Status is not null))
            return StatusCode(403, new ApiResponse { Success = false, Error = "Forbidden.", ErrorCode = "forbidden" });

        if (request.Group is not null)
        {
            if (!AuthConstants.Groups.IsValid(request.Group))
                return BadRequest(new ApiResponse { Success = false, Error = "无效的用户组。", ErrorCode = "invalid_request" });
            if (target.Uid == current.Uid && request.Group != AuthConstants.Roles.Max)
                return StatusCode(403, new ApiResponse { Success = false, Error = "不能取消自己的 max 组。", ErrorCode = "forbidden" });
            if (target.Group != request.Group)
            {
                var stepUp = await this.RequireMfaStepUpAsync(_mfa, _context);
                if (stepUp is not null) return stepUp;
            }
            if (target.Group != request.Group)
            {
                target.Group = request.Group;
                accessChanged = true;
            }
        }

        if (request.Status is not null)
        {
            if (!Enum.TryParse<UserStatus>(request.Status, true, out var parsed))
                return BadRequest(new ApiResponse { Success = false, Error = "无效的用户状态。", ErrorCode = "invalid_request" });
            if (target.Uid == current.Uid && parsed is UserStatus.Banned or UserStatus.Deleted)
                return StatusCode(403, new ApiResponse { Success = false, Error = "不能封禁或删除自己。", ErrorCode = "forbidden" });
            if (target.Status != parsed)
            {
                var statusStepUp = await this.RequireMfaStepUpAsync(_mfa, _context);
                if (statusStepUp is not null) return statusStepUp;
                target.Status = parsed;
                accessChanged = true;
                if (parsed == UserStatus.Active)
                {
                    target.LockoutEnd = null;
                    target.AccessFailedCount = 0;
                }
                if (parsed == UserStatus.Locked && target.LockoutEnd is null)
                    target.LockoutEnd = DateTimeOffset.UtcNow.AddMinutes(5);
            }
        }

        if (request.DisplayName is not null)
            target.DisplayName = request.DisplayName;

        if (request.Email is not null)
        {
            if (!AuthHelper.IsValidEmail(request.Email))
                return BadRequest(new ApiResponse { Success = false, Error = "邮箱地址格式不正确。", ErrorCode = "invalid_format" });
            var normalized = UsernameNormalizer.Normalize(request.Email);
            var taken = await _context.Users.AnyAsync(u => u.NormalizedEmail == normalized && u.Uid != target.Uid);
            if (taken)
                return BadRequest(new ApiResponse { Success = false, Error = "邮箱已被其他用户占用。", ErrorCode = "duplicate" });
            target.Email = request.Email;
            target.NormalizedEmail = normalized;
        }

        try
        {
            if (accessChanged)
                await _userAccessRevoker.RevokeUserAccessAsync(target.Uid);
            else
                await _context.SaveChangesAsync();
        }
        catch (DbUpdateException ex) when (ex.IsUniqueViolation())
        {
            return StatusCode(409, new ApiResponse { Success = false, Error = "用户名或邮箱已被占用。", ErrorCode = "duplicate" });
        }

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.AdminUserUpdated,
            target.Uid.ToString(), target.Email, true, $"Admin updated user {target.Name}");

        _logger.LogInformation("管理员更新用户 | uid:{Uid} | 用户:{Name}", target.Uid, target.Name);

        return Ok(new ApiResponse { Success = true });
    }

    [HttpPost("{uid:guid}/reset-password")]
    public async Task<IActionResult> ResetUserPassword(Guid uid, [FromBody] AdminResetPasswordRequest request)
    {
        var (_, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var stepUp = await this.RequireMfaStepUpAsync(_mfa, _context);
        if (stepUp is not null) return stepUp;

        if (!ModelState.IsValid)
            return BadRequest(new ApiResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });

        var pwErrors = await AuthHelper.ValidatePasswordAsync(_userManager, target, request.NewPassword);
        if (pwErrors.Count > 0)
            return BadRequest(new { success = false, error = pwErrors[0].Description, errorCode = "invalid_password" });

        target.PasswordHash = _passwordHasher.HashPassword(target, request.NewPassword);
        await _userAccessRevoker.RevokeUserAccessAsync(target.Uid);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.AdminResetPassword,
            target.Uid.ToString(), target.Email, true, $"Admin API reset password for {target.Name}");

        _logger.LogInformation("管理员重置密码 | uid:{Uid} | 用户:{Name}", target.Uid, target.Name);

        return Ok(new ApiResponse { Success = true });
    }

    [HttpPost("{uid:guid}/revoke-sessions")]
    public async Task<IActionResult> RevokeSessions(Guid uid)
    {
        var (_, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var revokedHashes = await _context.UserSessions.AsNoTracking()
            .Where(s => s.UserUid == target.Uid && s.RevokedAt == null)
            .Select(s => s.TokenHash)
            .ToListAsync();
        await _context.RevokeAllSessionsAsync(target.Uid);
        foreach (var tokenHash in revokedHashes)
            await SessionCacheInvalidator.InvalidateSessionAsync(_stateCache, tokenHash);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.SessionsRevokedAll,
            target.Uid.ToString(), target.Email, true, $"Admin API revoked all sessions for {target.Name}");

        return Ok(new ApiResponse { Success = true });
    }

    [HttpGet("{uid:guid}/sessions")]
    public async Task<IActionResult> Sessions(Guid uid)
    {
        var (_, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var now = DateTimeOffset.UtcNow;
        var sessions = await _context.UserSessions
            .Where(s => s.UserUid == uid)
            .OrderByDescending(s => s.CreatedAt)
            .Select(s => new AdminUserSessionInfo
            {
                Id = s.Id,
                CreatedAt = s.CreatedAt.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                ExpiresAt = s.ExpiresAt.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                IpAddress = s.IpAddress,
                UserAgent = s.UserAgent,
                Active = s.RevokedAt == null && s.ExpiresAt > now
            })
            .ToListAsync();

        return Ok(new AdminUserSessionsResponse { Success = true, Sessions = sessions });
    }

    [HttpDelete("{uid:guid}/sessions/{sessionId:long}")]
    public async Task<IActionResult> RevokeSession(Guid uid, long sessionId)
    {
        var (_, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var session = await _context.UserSessions.FirstOrDefaultAsync(s => s.Id == sessionId && s.UserUid == uid);
        if (session is null || session.RevokedAt is not null)
            return NotFound(new ApiResponse { Success = false, Error = "会话不存在。", ErrorCode = "not_found" });

        session.RevokedAt = DateTimeOffset.UtcNow;
        await _context.SaveChangesAsync();
        await SessionCacheInvalidator.InvalidateSessionAsync(_stateCache, session.TokenHash);

        return Ok(new ApiResponse { Success = true });
    }

    [HttpGet("{uid:guid}/token")]
    public async Task<IActionResult> Token(Guid uid, [FromQuery] int skip = 0, [FromQuery] int take = 20)
    {
        var (_, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var status = await _userTokenService.GetStatusAsync(target.Uid);
        if (status is null)
            return Ok(new { success = true, exists = false });

        var (usage, total) = await _userTokenService.GetUsageAsync(status.Id, Math.Max(0, skip), Math.Clamp(take, 1, 100));
        return Ok(new
        {
            success = true,
            exists = true,
            tokenPrefix = $"UserToken {status.TokenPrefix}…",
            createdAt = status.CreatedAt,
            refreshedAt = status.RefreshedAt,
            expiresAt = status.ExpiresAt,
            lastUsedAt = status.LastUsedAt,
            lastIpAddress = status.LastIpAddress,
            totalUsage = total,
            usage = usage.Select(u => new
            {
                id = u.Id,
                tokenPrefix = $"UserToken {u.TokenPrefix}…",
                occurredAt = u.OccurredAt.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                method = u.Method,
                endpoint = u.Endpoint,
                ipAddress = u.IpAddress,
                userAgent = u.UserAgent
            })
        });
    }

    [HttpDelete("{uid:guid}/token")]
    public async Task<IActionResult> RevokeToken(Guid uid)
    {
        var (_, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var revoked = await _userTokenService.RevokeAsync(target.Uid);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.UserTokenRevoked,
            target.Uid.ToString(), target.Email, true, $"Admin API revoked UserToken for {target.Name}");

        return Ok(new { success = true, revoked });
    }

    [HttpDelete("{uid:guid}")]
    public async Task<IActionResult> Delete(Guid uid)
    {
        var (current, target, error) = await ResolveTargetAsync(uid);
        if (error is not null) return error;
        if (current is null || target is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        if (target.Uid == current.Uid)
            return StatusCode(403, new ApiResponse { Success = false, Error = "不能删除自己。", ErrorCode = "forbidden" });

        if (target.Status == UserStatus.Deleted)
            return NotFound(new ApiResponse { Success = false, Error = "用户不存在。", ErrorCode = "not_found" });

        var stepUp = await this.RequireMfaStepUpAsync(_mfa, _context);
        if (stepUp is not null) return stepUp;

        target.Status = UserStatus.Deleted;
        await _userAccessRevoker.RevokeUserAccessAsync(target.Uid);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.AdminUserDeleted,
            target.Uid.ToString(), target.Email, true, $"Admin API deleted user {target.Name}");

        _logger.LogInformation("管理员删除用户 | uid:{Uid} | 用户:{Name}", target.Uid, target.Name);

        return Ok(new ApiResponse { Success = true });
    }

    private async Task<(User? Current, User? Target, IActionResult? Error)> ResolveTargetAsync(Guid uid)
    {
        var current = await this.GetCurrentUserAsync(_context);
        if (current is null)
            return (null, null, Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" }));

        var target = await _context.Users.FindAsync(uid);
        if (target is null)
            return (current, null, NotFound(new ApiResponse { Success = false, Error = "用户不存在。", ErrorCode = "not_found" }));

        if (current.Group == AuthConstants.Roles.Admin && target.Group != AuthConstants.Roles.Normal)
            return (current, target, StatusCode(403, new ApiResponse { Success = false, Error = "Forbidden.", ErrorCode = "forbidden" }));

        return (current, target, null);
    }
}
