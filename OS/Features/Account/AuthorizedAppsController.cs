using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using OpenIddict.Abstractions;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Pylaios.Features.Account;

/// <summary>
/// 已授权 OAuth 应用（应用级：同客户端仅一条活跃永久授权；撤销 = 删除授权 + 吊销其全部 Token）。
/// </summary>
[ApiController]
[Route("api/auth/account")]
[Authorize(AuthenticationSchemes = "Identity.Application,UserToken")]
public class AuthorizedAppsController : ControllerBase
{
    private readonly ApplicationDbContext _context;
    private readonly IAuditService _auditService;
    private readonly IpResolutionService _ipResolver;
    private readonly IOpenIddictAuthorizationManager _authorizationManager;
    private readonly IOpenIddictApplicationManager _applicationManager;
    private readonly IOpenIddictScopeManager _scopeManager;
    private readonly IOpenIddictTokenManager _tokenManager;
    private readonly ILogger<AuthorizedAppsController> _logger;

    public AuthorizedAppsController(
        ApplicationDbContext context,
        IAuditService auditService,
        IpResolutionService ipResolver,
        IOpenIddictAuthorizationManager authorizationManager,
        IOpenIddictApplicationManager applicationManager,
        IOpenIddictScopeManager scopeManager,
        IOpenIddictTokenManager tokenManager,
        ILogger<AuthorizedAppsController> logger)
    {
        _context = context;
        _auditService = auditService;
        _ipResolver = ipResolver;
        _authorizationManager = authorizationManager;
        _applicationManager = applicationManager;
        _scopeManager = scopeManager;
        _tokenManager = tokenManager;
        _logger = logger;
    }

    [HttpGet("authorized-apps")]
    public async Task<IActionResult> GetAuthorizedApps()
    {
        _logger.LogDebug("列出已授权应用");

        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

        var subject = user.Uid.ToString();
        var items = new List<(DateTimeOffset CreatedAt, AuthorizedAppItem Item)>();

        await foreach (var authorization in _authorizationManager.FindBySubjectAsync(subject))
        {
            var status = await _authorizationManager.GetStatusAsync(authorization);
            var type = await _authorizationManager.GetTypeAsync(authorization);
            if (status != Statuses.Valid || type != AuthorizationTypes.Permanent)
                continue;

            var appId = await _authorizationManager.GetApplicationIdAsync(authorization);
            if (string.IsNullOrEmpty(appId))
                continue;

            var application = await _applicationManager.FindByIdAsync(appId);
            if (application is null)
                continue;

            var clientId = await _applicationManager.GetClientIdAsync(application);
            var displayName = await _applicationManager.GetDisplayNameAsync(application) ?? clientId;
            var metadata = await _context.OAuthClientMetadata.FindAsync(appId);
            var createdAt = await _authorizationManager.GetCreationDateAsync(authorization);
            var scopes = await _authorizationManager.GetScopesAsync(authorization);
            var scopeList = new List<ScopeInfo>();

            foreach (var scope in scopes.Where(s => s is not (AuthConstants.Scopes.OpenId or AuthConstants.Scopes.OfflineAccess)))
            {
                var scopeObj = await _scopeManager.FindByNameAsync(scope);
                scopeList.Add(new ScopeInfo
                {
                    Name = scope,
                    DisplayName = scopeObj is null ? scope : await _scopeManager.GetDisplayNameAsync(scopeObj) ?? scope,
                    Description = scopeObj is null ? string.Empty : await _scopeManager.GetDescriptionAsync(scopeObj) ?? string.Empty
                });
            }

            items.Add((createdAt ?? DateTimeOffset.UtcNow, new AuthorizedAppItem
            {
                Id = await _authorizationManager.GetIdAsync(authorization) ?? appId,
                ClientId = clientId ?? string.Empty,
                DisplayName = displayName ?? string.Empty,
                Description = metadata?.Description,
                LogoUrl = $"{Request.Scheme}://{Request.Host}/api/clients/{Uri.EscapeDataString(appId)}/logo",
                IsFajorCertified = metadata?.IsFajorCertified ?? false,
                HomepageUrl = metadata?.HomepageUrl,
                AuthorizedAt = (createdAt ?? DateTimeOffset.UtcNow).ToOffset(TimeSpan.FromHours(8)).ToString("yyyy/MM/dd H:mm:ss"),
                Scopes = scopeList
            }));
        }

        var apps = items.OrderByDescending(t => t.CreatedAt).Select(t => t.Item).ToList();

        _logger.LogInformation("已授权应用列表 | uid:{Uid} | 数量:{Count}", user.Uid, apps.Count);

        return Ok(new AuthorizedAppListResponse { Success = true, Apps = apps });
    }

    [HttpDelete("authorized-apps/{id}")]
    public async Task<IActionResult> RevokeAuthorizedApp(string id)
    {
        _logger.LogDebug("撤销授权应用 | id:{Id}", id);

        var (user, userError) = await this.RequireUserAsync(_context);
        if (user is null) return userError!;

        var authorization = await _authorizationManager.FindByIdAsync(id);
        if (authorization is null)
        {
            _logger.LogWarning("授权不存在 | id:{Id}", id);
            return NotFound(new AuthorizedAppRevokeResponse { Success = false, Error = "授权不存在。", ErrorCode = "not_found" });
        }

        var subject = await _authorizationManager.GetSubjectAsync(authorization);
        if (subject != user.Uid.ToString())
        {
            _logger.LogWarning("用户与授权不匹配 | uid:{Uid} | id:{Id}", user.Uid, id);
            return Forbid();
        }

        var authorizationId = id;
        await _tokenManager.RevokeByAuthorizationIdAsync(authorizationId);

        var appId = await _authorizationManager.GetApplicationIdAsync(authorization);
        if (!string.IsNullOrEmpty(appId))
        {
            _context.ConsentAuditEvents.Add(new ConsentAuditEvent
            {
                Subject = subject,
                ClientId = appId,
                Action = ConsentAuditActions.ApplicationRevoked,
                AuthorizationId = authorizationId
            });
            await _context.SaveChangesAsync();
        }

        await _authorizationManager.DeleteAsync(authorization);

        _logger.LogInformation("撤销授权成功 | uid:{Uid} | id:{Id}", user.Uid, id);

        await this.AuditAsync(_auditService, _ipResolver, AuthConstants.EventTypes.AuthorizationRevoked, user.Uid.ToString(), user.Email, true,
            $"Authorization: {id}");

        return Ok(new AuthorizedAppRevokeResponse { Success = true });
    }
}
