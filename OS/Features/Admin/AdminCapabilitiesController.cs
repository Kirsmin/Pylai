using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace Pylaios.Features.Admin;

[ApiController]
[Route("api/admin")]
[Authorize(Policy = AuthConstants.Policies.AuthenticatedApi)]
public class AdminCapabilitiesController : ControllerBase
{
    private readonly ApplicationDbContext _context;

    public AdminCapabilitiesController(ApplicationDbContext context)
    {
        _context = context;
    }

    [HttpGet("capabilities")]
    public async Task<IActionResult> Get()
    {
        var user = await this.GetCurrentUserAsync(_context);
        if (user is null)
            return Unauthorized(new ApiResponse { Success = false, Error = "Unauthorized.", ErrorCode = "unauthorized" });

        var isMax = user.Group == AuthConstants.Roles.Max;
        var isAdmin = user.Group == AuthConstants.Roles.Admin;
        var capabilities = new List<AdminCapability>();

        if (isAdmin || isMax)
            capabilities.Add(UsersCapability(isMax));

        if (isMax)
        {
            capabilities.Add(InviteCodesCapability());
            capabilities.Add(BansCapability());
            capabilities.Add(AuditLogsCapability());
            capabilities.Add(ClientsCapability());
        }

        return Ok(new AdminCapabilitiesResponse
        {
            Success = true,
            User = new AdminCapabilityUser
            {
                Uid = user.Uid,
                Name = user.Name,
                DisplayName = user.DisplayName,
                Email = user.Email,
                Group = user.Group
            },
            Capabilities = capabilities
        });
    }

    private static AdminCapability UsersCapability(bool isMax)
    {
        var capability = new AdminCapability
        {
            Key = "users",
            Name = "用户管理",
            Description = "查看和管理用户、会话与 UserToken",
            Route = "/users",
            CanEditGroup = isMax,
            CanEditStatus = isMax,
            TargetGroups = isMax
                ? [AuthConstants.Roles.Normal, AuthConstants.Roles.Admin, AuthConstants.Roles.Max]
                : [AuthConstants.Roles.Normal],
            Endpoints =
            [
                Endpoint("GET", "/api/admin/users"),
                Endpoint("GET", "/api/admin/users/{uid}"),
                Endpoint("PATCH", "/api/admin/users/{uid}"),
                Endpoint("POST", "/api/admin/users/{uid}/reset-password"),
                Endpoint("POST", "/api/admin/users/{uid}/revoke-sessions"),
                Endpoint("GET", "/api/admin/users/{uid}/sessions"),
                Endpoint("DELETE", "/api/admin/users/{uid}/sessions/{sessionId}"),
                Endpoint("GET", "/api/admin/users/{uid}/token"),
                Endpoint("DELETE", "/api/admin/users/{uid}/token"),
                Endpoint("DELETE", "/api/admin/users/{uid}")
            ]
        };
        return capability;
    }

    private static AdminCapability InviteCodesCapability() => new()
    {
        Key = "inviteCodes",
        Name = "邀请码",
        Description = "创建和管理注册提权邀请码",
        Route = "/invite-codes",
        Endpoints =
        [
            Endpoint("GET", "/api/admin/invite-codes"),
            Endpoint("POST", "/api/admin/invite-codes"),
            Endpoint("GET", "/api/admin/invite-codes/{id}"),
            Endpoint("PATCH", "/api/admin/invite-codes/{id}"),
            Endpoint("POST", "/api/admin/invite-codes/revoke")
        ]
    };

    private static AdminCapability BansCapability() => new()
    {
        Key = "bans",
        Name = "封禁管理",
        Description = "查看当前封禁、历史记录并解封",
        Route = "/bans",
        Endpoints =
        [
            Endpoint("GET", "/api/admin/bans"),
            Endpoint("GET", "/api/admin/bans/history"),
            Endpoint("DELETE", "/api/admin/bans/{banId}"),
            Endpoint("DELETE", "/api/admin/bans/ip/{ip}")
        ]
    };

    private static AdminCapability AuditLogsCapability() => new()
    {
        Key = "auditLogs",
        Name = "审计日志",
        Description = "查询平台操作与安全审计日志",
        Route = "/audit-logs",
        Endpoints =
        [
            Endpoint("GET", "/api/admin/audit-logs")
        ]
    };

    private static AdminCapability ClientsCapability() => new()
    {
        Key = "clients",
        Name = "客户端管理",
        Description = "管理 OAuth2/OIDC 客户端、权限与 Logo",
        Route = "/clients",
        Endpoints =
        [
            Endpoint("GET", "/api/clients"),
            Endpoint("POST", "/api/clients"),
            Endpoint("GET", "/api/clients/{id}"),
            Endpoint("PUT", "/api/clients/{id}"),
            Endpoint("PATCH", "/api/clients/{id}/disable"),
            Endpoint("PATCH", "/api/clients/{id}/enable"),
            Endpoint("DELETE", "/api/clients/{id}"),
            Endpoint("GET", "/api/clients/{id}/logo"),
            Endpoint("PUT", "/api/clients/{id}/logo"),
            Endpoint("DELETE", "/api/clients/{id}/logo")
        ]
    };

    private static AdminCapabilityEndpoint Endpoint(string method, string path) => new()
    {
        Method = method,
        Path = path
    };
}
