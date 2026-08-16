using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using OpenIddict.Abstractions;

namespace Pylaios.Features.OAuth;

[ApiController]
[Route("api/auth")]
public class AuthorizeApiController : ControllerBase
{

    private readonly IRedisStateCache _stateCache;
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly IpResolutionService _ipResolver;
    private readonly IOpenIddictAuthorizationManager _authorizationManager;
    private readonly ILogger<AuthorizeApiController> _logger;

    public AuthorizeApiController(
        IRedisStateCache stateCache,
        ApplicationDbContext context,
        IAuditService auditService,
        IpResolutionService ipResolver,
        IOpenIddictAuthorizationManager authorizationManager,
        ILogger<AuthorizeApiController> logger)
    {
        _stateCache = stateCache;
        _context = context;
        _auditService = auditService;
        _ipResolver = ipResolver;
        _authorizationManager = authorizationManager;
        _logger = logger;
    }

    [AllowAnonymous]
    [HttpGet("authorize-request")]
    public async Task<IActionResult> GetAuthorizeRequest([FromQuery] string requestId)
    {
        if (string.IsNullOrEmpty(requestId))
            return BadRequest(new AuthorizeRequestInfoResponse { Success = false, Error = "缺少 requestId。", ErrorCode = "invalid_request" });

        var pending = await _stateCache.GetAsync<PendingAuthorizeRequest>(ConsentState.Key(requestId));
        if (pending is null)
            return NotFound(new AuthorizeRequestInfoResponse { Success = false, Error = "请求已过期或无效。", ErrorCode = "expired" });

        var user = await this.GetCurrentUserAsync(_context);

        AuthorizeUserInfo? userInfo = null;
        List<string> existingScopes = [];
        if (user is not null && user.Uid.ToString() == pending.UserId)
        {
            userInfo = new AuthorizeUserInfo
            {
                Uid = user.Uid,
                Name = user.Name,
                DisplayName = user.DisplayName,
                Email = user.Email,
                Group = user.Group
            };

            var existing = await AuthorizationConsolidator.FindActiveAsync(_authorizationManager, pending.UserId, pending.ApplicationId);
            foreach (var auth in existing)
                existingScopes.AddRange(await _authorizationManager.GetScopesAsync(auth));
            existingScopes = existingScopes
                .Where(s => s is not (AuthConstants.Scopes.OpenId or AuthConstants.Scopes.OfflineAccess))
                .Distinct(StringComparer.Ordinal)
                .ToList();
        }

        return Ok(new AuthorizeRequestInfoResponse
        {
            Success = true,
            DisplayName = pending.ApplicationName,
            Description = pending.Description,
            HomepageUrl = pending.HomepageUrl,
            IsFajorCertified = pending.IsFajorCertified,
            LogoUrl = $"{Request.Scheme}://{Request.Host}/api/clients/{pending.ApplicationId}/logo",
            Scopes = pending.Scopes
                .Where(s => s.Name is not (AuthConstants.Scopes.OpenId or AuthConstants.Scopes.OfflineAccess))
                .Select(s => new ScopeInfo
                {
                    Name = s.Name,
                    DisplayName = s.DisplayName,
                    Description = s.Description
                }).ToList(),
            ExistingScopes = existingScopes,
            User = userInfo
        });
    }

    [Authorize]
    [HttpPost("authorize-request/consent")]
    public async Task<IActionResult> Consent([FromBody] AuthorizeConsentRequest body)
    {
        if (string.IsNullOrEmpty(body.RequestId))
            return BadRequest(new AuthorizeConsentResponse { Success = false, Error = "缺少 requestId。", ErrorCode = "invalid_request" });

        var pending = await _stateCache.GetAsync<PendingAuthorizeRequest>(ConsentState.Key(body.RequestId));
        if (pending is null)
            return NotFound(new AuthorizeConsentResponse { Success = false, Error = "请求已过期或无效。", ErrorCode = "expired" });

        var user = await this.GetCurrentUserAsync(_context);
        if (user is null || user.Uid.ToString() != pending.UserId)
        {
            _logger.LogWarning("Consent 用户不匹配 | requestId:{Id} | 期望用户:{Expected}", body.RequestId, pending.UserId);
            return Forbid();
        }

        if (!body.Approved)
        {
            await _stateCache.RemoveAsync(ConsentState.Key(body.RequestId));
            var denyUrl = $"{pending.RedirectUri}?error=access_denied";
            if (!string.IsNullOrEmpty(pending.State))
                denyUrl += $"&state={Uri.EscapeDataString(pending.State!)}";

            _logger.LogInformation("Consent 已拒绝 | requestId:{Id} | 用户:{UserId}", body.RequestId, user.Uid);

            var requestedNames = (pending.Scope ?? string.Empty)
                .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .ToList();
            _context.ConsentAuditEvents.Add(new ConsentAuditEvent
            {
                Subject = pending.UserId,
                ClientId = pending.ApplicationId,
                Action = ConsentAuditActions.ConsentDenied,
                RequestedScopes = AuthorizationConsolidator.ToJson(requestedNames),
                UserAgent = HttpContext.Request.Headers.UserAgent.ToString()
            });
            await _context.SaveChangesAsync();

            await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ConsentDenied, user.Uid.ToString(), user.Email, true, $"Client: {pending.ClientId}");

            return Ok(new AuthorizeConsentResponse { Success = true, RedirectUrl = denyUrl });
        }

        pending.Approved = true;
        await _stateCache.SetAsync(ConsentState.Key(body.RequestId), pending, ConsentState.PendingTtl);

        var queryParams = new Dictionary<string, string?>
        {
            ["client_id"] = pending.ClientId,
            ["redirect_uri"] = pending.RedirectUri,
            ["scope"] = pending.Scope,
            ["state"] = pending.State,
            ["response_type"] = pending.ResponseType,
            ["code_challenge"] = pending.CodeChallenge,
            ["code_challenge_method"] = pending.CodeChallengeMethod,
            ["nonce"] = pending.Nonce,
            ["consent_approved"] = body.RequestId
        };

        var query = string.Join("&",
            queryParams.Where(kv => !string.IsNullOrEmpty(kv.Value))
                       .Select(kv => $"{Uri.EscapeDataString(kv.Key)}={Uri.EscapeDataString(kv.Value!)}"));

        var serverBase = $"{Request.Scheme}://{Request.Host}{Request.PathBase}";
        var authorizeUrl = $"{serverBase}/connect/authorize?{query}";

        _logger.LogInformation("Consent 已批准 | requestId:{Id} | 用户:{UserId}", body.RequestId, user.Uid);
        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.ConsentApproved, user.Uid.ToString(), user.Email, true, $"Client: {pending.ClientId}");

        return Ok(new AuthorizeConsentResponse { Success = true, RedirectUrl = authorizeUrl });
    }

}
