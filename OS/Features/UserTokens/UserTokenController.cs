using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.UserTokens;

[ApiController]
[Route("api/user-token")]
[Authorize(AuthenticationSchemes = "Identity.Application,OpenIddict.Validation.AspNetCore")]
public class UserTokenController : ControllerBase
{
    private readonly ApplicationDbContext _context;
    private readonly IUserTokenService _tokenService;
    private readonly ConfirmationGuard _confirmationGuard;
    private readonly IAuditService _auditService;
    private readonly IpResolutionService _ipResolver;
    private readonly ILogger<UserTokenController> _logger;

    public UserTokenController(
        ApplicationDbContext context,
        IUserTokenService tokenService,
        ConfirmationGuard confirmationGuard,
        IAuditService auditService,
        IpResolutionService ipResolver,
        ILogger<UserTokenController> logger)
    {
        _context = context;
        _tokenService = tokenService;
        _confirmationGuard = confirmationGuard;
        _auditService = auditService;
        _ipResolver = ipResolver;
        _logger = logger;
    }

    [HttpPost]
    public async Task<IActionResult> CreateOrRefresh([FromBody] UserTokenCreateRequest request)
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        if (!ModelState.IsValid)
            return BadRequest(new ApiResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });
        if (request.LifetimeDays < 0)
            return BadRequest(new ApiResponse { Success = false, Error = "有效期不能为负数。", ErrorCode = "invalid_request" });

        var guard = await _confirmationGuard.VerifyAsync(user, request.Password, "UserToken 创建/刷新");
        if (!guard.Success)
            return ConfirmationError(guard);

        var (token, plainToken, refreshed) = await _tokenService.CreateOrRefreshAsync(user, request.LifetimeDays);

        await this.AuditAsync(_auditService, _ipResolver,
            refreshed ? AuthConstants.EventTypes.UserTokenRefreshed : AuthConstants.EventTypes.UserTokenCreated,
            user.Uid.ToString(), user.Email, true,
            $"{(refreshed ? "Refreshed" : "Created")} UserToken Id:{token.Id}");

        _logger.LogInformation("UserToken创建/刷新 | uid:{Uid} | TokenId:{Id} | Refreshed:{Refreshed}", user.Uid, token.Id, refreshed);

        return Ok(new UserTokenCreateResponse
        {
            Success = true,
            Token = plainToken,
            TokenPrefix = $"UserToken {token.TokenPrefix}…",
            Refreshed = refreshed,
            CreatedAt = token.CreatedAt,
            ExpiresAt = token.ExpiresAt
        });
    }

    [HttpPost("query")]
    public async Task<IActionResult> Query([FromBody] UserTokenQueryRequest request)
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        if (!ModelState.IsValid)
            return BadRequest(new ApiResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });

        var guard = await _confirmationGuard.VerifyAsync(user, request.Password, "UserToken 查询");
        if (!guard.Success)
            return ConfirmationError(guard);

        var status = await _tokenService.GetStatusAsync(user.Uid);
        if (status is null)
        {
            return Ok(new UserTokenQueryResponse
            {
                Success = true,
                Token = new UserTokenStatusDto { Exists = false }
            });
        }

        var skip = Math.Max(0, request.Skip);
        var take = Math.Clamp(request.Take, 1, 100);
        var (usage, total) = await _tokenService.GetUsageAsync(status.Id, skip, take);

        var dto = new UserTokenStatusDto
        {
            Exists = true,
            TokenPrefix = $"UserToken {status.TokenPrefix}…",
            CreatedAt = status.CreatedAt,
            RefreshedAt = status.RefreshedAt,
            ExpiresAt = status.ExpiresAt,
            LastUsedAt = status.LastUsedAt,
            LastIpAddress = status.LastIpAddress,
            TotalUsage = total,
            Usage = usage.Select(u => new UserTokenUsageDto
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

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.UserTokenQueried,
            user.Uid.ToString(), user.Email, true, $"Queried UserToken Id:{status.Id}");

        return Ok(new UserTokenQueryResponse { Success = true, Token = dto });
    }

    [HttpDelete]
    public async Task<IActionResult> Revoke([FromBody] UserTokenRevokeRequest request)
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        if (!ModelState.IsValid)
            return BadRequest(new ApiResponse { Success = false, Error = "请求参数无效。", ErrorCode = "invalid_format" });

        var guard = await _confirmationGuard.VerifyAsync(user, request.Password, "UserToken 吊销");
        if (!guard.Success)
            return ConfirmationError(guard);

        var revoked = await _tokenService.RevokeAsync(user.Uid);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.UserTokenRevoked,
            user.Uid.ToString(), user.Email, true, $"Revoked UserToken for {user.Name}");

        _logger.LogInformation("UserToken吊销 | uid:{Uid} | Revoked:{Revoked}", user.Uid, revoked);

        return Ok(new UserTokenRevokeResponse { Success = true, Revoked = revoked });
    }

    private IActionResult ConfirmationError(ConfirmationResult guard)
    {
        var payload = new
        {
            success = false,
            error = guard.Error,
            errorCode = guard.ErrorCode,
            banId = guard.BanId,
            banRemaining = guard.BanRemaining
        };

        return guard.ErrorCode switch
        {
            "confirmation_locked" => StatusCode(403, payload),
            _ => BadRequest(payload)
        };
    }
}
