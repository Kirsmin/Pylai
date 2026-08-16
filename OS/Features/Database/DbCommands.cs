using Cocona;
using Microsoft.EntityFrameworkCore;
using OpenIddict.Abstractions;

namespace Pylaios.Features.Database;





public sealed class DbCommands
{
    private readonly CliCommandContext _ctx;
    private readonly IOpenIddictAuthorizationManager _authorizationManager;
    private readonly IOpenIddictTokenManager _tokenManager;

    public DbCommands(
        CliCommandContext ctx,
        IOpenIddictAuthorizationManager authorizationManager,
        IOpenIddictTokenManager tokenManager)
    {
        _ctx = ctx;
        _authorizationManager = authorizationManager;
        _tokenManager = tokenManager;
    }


    [Command("status", Description = "只读迁移状态（applied/pending）")]
    public async Task<int> StatusAsync()
    {
        var applied = await _ctx.Db.Database.GetAppliedMigrationsAsync();
        var pending = await _ctx.Db.Database.GetPendingMigrationsAsync();
        return await CliHelpers.OkAsync(new { success = true, applied, pending });
    }


    [Command("migrate", Description = "显式应用全部 pending 迁移")]
    public async Task<int> MigrateAsync()
    {
        var appliedBefore = await _ctx.Db.Database.GetAppliedMigrationsAsync();
        await _ctx.Db.Database.MigrateAsync();
        var pending = await _ctx.Db.Database.GetPendingMigrationsAsync();

        await CliHelpers.LogAsync(_ctx, "cli:db migrate", true, $"db migrate {appliedBefore.Count()} -> applied");

        return await CliHelpers.OkAsync(new
        {
            success = true,
            appliedBefore,
            applied = (await _ctx.Db.Database.GetAppliedMigrationsAsync()).Except(appliedBefore),
            pending
        });
    }


    [Command("bootstrap", Description = "系统必需数据引导（权限组/Scopes，幂等）")]
    public async Task<int> BootstrapAsync()
    {
        try
        {
            await DbBootstrap.BootstrapAsync(_ctx.Services, _ctx.Config);
        }
        catch (Npgsql.PostgresException ex) when (ex.SqlState == "42P01")
        {
            return await CliHelpers.ErrorAsync(
                "数据库表不存在：请先执行 `db migrate` 应用迁移后再执行 `db bootstrap`。");
        }

        await CliHelpers.LogAsync(_ctx, "cli:db bootstrap", true, "db bootstrap completed");

        return await CliHelpers.OkAsync(new { success = true, bootstrapped = true });
    }


    [Command("seed", Description = "显式插入种子数据（初始账号/邀请码，幂等）")]
    public async Task<int> SeedAsync()
    {
        try
        {
            await DbSeeder.SeedAsync(_ctx.Services, _ctx.Config);
        }
        catch (Npgsql.PostgresException ex) when (ex.SqlState == "42P01")
        {
            return await CliHelpers.ErrorAsync(
                "数据库表不存在：请先执行 `db migrate` 应用迁移后再执行 `db seed`。");
        }

        await CliHelpers.LogAsync(_ctx, "cli:db seed", true, "db seed completed");

        return await CliHelpers.OkAsync(new { success = true, seeded = true });
    }

    [Command("consolidate-authorizations",
        Description = "合并同一用户+客户端的重复永久授权（scope 并集，token 迁移，幂等）")]
    public async Task<int> ConsolidateAuthorizationsAsync()
    {
        var result = await AuthorizationConsolidator.ConsolidateAllAsync(
            _authorizationManager, _tokenManager, _ctx.Db);

        await CliHelpers.LogAsync(_ctx, "cli:db consolidate-authorizations", true,
            $"db consolidate-authorizations groups={result.GroupsProcessed} auths={result.AuthorizationsConsolidated} tokens={result.TokensReassigned}");

        return await CliHelpers.OkAsync(new
        {
            success = true,
            groupsProcessed = result.GroupsProcessed,
            authorizationsConsolidated = result.AuthorizationsConsolidated,
            tokensReassigned = result.TokensReassigned
        });
    }
}
