using System.Reflection;
using Microsoft.AspNetCore.DataProtection;
using Cocona;
using Cocona.CommandLine;
using Microsoft.Extensions.Logging.Console;

var rest = new List<string>();
string? configFlag = null;
var testMode = false;
var versionFlag = false;

for (var i = 0; i < args.Length; i++)
{
    var a = args[i];
    if (a == "--config" && i + 1 < args.Length) { configFlag = args[++i]; continue; }
    if (a.StartsWith("--config=", StringComparison.Ordinal)) { configFlag = a["--config=".Length..]; continue; }
    if (a == "--output" && i + 1 < args.Length) { CliHelpers.OutputFormat = args[++i]; continue; }
    if (a.StartsWith("--output=", StringComparison.Ordinal)) { CliHelpers.OutputFormat = a["--output=".Length..]; continue; }
    if (a == "--TestMode") { testMode = true; continue; }
    if (a == "--version") { versionFlag = true; continue; }
    rest.Add(a);
}

if (versionFlag)
{
    Console.Out.WriteLine(CliHelpers.SerializeJson(new
    {
        success = true,
        name = "Pylaios",
        version = VersionInfo()
    }));
    return 0;
}

var cliArgs = rest.ToArray();
return cliArgs.Length == 0 || cliArgs[0] == "serve"
    ? await RunWebAsync(testMode, configFlag)
    : await RunCliAsync(cliArgs, cliArgs, configFlag);



static async Task<int> RunWebAsync(bool testMode, string? configFlag)
{
    var builder = WebApplication.CreateBuilder();
    CliHelpers.ConfigPath = ResolveConfigPath(builder.Environment.ContentRootPath, configFlag);

    MainConfig config;
    var loadResult = ConfigLoader.Load(CliHelpers.ConfigPath, builder.Environment.EnvironmentName);
    if (loadResult.Errors.Count > 0 || loadResult.Config is null)
    {
        Console.Error.WriteLine("配置校验失败，拒绝启动：");
        foreach (var e in loadResult.Errors)
            Console.Error.WriteLine($"  [{e.Code}] {e.File}: {e.Path} — {e.Message}");
        return 2;
    }
    config = loadResult.Config;

    builder.Services.AddSingleton(new TestModeOptions { Enabled = testMode });
    if (testMode)
        Console.Error.WriteLine($"\x1b[93m{DateTimeOffset.Now:yyyy/MM/dd HH:mm:ss}  \u26A0\uFE0F  Pylaios       TestMode \u2014 邮件不会实际发送，验证码将输出到控制台\x1b[0m");

    if (!string.IsNullOrEmpty(config.Server.Url))
        builder.WebHost.UseUrls(config.Server.Url);

    builder.WebHost.ConfigureKestrel(options =>
    {
        var mb = config.Server.MaxRequestBodyMB > 0 ? config.Server.MaxRequestBodyMB : 2;
        options.Limits.MaxRequestBodySize = mb * 1024L * 1024L;
    });

    var dataProtectionPath = Environment.GetEnvironmentVariable("PYLAI_DATA_DIR");
    if (!string.IsNullOrWhiteSpace(dataProtectionPath))
    {
        Directory.CreateDirectory(dataProtectionPath);
        builder.Services.AddDataProtection()
            .PersistKeysToFileSystem(new DirectoryInfo(dataProtectionPath));
    }

    builder.Services.AddPylaios(config, builder.Environment);

    ConfigureLogging(builder.Logging, config, builder.Environment);

    var app = builder.Build();


    MigrationCheckResult migrationCheck;
    try
    {
        migrationCheck = await MigrationGate.CheckAsync(app.Services);
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"错误  Pylaios       迁移状态查询失败，拒绝启动: {ex.Message}");
        Console.Out.WriteLine(CliHelpers.SerializeJson(new
        {
            success = false,
            error = "迁移状态查询失败，拒绝启动。请检查数据库后重试",
            detail = ex.Message.Replace('\r', ' ').Replace('\n', ' ')
        }));
        return 3;
    }
    if (migrationCheck.Pending is { Length: > 0 })
    {
        Console.Error.WriteLine("错误  Pylaios       检测到未应用的数据库迁移，拒绝启动。请先执行: Pylaios db migrate");
        Console.Out.WriteLine(CliHelpers.SerializeJson(new
        {
            success = false,
            error = "数据库存在未应用的迁移，拒绝启动。请先执行 db migrate",
            pending = migrationCheck.Pending
        }));
        return 3;
    }
    if (migrationCheck.Ahead.Length > 0)
    {
        Console.Error.WriteLine("错误  Pylaios       数据库迁移超前于当前程序（databaseAhead），拒绝启动");
        Console.Out.WriteLine(CliHelpers.SerializeJson(new
        {
            success = false,
            error = "数据库版本超前于当前程序，拒绝启动。请升级程序或恢复数据库",
            ahead = migrationCheck.Ahead
        }));
        return 3;
    }
    if (migrationCheck.Pending is null)
        Console.Error.WriteLine("警告  Pylaios       数据库连接失败，无法确认迁移状态（/health/ready 将反映数据库状态）");

    if (!testMode
        && (string.IsNullOrEmpty(config.Email.Smtp.Host) || string.IsNullOrEmpty(config.Email.FromAddress)))
    {
        Console.Error.WriteLine("\x1b[93m警告  Pylaios       邮件服务未配置（[Email.Smtp.Host] / [Email.FromAddress]）— 注册/重置密码等验证码邮件将不会发送\x1b[0m");
    }


    app.UseForwardedHeaders();

    if (app.Environment.IsDevelopment())
        app.UseDeveloperExceptionPage();
    else
        app.UseExceptionHandler("/error");

    if (config.Cors.Enabled)
        app.UseCors("DefaultCors");

    app.UseRouting();
    if (app.Environment.IsDevelopment())
    {
        app.UseOpenApi();
        app.UseSwaggerUi();
    }
    app.UseMiddleware<AuditMiddleware>();
    app.UseMiddleware<AdminApiIpBanMiddleware>();
    app.UseAuthentication();
    app.UseMiddleware<SessionValidationMiddleware>();
    app.UseAuthorization();
    app.MapControllers();

    await app.RunAsync();
    return 0;
}




