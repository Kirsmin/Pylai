using System.Collections.Immutable;
using System.Security.Claims;
using Microsoft.AspNetCore;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;
using OpenIddict.Server.AspNetCore;
using static OpenIddict.Abstractions.OpenIddictConstants;

namespace Pylaios.Features.OAuth;

public class AuthorizationController : Controller
{

    private readonly IOpenIddictApplicationManager _applicationManager;
    private readonly IOpenIddictAuthorizationManager _authorizationManager;
    private readonly IOpenIddictScopeManager _scopeManager;
    private readonly IOpenIddictTokenManager _tokenManager;
    private readonly SignInManager<User> _signInManager;
    private readonly UserManager<User> _userManager;
    private readonly ApplicationDbContext _context;
    private readonly IRedisStateCache _stateCache;
    private readonly ILogger<AuthorizationController> _logger;
    private readonly string _frontendBase;

    public AuthorizationController(
        IOpenIddictApplicationManager applicationManager,
        IOpenIddictAuthorizationManager authorizationManager,
        IOpenIddictScopeManager scopeManager,
        IOpenIddictTokenManager tokenManager,
        SignInManager<User> signInManager,
        UserManager<User> userManager,
        ApplicationDbContext context,
        IRedisStateCache stateCache,
        ILogger<AuthorizationController> logger,
        MainConfig config)
    {
        _applicationManager = applicationManager;
        _authorizationManager = authorizationManager;
        _scopeManager = scopeManager;
        _tokenManager = tokenManager;
        _signInManager = signInManager;
        _userManager = userManager;
        _context = context;
        _stateCache = stateCache;
        _logger = logger;
        _frontendBase = config.Frontend.Url.TrimEnd('/');
    }

    [HttpGet("~/connect/authorize")]
    [IgnoreAntiforgeryToken]
    public async Task<IActionResult> AuthorizeGet()
    {
        return await AuthorizeInternal();
    }

    [HttpPost("~/connect/authorize")]
    [IgnoreAntiforgeryToken]
    public async Task<IActionResult> AuthorizePost()
    {
        return await AuthorizeInternal();
    }

