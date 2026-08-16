using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;

namespace Pylaios.Features.Database;






public static class DbBootstrap
{
    public static async Task BootstrapAsync(IServiceProvider serviceProvider, MainConfig config)
    {
        using var scope = serviceProvider.CreateScope();

        var scopeManager = scope.ServiceProvider.GetRequiredService<IOpenIddictScopeManager>();

        await SeedScopesAsync(scopeManager, config);
    }

    private static async Task SeedScopesAsync(IOpenIddictScopeManager scopeManager, MainConfig config)
    {
        var scopeDefs = new Dictionary<string, (string? displayName, string? description)>
        {
            [AuthConstants.Scopes.OpenId] = (null, null),
            [AuthConstants.Scopes.ProfileBasic] = ("基础个人资料", "用户名、显示名等基础信息"),
            [AuthConstants.Scopes.ProfileMail] = ("邮箱地址", "你的邮箱地址"),
            [AuthConstants.Scopes.ProfileRole] = ("用户权限组", "当前账户所属用户权限组"),
            [AuthConstants.Scopes.OfflineAccess] = (null, null),
        };

        var enabledScopes = config.OpenIddict.Scopes.Enabled();

        foreach (var scopeName in enabledScopes)
        {
            if (scopeDefs.TryGetValue(scopeName, out var def))
            {
                await CreateScopeIfNotExists(scopeManager, scopeName, def.displayName, def.description);
            }
        }
    }

    private static async Task CreateScopeIfNotExists(
        IOpenIddictScopeManager scopeManager, string name, string? displayName, string? description)
    {
        if (await scopeManager.FindByNameAsync(name) is not null)
            return;

        await scopeManager.CreateAsync(new OpenIddictScopeDescriptor
        {
            Name = name,
            DisplayName = displayName,
            Description = description
        });
    }
}
