using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;

namespace Pylaios.Shared;

public enum UserGroupRequirementLevel
{
    AdminOrMax,
    Max
}

public sealed class UserGroupRequirement(UserGroupRequirementLevel level) : IAuthorizationRequirement
{
    public UserGroupRequirementLevel Level { get; } = level;
}

public sealed class UserGroupAuthorizationHandler : AuthorizationHandler<UserGroupRequirement>
{
    private readonly ApplicationDbContext _context;

    public UserGroupAuthorizationHandler(ApplicationDbContext context)
    {
        _context = context;
    }

    protected override async Task HandleRequirementAsync(
        AuthorizationHandlerContext context, UserGroupRequirement requirement)
    {
        var uidClaim = context.User.FindFirst(ClaimTypes.NameIdentifier)?.Value
                    ?? context.User.FindFirst(OpenIddict.Abstractions.OpenIddictConstants.Claims.Subject)?.Value;
        if (uidClaim is null || !Guid.TryParse(uidClaim, out var uid))
            return;

        var group = await _context.Users.AsNoTracking()
            .Where(u => u.Uid == uid && u.Status == UserStatus.Active)
            .Select(u => u.Group)
            .FirstOrDefaultAsync();

        var allowed = requirement.Level switch
        {
            UserGroupRequirementLevel.AdminOrMax => group is AuthConstants.Roles.Admin or AuthConstants.Roles.Max,
            UserGroupRequirementLevel.Max => group == AuthConstants.Roles.Max,
            _ => false
        };

        if (allowed)
            context.Succeed(requirement);
    }
}