    private async Task<IActionResult> AuthorizeInternal()
    {
        var request = HttpContext.GetOpenIddictServerRequest()
            ?? throw new InvalidOperationException("The OpenID Connect request cannot be retrieved.");

        var consentApproved = (string?)request["consent_approved"];
        var pendingConsent = !string.IsNullOrEmpty(consentApproved)
            ? await _stateCache.GetAsync<PendingAuthorizeRequest>(ConsentState.Key(consentApproved))
            : null;
        if (pendingConsent is not null && pendingConsent.Approved)
        {
            var uid = User.Identity?.IsAuthenticated == true
                ? await _userManager.GetUserIdAsync((await _userManager.GetUserAsync(User))!)
                : null;

            var matches = pendingConsent.UserId == uid
                && string.Equals(pendingConsent.ClientId, request.ClientId, StringComparison.Ordinal)
                && string.Equals(pendingConsent.RedirectUri, request.RedirectUri, StringComparison.Ordinal)
                && string.Equals(pendingConsent.Scope, request.Scope, StringComparison.Ordinal)
                && string.Equals(pendingConsent.ResponseType, request.ResponseType, StringComparison.Ordinal)
                && string.Equals(pendingConsent.CodeChallenge, request.CodeChallenge, StringComparison.Ordinal)
                && string.Equals(pendingConsent.CodeChallengeMethod, request.CodeChallengeMethod, StringComparison.Ordinal);

            await _stateCache.RemoveAsync(ConsentState.Key(consentApproved!));

            if (!matches)
                return BuildErrorResponse(Errors.InvalidRequest, "The consent approval does not match the authorization request.");

            return await ProcessAcceptConsent(request);
        }

        if (request.HasPromptValue(PromptValues.Login))
        {
            await _signInManager.SignOutAsync();
            return Redirect(BuildFrontendLoginUrl(request));
        }

        if (!User.Identity?.IsAuthenticated ?? true)
        {
            if (request.HasPromptValue(PromptValues.None))
            {
                return BuildErrorResponse(Errors.LoginRequired, "The user is not logged in.");
            }

            return Redirect(BuildFrontendLoginUrl(request));
        }

        if (request.MaxAge is not null)
        {
            var authTime = User.FindFirst("auth_time")?.Value;

            if (authTime is not null
                && long.TryParse(authTime, out var authTimeEpoch))
            {
                var authAge = DateTimeOffset.UtcNow.ToUnixTimeSeconds() - authTimeEpoch;
                if (authAge > request.MaxAge.Value)
                {
                    await _signInManager.SignOutAsync();
                    return Redirect(BuildFrontendLoginUrl(request));
                }
            }
        }

        var user = await _userManager.GetUserAsync(User)
            ?? throw new InvalidOperationException("The user cannot be retrieved.");

        var application = await _applicationManager.FindByClientIdAsync(request.ClientId!)
            ?? throw new InvalidOperationException("The application cannot be found.");

        var appId = (await _applicationManager.GetIdAsync(application))!;
        var metadata = await GetClientMetadataAsync(appId);
        if (metadata is { IsDisabled: true })
        {
            return BuildErrorResponse(Errors.UnauthorizedClient, "The application is disabled.");
        }

        var userId = await _userManager.GetUserIdAsync(user);
        var authorizations = await AuthorizationConsolidator.FindActiveAsync(_authorizationManager, userId, appId);

        var requestedScopes = request.GetScopes();
        var hasAllScopes = false;
        foreach (var authorization in authorizations)
        {
            var scopes = await _authorizationManager.GetScopesAsync(authorization);
            if (requestedScopes.All(s => scopes.Contains(s)))
            {
                hasAllScopes = true;
                break;
            }
        }

        if (hasAllScopes && !request.HasPromptValue(PromptValues.Consent))
            return await ProcessAcceptConsent(request);

        if (request.HasPromptValue(PromptValues.None))
        {
            return BuildErrorResponse(Errors.ConsentRequired, "Interactive user consent is required.");
        }

        var appName = (await _applicationManager.GetDisplayNameAsync(application))!;
        var scopeInfos = new List<PendingScope>();
        foreach (var scope in request.GetScopes())
        {
            if (scope is AuthConstants.Scopes.OpenId or AuthConstants.Scopes.OfflineAccess)
                continue;

            var scopeObj = await _scopeManager.FindByNameAsync(scope);
            scopeInfos.Add(new PendingScope
            {
                Name = scope,
                DisplayName = scopeObj is not null
                    ? (await _scopeManager.GetDisplayNameAsync(scopeObj) ?? scope)
                    : scope,
                Description = scopeObj is not null
                    ? (await _scopeManager.GetDescriptionAsync(scopeObj) ?? scope)
                    : scope
            });
        }

        var requestId = Guid.NewGuid().ToString("N");
        await _stateCache.SetAsync(ConsentState.Key(requestId), new PendingAuthorizeRequest
        {
            ClientId = request.ClientId!,
            RedirectUri = request.RedirectUri!,
            Scope = request.Scope!,
            State = request.State,
            ResponseType = request.ResponseType!,
            CodeChallenge = request.CodeChallenge,
            CodeChallengeMethod = request.CodeChallengeMethod,
            Nonce = request.Nonce,
            UserId = (await _userManager.GetUserIdAsync(user)),
            ApplicationId = appId,
            ApplicationName = appName,
            Description = metadata?.Description,
            HomepageUrl = metadata?.HomepageUrl,
            IsFajorCertified = metadata?.IsFajorCertified ?? false,
            Scopes = scopeInfos
        }, ConsentState.PendingTtl);

        return Redirect($"{_frontendBase}/auth-with-pylai?requestId={requestId}");
    }

