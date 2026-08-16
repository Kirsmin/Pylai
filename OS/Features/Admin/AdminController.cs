using System.Net;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Features.Admin;

[ApiController]
[Route("api/admin")]
[Authorize(Policy = AuthConstants.Policies.MaxApi)]
public class AdminController : ControllerBase
{
    private readonly ApplicationDbContext _context;
    private readonly ILoginRateLimitService _loginRateLimit;
    private readonly IInviteCodeService _inviteCodeService;
    private readonly IAdminRateLimitService _adminRateLimit;
    private readonly IConfirmationRateLimitService _confirmationRateLimit;
    private readonly IEmailVerificationBlockService _emailBlock;
    private readonly IAuditService _auditService;
    private readonly IpResolutionService _ipResolver;
    private readonly ILogger<AdminController> _logger;

    public AdminController(
        ApplicationDbContext context,
        ILoginRateLimitService loginRateLimit,
        IInviteCodeService inviteCodeService,
        IAdminRateLimitService adminRateLimit,
        IConfirmationRateLimitService confirmationRateLimit,
        IEmailVerificationBlockService emailBlock,
        IAuditService auditService,
        IpResolutionService ipResolver,
        ILogger<AdminController> logger)
    {
        _context = context;
        _loginRateLimit = loginRateLimit;
        _inviteCodeService = inviteCodeService;
        _adminRateLimit = adminRateLimit;
        _confirmationRateLimit = confirmationRateLimit;
        _emailBlock = emailBlock;
        _auditService = auditService;
        _ipResolver = ipResolver;
        _logger = logger;
    }

    // ============ 邀请码管理 ============

    [HttpGet("invite-codes")]
    public async Task<IActionResult> ListInviteCodes(
        [FromQuery] string? group = null,
        [FromQuery] int skip = 0,
        [FromQuery] int take = 20)
    {
        var query = _context.InviteCodes.AsNoTracking();
        if (!string.IsNullOrEmpty(group))
            query = query.Where(c => c.Group == group);

        var total = await query.CountAsync();
        var codes = await query.OrderBy(c => c.Code)
            .Skip(Math.Max(0, skip)).Take(Math.Clamp(take, 1, 100))
            .Select(c => new AdminInviteCodeListItem
            {
                Code = c.Code,
                Group = c.Group,
                MaxRedemptions = c.MaxRedemptions,
                UsedCount = c.UsedCount
            })
            .ToListAsync();

        return Ok(new AdminInviteCodeListResponse { Success = true, Total = total, Codes = codes });
    }

    [HttpPost("invite-codes")]
    public async Task<IActionResult> CreateInviteCode([FromBody] AdminInviteCodeCreateRequest request)
    {
        if (!ModelState.IsValid)
            return BadRequest(new ApiResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });

        var code = request.Code.Trim();
        if (code.Length == 0 || code.Length > 128)
            return BadRequest(new ApiResponse { Success = false, Error = "邀请码格式无效。", ErrorCode = "invalid_format" });
        if (!AuthConstants.Groups.IsValid(request.Group))
            return BadRequest(new ApiResponse { Success = false, Error = "无效的用户组。", ErrorCode = "invalid_request" });
        if (request.MaxRedemptions is <= 0)
            return BadRequest(new ApiResponse { Success = false, Error = "最大核销次数必须大于 0。", ErrorCode = "invalid_request" });

        if (await _context.InviteCodes.AnyAsync(c => c.Code == code))
            return Conflict(new ApiResponse { Success = false, Error = "邀请码已存在。", ErrorCode = "duplicate" });