static async Task<int> RunCliAsync(string[] args, string[] cliArgs, string? configFlag)
{
    CliHelpers.ConfigPath = ResolveConfigPath(Environment.CurrentDirectory, configFlag);

    var loadResult = ConfigLoader.Load(CliHelpers.ConfigPath, "Production");
    if (loadResult.Errors.Count > 0 || loadResult.Config is null)
    {
        Console.Out.WriteLine(CliHelpers.SerializeJson(new
        {
            success = false,
            errors = loadResult.Errors
        }));
        return 2;
    }
    var config = loadResult.Config;

    var cocona = CoconaApp.CreateBuilder();
    cocona.Services.AddPylaios(config, env: null, cliOnly: true);

    // CLI 输出规范：stdout=JSON、stderr=日志。日志显式走 stderr，避免与 JSON 混流；
    // 与 web 共用 emoji formatter（统一格式 + 框架英文日志自动翻译为中文）
    cocona.Services.AddLogging(logging =>
    {
        logging.ClearProviders();
        logging.AddConsoleFormatter<EmojiConsoleFormatter, ConsoleFormatterOptions>(options =>
        {
            options.TimestampFormat = "yyyy/MM/dd HH:mm:ss";
        });
        logging.AddConsole(options =>
        {
            options.FormatterName = "emoji";
            options.LogToStandardErrorThreshold = LogLevel.Trace;
        });
        // 数据库操作信息只在出错时显示（CLI 与 web 一致，见 ConfigureEfLogging）；
        // 真实数据库错误仍由命令层异常 + JSON 错误输出上报。
        ConfigureEfLogging(logging);
        // CLI 不签发 Cookie/Token，DataProtection 密钥环仅临时生成，相关持久化/加密警告无意义
        logging.AddFilter("Microsoft.AspNetCore.DataProtection", LogLevel.Error);
    });

    cocona.Services.AddSingleton<ICoconaEnvironmentProvider>(
        new CliEnvironmentProvider(args));
    var app = cocona.Build();

    app.AddSubCommand("config", c => c.AddCommands<ConfigCommands>());
    app.AddSubCommand("user", c => c.AddCommands<UserCommands>());
    app.AddSubCommand("client", c => c.AddCommands<ClientCommands>());
    app.AddSubCommand("ban", c => c.AddCommands<BanCommands>());
    app.AddSubCommand("user-token", c => c.AddCommands<UserTokenCommands>());
    app.AddSubCommand("db", c => c.AddCommands<DbCommands>());
    app.AddSubCommand("key", c => c.AddCommands<SigningKeyCommands>());
    app.AddSubCommand("backup", c => c.AddCommands<BackupCommands>());

    try
    {

        var group = args[0];
        if (group is not ("db" or "config"))
        {
            var gate = await MigrationGate.CheckCliAsync(app.Services);
            if (gate != 0) return gate;
        }
        await app.RunAsync();
        return Environment.ExitCode;
    }
    catch (Exception ex)
    {
        var message = ex.Message.Replace('\r', ' ').Replace('\n', ' ');
        if (message.Length > 300) message = message[..300] + " ...";
        return await CliHelpers.ErrorAsync(message);
    }
}