    [HttpPost("~/connect/token")]
    [IgnoreAntiforgeryToken]
    [Produces("application/json")]
    public async Task<IActionResult> Exchange()
    {
        var request = HttpContext.GetOpenIddictServerRequest()
            ?? throw new InvalidOperationException("The OpenID Connect request cannot be retrieved.");

        if (request.ClientId is not null)
        {
            var application = await _applicationManager.FindByClientIdAsync(request.ClientId!);
            var appId = application is null ? null : await _applicationManager.GetIdAsync(application);
            var metadata = appId is null ? null : await GetClientMetadataAsync(appId);
            if (metadata is { IsDisabled: true })
            {
                return BuildErrorResponse(Errors.UnauthorizedClient, "The application is disabled.");
            }
        }

        if (request.IsAuthorizationCodeGrantType() || request.IsRefreshTokenGrantType())
        {
            var result = await HttpContext.AuthenticateAsync(OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
            var principal = result.Principal
                ?? throw new InvalidOperationException("The user principal cannot be retrieved.");

            return SignIn(principal, OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
        }

        if (request.IsClientCredentialsGrantType())
        {
            var application = await _applicationManager.FindByClientIdAsync(request.ClientId!)
                ?? throw new InvalidOperationException("The application cannot be found.");

            var claims = new List<Claim>
            {
                new(Claims.Subject, request.ClientId!),
                new(Claims.Name, await _applicationManager.GetDisplayNameAsync(application) ?? request.ClientId!)
            };

            var identity = new ClaimsIdentity(claims, "Bearer", Claims.Name, Claims.Role);
            identity.SetDestinations(static claim => claim.Type switch
            {
                Claims.Name => [Destinations.AccessToken, Destinations.IdentityToken],
                _ => [Destinations.AccessToken, Destinations.IdentityToken]
            });

            return SignIn(new ClaimsPrincipal(identity), OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
        }

        throw new InvalidOperationException("The specified grant type is not supported.");
    }

    [HttpGet("~/connect/logout")]
    [HttpPost("~/connect/logout")]
    [IgnoreAntiforgeryToken]
    public async Task<IActionResult> Logout()
    {
        var request = HttpContext.GetOpenIddictServerRequest();

        await _signInManager.SignOutAsync();

        var redirectUri = "/";

        if (request?.PostLogoutRedirectUri is not null)
        {
            var matched = await _applicationManager
                .FindByPostLogoutRedirectUriAsync(request.PostLogoutRedirectUri)
                .ToListAsync();
            if (matched.Count > 0)
            {
                redirectUri = request.PostLogoutRedirectUri;

                if (!string.IsNullOrEmpty(request.State))
                {
                    redirectUri += $"?state={Uri.EscapeDataString(request.State)}";
                }
            }
        }

        return SignOut(
            authenticationSchemes: OpenIddictServerAspNetCoreDefaults.AuthenticationScheme,
            properties: new AuthenticationProperties
            {
                RedirectUri = redirectUri
            });
    }

    private async Task<IActionResult> ProcessAcceptConsent(OpenIddictRequest request)
    {
        var user = await _userManager.GetUserAsync(User)
            ?? throw new InvalidOperationException("The user cannot be retrieved.");

        var application = (await _applicationManager.FindByClientIdAsync(request.ClientId!))!;
        var appId = (await _applicationManager.GetIdAsync(application))!;
        var metadata = await GetClientMetadataAsync(appId);
        if (metadata is { IsDisabled: true })
        {
            return BuildErrorResponse(Errors.UnauthorizedClient, "The application is disabled.");
        }

        var principal = await _signInManager.CreateUserPrincipalAsync(user);

        principal.SetScopes(request.GetScopes());
        principal.SetResources(await _scopeManager.ListResourcesAsync(principal.GetScopes()).ToListAsync());

        ((ClaimsIdentity)principal.Identity!).AddClaim(new Claim(Claims.PreferredUsername, user.DisplayName ?? user.Name));
        if (!string.IsNullOrEmpty(user.Email))
            ((ClaimsIdentity)principal.Identity!).AddClaim(new Claim(Claims.EmailVerified, "true"));

        var subject = await _userManager.GetUserIdAsync(user);
        var requestedScopes = principal.GetScopes().ToList();

        var authorizationId = await MergeAuthorizationAsync(principal, subject, appId, requestedScopes);

        principal.SetAuthorizationId(authorizationId);

        foreach (var claim in principal.Claims)
        {
            claim.SetDestinations(GetDestinations(claim, principal));
        }

        return SignIn(principal, OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
    }

    /// <summary>
    /// 一个用户对一个客户端只保留一条活跃永久授权：已有授权则合并 scope（并集），
    /// 无授权则新建；重复记录删除前将其 token 迁移到主授权。唯一索引 + 乐观并发兜底，冲突重试。
    /// </summary>
    private async Task<string> MergeAuthorizationAsync(
        ClaimsPrincipal principal, string subject, string appId, List<string> requestedScopes)
    {
        for (var attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                await using var tx = await _context.Database.BeginTransactionAsync();

                var merged = await AuthorizationConsolidator.ConsolidateAsync(
                    _authorizationManager, _tokenManager, subject, appId, requestedScopes);

                if (merged is null)
                {
                    var created = await _authorizationManager.CreateAsync(
                        principal: principal,
                        subject: subject,
                        client: appId,
                        type: AuthorizationTypes.Permanent,
                        scopes: requestedScopes.ToImmutableArray());

                    var createdId = await _authorizationManager.GetIdAsync(created);

                    _context.ConsentAuditEvents.Add(new ConsentAuditEvent
                    {
                        Subject = subject,
                        ClientId = appId,
                        Action = ConsentAuditActions.ConsentGranted,
                        RequestedScopes = AuthorizationConsolidator.ToJson(requestedScopes),
                        GrantedScopes = AuthorizationConsolidator.ToJson(requestedScopes),
                        AuthorizationId = createdId
                    });

                    await _context.SaveChangesAsync();
                    await tx.CommitAsync();
                    return createdId;
                }

                if (!merged.GrantedScopes.SequenceEqual(merged.PreviousScopes) || merged.ConsolidatedIds.Count > 0)
                {
                    _context.ConsentAuditEvents.Add(new ConsentAuditEvent
                    {
                        Subject = subject,
                        ClientId = appId,
                        Action = ConsentAuditActions.ConsentScopeMerged,
                        PreviousScopes = AuthorizationConsolidator.ToJson(merged.PreviousScopes),
                        RequestedScopes = AuthorizationConsolidator.ToJson(requestedScopes),
                        GrantedScopes = AuthorizationConsolidator.ToJson(merged.GrantedScopes),
                        AuthorizationId = merged.AuthorizationId
                    });
                }

                await _context.SaveChangesAsync();
                await tx.CommitAsync();
                return merged.AuthorizationId;
            }
            catch (Npgsql.PostgresException ex) when (ex.SqlState == "23505")
            {
                _logger.LogWarning("授权合并唯一冲突，重试 | subject:{Subject} | client:{Client}", subject, appId);
            }
            catch (DbUpdateConcurrencyException)
            {
                _logger.LogWarning("授权合并并发冲突，重试 | subject:{Subject} | client:{Client}", subject, appId);
            }
        }

        throw new InvalidOperationException("授权合并失败：并发冲突重试后仍无法完成。");
    }

    private async Task<OAuthClientMetadata?> GetClientMetadataAsync(string appId)
    {
        return await _context.OAuthClientMetadata.FindAsync([appId]);
    }

    private string BuildFrontendLoginUrl(OpenIddictRequest request)
    {
        var returnUrl = Uri.EscapeDataString(
            $"{Request.PathBase}{Request.Path}{Request.QueryString}");
        return $"{_frontendBase}/login?return_url={returnUrl}";
    }

    private IActionResult BuildErrorResponse(string error, string description)
    {
        var properties = new AuthenticationProperties(new Dictionary<string, string?>
        {
            [OpenIddictServerAspNetCoreConstants.Properties.Error] = error,
            [OpenIddictServerAspNetCoreConstants.Properties.ErrorDescription] = description
        });

        return Forbid(properties, OpenIddictServerAspNetCoreDefaults.AuthenticationScheme);
    }

    private static IEnumerable<string> GetDestinations(Claim claim, ClaimsPrincipal principal)
    {
        return claim.Type switch
        {
            Claims.Subject or Claims.AuthenticationTime or Claims.AccessTokenHash
                or "sid" or "idp" or "amr" or "c_hash" =>
                [Destinations.AccessToken, Destinations.IdentityToken],

            Claims.Name or Claims.PreferredUsername when principal.HasScope(AuthConstants.Scopes.ProfileBasic) =>
                [Destinations.AccessToken, Destinations.IdentityToken],

            Claims.Email or Claims.EmailVerified when principal.HasScope(AuthConstants.Scopes.ProfileMail) =>
                [Destinations.AccessToken, Destinations.IdentityToken],

            Claims.Role when principal.HasScope(AuthConstants.Scopes.ProfileRole) =>
                [Destinations.AccessToken, Destinations.IdentityToken],

            _ => []
        };
    }
}