        _context.InviteCodes.Add(new InviteCode
        {
            Code = code,
            Group = request.Group,
            MaxRedemptions = request.MaxRedemptions ?? 10
        });
        await _context.SaveChangesAsync();

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.InviteCodeCreated,
            null, null, true, $"Created invite code {code} group:{request.Group}");

        return Ok(new ApiResponse { Success = true });
    }

    [HttpGet("invite-codes/{code}")]
    public async Task<IActionResult> InviteCodeDetail(string code)
    {
        var entity = await _context.InviteCodes.AsNoTracking().FirstOrDefaultAsync(c => c.Code == code);
        if (entity is null)
            return NotFound(new ApiResponse { Success = false, Error = "邀请码不存在。", ErrorCode = "not_found" });

        var usedBy = new List<AdminInviteCodeRedemption>();
        if (entity.UsedBy.Count > 0)
        {
            var uids = entity.UsedBy.Select(s => Guid.Parse(s)).ToList();
            usedBy = await _context.Users.AsNoTracking()
                .Where(u => uids.Contains(u.Uid))
                .Select(u => new AdminInviteCodeRedemption
                {
                    Uid = u.Uid,
                    Name = u.Name,
                    DisplayName = u.DisplayName
                })
                .ToListAsync();
        }

        var detail = new AdminInviteCodeDetail
        {
            Code = entity.Code,
            Group = entity.Group,
            MaxRedemptions = entity.MaxRedemptions,
            UsedCount = entity.UsedCount,
            UsedBy = usedBy
        };

        return Ok(new AdminInviteCodeDetailResponse { Success = true, Code = detail });
    }

    [HttpPatch("invite-codes/{code}")]
    public async Task<IActionResult> UpdateInviteCode(string code, [FromBody] AdminInviteCodeUpdateRequest request)
    {
        var entity = await _context.InviteCodes.FirstOrDefaultAsync(c => c.Code == code);
        if (entity is null)
            return NotFound(new ApiResponse { Success = false, Error = "邀请码不存在。", ErrorCode = "not_found" });

        if (request.Group is not null)
        {
            if (!AuthConstants.Groups.IsValid(request.Group))
                return BadRequest(new ApiResponse { Success = false, Error = "无效的用户组。", ErrorCode = "invalid_request" });
            entity.Group = request.Group;
        }

        if (request.MaxRedemptions is not null)
        {
            if (request.MaxRedemptions <= 0 || request.MaxRedemptions < entity.UsedCount)
                return BadRequest(new ApiResponse { Success = false, Error = "最大核销次数必须大于 0 且不小于已核销次数。", ErrorCode = "invalid_request" });
            entity.MaxRedemptions = request.MaxRedemptions.Value;
        }

        await _context.SaveChangesAsync();

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.InviteCodeUpdated,
            null, null, true, $"Updated invite code {code}");

        return Ok(new ApiResponse { Success = true });
    }

    [HttpDelete("invite-codes/{code}")]
    public async Task<IActionResult> DeleteInviteCode(string code)
    {
        var entity = await _context.InviteCodes.FirstOrDefaultAsync(c => c.Code == code);
        if (entity is null)
            return NotFound(new ApiResponse { Success = false, Error = "邀请码不存在。", ErrorCode = "not_found" });

        _context.InviteCodes.Remove(entity);
        await _context.SaveChangesAsync();

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.InviteCodeDeleted,
            null, null, true, $"Deleted invite code {code}");

        return Ok(new ApiResponse { Success = true });
    }

    // ============ 封禁管理 ============

    [HttpGet("bans")]
    public async Task<IActionResult> ListBans(
        [FromQuery] string? type = null,
        [FromQuery] int skip = 0,
        [FromQuery] int take = 20)
    {
        if (type is not null && !IsKnownActiveBanType(type))
            return BadRequest(new ApiResponse { Success = false, Error = "无效的封禁类型。", ErrorCode = "invalid_request" });

        var list = new List<AdminBanInfo>();
        var now = DateTimeOffset.UtcNow;

        if (type is null or "login")
            list.AddRange(await GetIpBansAsync<LoginFailure>("login", now));
        if (type is null or "invite")
            list.AddRange(await GetIpBansAsync<InviteCodeFailure>("invite", now));
        if (type is null or "email")
            list.AddRange(await GetIpBansAsync<EmailVerificationBlock>("email", now));
        if (type is null or "admin")
            list.AddRange(await GetIpBansAsync<AdminAuthFailure>("admin", now));
        if (type is null or "confirm")
        {
            var confirmBans = await _confirmationRateLimit.GetActiveBansAsync();
            list.AddRange(confirmBans.Select(b => new AdminBanInfo
            {
                BanId = b.BanId ?? "",
                Type = "confirm",
                UserUid = b.UserUid,
                UserName = b.UserName,
                FailureCount = b.FailureCount,
                BanExpires = b.BanExpiresAt.HasValue ? b.BanExpiresAt.Value.ToString("yyyy-MM-dd HH:mm:ss UTC") : null
            }));
        }

        var total = list.Count;
        return Ok(new AdminBanListResponse
        {
            Success = true,
            Total = total,
            Bans = list.Skip(Math.Max(0, skip)).Take(Math.Clamp(take, 1, 100)).ToList()
        });
    }

    [HttpGet("bans/history")]
    public async Task<IActionResult> BanHistory(
        [FromQuery] string? type = null,
        [FromQuery] int skip = 0,
        [FromQuery] int take = 20)
    {
        var query = _context.IpBanAudits.AsNoTracking();
        if (!string.IsNullOrEmpty(type))
        {
            var historyType = ResolveHistoryBanType(type);
            if (historyType is null)
                return BadRequest(new ApiResponse { Success = false, Error = "无效的封禁类型。", ErrorCode = "invalid_request" });
            query = query.Where(a => a.BanType == historyType);
        }

        var total = await query.CountAsync();
        var bans = await query.OrderByDescending(a => a.BannedAt)
            .Skip(Math.Max(0, skip)).Take(Math.Clamp(take, 1, 100))
            .Select(a => new AdminBanHistoryItem
            {
                Id = a.Id,
                BanId = a.BanId,
                Type = a.BanType,
                Ip = a.IpAddress,
                BannedAt = a.BannedAt.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                BanExpiresAt = a.BanExpiresAt.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                UnbannedAt = a.UnbannedAt.HasValue ? a.UnbannedAt.Value.ToString("yyyy-MM-dd HH:mm:ss UTC") : null
            })
            .ToListAsync();

        return Ok(new AdminBanHistoryResponse { Success = true, Total = total, Bans = bans });
    }

    [HttpDelete("bans/{banId}")]
    public async Task<IActionResult> UnbanByBanId(string banId)
    {
        var revoked = await _loginRateLimit.RevokeByBanIdAsync(banId)
            || await _inviteCodeService.RevokeByBanIdAsync(banId)
            || await _emailBlock.RevokeByBanIdAsync(banId)
            || await _adminRateLimit.RevokeByBanIdAsync(banId)
            || await _confirmationRateLimit.RevokeByBanIdAsync(banId);
        if (!revoked)
            return NotFound(new ApiResponse { Success = false, Error = "BanId 不存在。", ErrorCode = "not_found" });

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.AdminIpUnbanned,
            null, null, true, $"Admin API unban by BanId {banId}");

        return Ok(new ApiResponse { Success = true });
    }

    [HttpDelete("bans/ip/{ip}")]
    public async Task<IActionResult> UnbanByIp(string ip, [FromQuery] string? type = null)
    {
        if (!IPAddress.TryParse(ip, out _))
            return BadRequest(new ApiResponse { Success = false, Error = "IP 地址格式无效。", ErrorCode = "invalid_request" });
        if (type is "confirm")
            return BadRequest(new ApiResponse { Success = false, Error = "confirm 类型为账号级封禁，请使用 /api/admin/bans/{banId} 解封。", ErrorCode = "invalid_request" });
        if (type is not null && !IsKnownIpBanType(type))
            return BadRequest(new ApiResponse { Success = false, Error = "无效的封禁类型。", ErrorCode = "invalid_request" });

        var results = new List<object>();
        if (type is null or "login")
            results.Add(new { type = "login", status = await _loginRateLimit.RevokeByIpAsync(ip) ? "unbanned" : "not-banned" });
        if (type is null or "invite")
            results.Add(new { type = "invite", status = await _inviteCodeService.RevokeByIpAsync(ip) ? "unbanned" : "not-banned" });
        if (type is null or "email")
            results.Add(new { type = "email", status = await _emailBlock.RevokeByIpAsync(ip) ? "unbanned" : "not-banned" });
        if (type is null or "admin")
            results.Add(new { type = "admin", status = await _adminRateLimit.RevokeByIpAsync(ip) ? "unbanned" : "not-banned" });

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.AdminIpUnbanned,
            null, null, true, $"Admin API unban IP {ip}");

        return Ok(new { success = true, ip, results });
    }

    // ============ 审计日志 ============

    [HttpGet("audit-logs")]
    public async Task<IActionResult> AuditLogs(
        [FromQuery] string? eventType = null,
        [FromQuery] string? userId = null,
        [FromQuery] string? ip = null,
        [FromQuery] bool? success = null,
        [FromQuery] DateTimeOffset? from = null,
        [FromQuery] DateTimeOffset? to = null,
        [FromQuery] int skip = 0,
        [FromQuery] int take = 20)
    {
        var query = _context.AuditLogs.AsNoTracking();
        if (!string.IsNullOrEmpty(eventType))
            query = query.Where(l => l.EventType == eventType);
        if (!string.IsNullOrEmpty(userId))
            query = query.Where(l => l.UserId == userId);
        if (!string.IsNullOrEmpty(ip))
            query = query.Where(l => l.IpAddress == ip);
        if (success is not null)
            query = query.Where(l => l.Success == success);
        if (from is not null)
            query = query.Where(l => l.Timestamp >= from);
        if (to is not null)
            query = query.Where(l => l.Timestamp <= to);

        var total = await query.CountAsync();
        var logs = await query.OrderByDescending(l => l.Timestamp)
            .Skip(Math.Max(0, skip)).Take(Math.Clamp(take, 1, 100))
            .Select(l => new AdminAuditLogItem
            {
                Id = l.Id,
                EventType = l.EventType,
                UserId = l.UserId,
                UserEmail = l.UserEmail,
                Endpoint = l.Endpoint,
                Method = l.Method,
                IpAddress = l.IpAddress,
                Success = l.Success,
                Timestamp = l.Timestamp.ToString("yyyy-MM-dd HH:mm:ss UTC"),
                Details = l.Details
            })
            .ToListAsync();

        return Ok(new AdminAuditLogListResponse { Success = true, Total = total, Logs = logs });
    }

    private static bool IsKnownActiveBanType(string type)
        => type is "login" or "invite" or "email" or "admin" or "confirm";

    private static bool IsKnownIpBanType(string type)
        => type is "login" or "invite" or "email" or "admin";

    private static string? ResolveHistoryBanType(string type) => type switch
    {
        "login" => "Login",
        "invite" => "InviteCode",
        "email" => "EmailVerify",
        "admin" => "AdminAuth",
        _ => null
    };

    private async Task<List<AdminBanInfo>> GetIpBansAsync<T>(string type, DateTimeOffset now) where T : class, IIpBanEntry
    {
        return await _context.Set<T>().AsNoTracking()
            .Where(f => f.BanId != null && (f.BanExpiresAt == null || f.BanExpiresAt > now))
            .Select(f => new AdminBanInfo
            {
                BanId = f.BanId!,
                Type = type,
                Ip = f.IpAddress,
                FailureCount = f.FailureCount,
                BanExpires = f.BanExpiresAt.HasValue ? f.BanExpiresAt.Value.ToString("yyyy-MM-dd HH:mm:ss UTC") : null
            })
            .ToListAsync();
    }
}