static string ResolveConfigPath(string baseDir, string? flag)
{
    var path = flag ?? Environment.GetEnvironmentVariable("PYLAI_CONFIG");
    if (path is not null)
        return Path.GetFullPath(path, Environment.CurrentDirectory);

    var rootCandidate = Path.Combine(baseDir, "pylai.toml");
    var cwdCandidate = Path.Combine(Environment.CurrentDirectory, "pylai.toml");
    if (File.Exists(rootCandidate)) return rootCandidate;
    if (File.Exists(cwdCandidate)) return cwdCandidate;
    return cwdCandidate;
}

static string VersionInfo()
{
    var assembly = Assembly.GetExecutingAssembly();
    var v = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "0.0.0";
    if (v.Contains('+', StringComparison.Ordinal))
        v = v[..v.IndexOf('+')];
    return v;
}

static void ConfigureLogging(ILoggingBuilder logging, MainConfig config, IWebHostEnvironment env)
{
    logging.ClearProviders();
    logging.AddConsoleFormatter<EmojiConsoleFormatter, ConsoleFormatterOptions>(options =>
    {
        options.TimestampFormat = "yyyy/MM/dd HH:mm:ss";
    });

    logging.AddConsole(o =>
    {
        o.FormatterName = "emoji";
        o.LogToStandardErrorThreshold = LogLevel.Trace;
    });
    logging.SetMinimumLevel(Enum.Parse<LogLevel>(config.Logging.DefaultLevel));
    logging.AddFilter("Microsoft.AspNetCore", Enum.Parse<LogLevel>(config.Logging.MicrosoftAspNetCoreLevel));
    logging.AddFilter("Pylaios", Enum.Parse<LogLevel>(config.Logging.PylaiosLevel));

    // 数据库操作信息只在出错时显示（避免健康检查 SELECT 1 / 日常查询刷屏）——
    // 见 ConfigureEfLogging；开发环境额外抑制 DataProtection 临时密钥警告
    // （密钥环随容器临时生成，持久化/加密警告无意义；生产环境保留以便排查）。
    ConfigureEfLogging(logging);

    if (env.IsDevelopment())
        logging.AddFilter("Microsoft.AspNetCore.DataProtection", LogLevel.Error);
}


/// <summary>
/// 数据库操作信息只在出错时显示（web 与 CLI 共用）：
/// Command/Connection/Transaction 仅保留 Error 及以上，避免健康检查 SELECT 1 /
/// 日常查询刷屏。全新数据库首启时迁移探测查询 __EFMigrationsHistory 触发的
/// 42P01 "Failed executing DbCommand"（EventId 20102）属正常首启流程噪音
/// （EF 内部已捕获、迁移门禁显式兜底），由 EmojiConsoleFormatter 抑制。
/// </summary>
static void ConfigureEfLogging(ILoggingBuilder logging)
{
    logging.AddFilter("Microsoft.EntityFrameworkCore.Database.Command", LogLevel.Error);
    logging.AddFilter("Microsoft.EntityFrameworkCore.Database.Connection", LogLevel.Error);
    logging.AddFilter("Microsoft.EntityFrameworkCore.Database.Transaction", LogLevel.Error);
}


sealed class CliEnvironmentProvider(string[] args) : ICoconaEnvironmentProvider
{
    public string[] GetCommandLineArgs() => args;
}
