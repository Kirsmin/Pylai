using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Pylaios.Shared.Cli;


public sealed class MigrationCheckResult
{

    public string[]? Pending;

    public string[] Ahead = [];
}







public static class MigrationGate
{
    public static async Task<MigrationCheckResult> CheckAsync(IServiceProvider services)
    {
        var result = new MigrationCheckResult();
        try
        {
            using var scope = services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
            var codeMigrations = db.Database.GetMigrations().ToArray();
            var applied = await db.Database.GetAppliedMigrationsAsync();
            result.Pending = codeMigrations.Except(applied).ToArray();
            result.Ahead = applied.Except(codeMigrations).ToArray();
            return result;
        }
        catch (PostgresException ex) when (ex.SqlState == "42P01")
        {
            using var scope = services.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
            result.Pending = db.Database.GetMigrations().ToArray();
            return result;
        }
        catch (NpgsqlException ex) when (IsConnectionFailure(ex))
        {
            result.Pending = null;
            return result;
        }
    }


    public static bool IsConnectionFailure(NpgsqlException ex)
    {
        for (var e = (Exception?)ex; e is not null; e = e.InnerException)
        {
            if (e is System.Net.Sockets.SocketException or TimeoutException or System.Net.Http.HttpRequestException)
                return true;
            if (e is PostgresException)
                return false;
        }
        return false;
    }


    public static async Task<int> CheckCliAsync(IServiceProvider services)
    {
        MigrationCheckResult check;
        try
        {
            check = await CheckAsync(services);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"错误  Pylaios       迁移状态查询失败，拒绝执行: {ex.Message}");
            Console.Out.WriteLine(CliHelpers.SerializeJson(new
            {
                success = false,
                error = "迁移状态查询失败，拒绝执行。请检查数据库后重试",
                detail = ex.Message.Replace('\r', ' ').Replace('\n', ' ')
            }));
            return 3;
        }
        if (check.Pending is { Length: > 0 })
        {
            Console.Error.WriteLine("Pylaios       数据库存在未应用的迁移，拒绝执行。请先运行: Pylaios db migrate");
            Console.Out.WriteLine(CliHelpers.SerializeJson(new
            {
                success = false,
                error = "数据库存在未应用的迁移，请先执行 db migrate",
                pending = check.Pending
            }));
            return 3;
        }
        if (check.Ahead.Length > 0)
        {
            Console.Error.WriteLine("Pylaios       数据库迁移超前于当前程序（databaseAhead），拒绝执行");
            Console.Out.WriteLine(CliHelpers.SerializeJson(new
            {
                success = false,
                error = "数据库版本超前于当前程序，拒绝执行。请升级程序或恢复数据库",
                ahead = check.Ahead
            }));
            return 3;
        }
        return 0;
    }
}
