using Cocona;
using Cocona.CommandLine;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Logging.Console;

namespace Pylaios.Shared;

/// <summary>
/// CLI（Cocona）启动路径：配置加载 → 服务注册（cliOnly）→ 日志 → 子命令 + 迁移门禁。
/// 输出规范：stdout=JSON、stderr=日志；exit 0/1/2/3。
/// </summary>
public static class CliAppStartup
{
    public static async Task<int> RunAsync(string[] args, string[] cliArgs, string? configFlag)
    {
        CliHelpers.ConfigPath = CliHelpers.ResolveConfigPath(Environment.CurrentDirectory, configFlag);

        var cliEnvironment = Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT") ?? "Production";
        var loadResult = ConfigLoader.Load(CliHelpers.ConfigPath, cliEnvironment);
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
        cocona.Services.AddSingleton<IWebHostEnvironment>(new CliHostEnvironment
        {
            EnvironmentName = cliEnvironment,
            ContentRootPath = Environment.CurrentDirectory
        });
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
            WebAppStartup.ConfigureEfLogging(logging);
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
        app.AddSubCommand("invite", c => c.AddCommands<InviteCommands>());
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
            Console.Out.Flush();
            Console.Error.Flush();
            Environment.Exit(Environment.ExitCode);
            return 0;
        }
        catch (Exception ex)
        {
            var message = ex.Message.Replace('\r', ' ').Replace('\n', ' ');
            if (message.Length > 300) message = message[..300] + " ...";
            var code = await CliHelpers.ErrorAsync(message);
            Console.Out.Flush();
            Console.Error.Flush();
            Environment.Exit(code);
            return 0;
        }
    }
}

sealed class CliEnvironmentProvider(string[] args) : ICoconaEnvironmentProvider
{
    public string[] GetCommandLineArgs() => args;
}


sealed class CliHostEnvironment : IWebHostEnvironment
{
    public string ApplicationName { get; set; } = "Pylaios.Cli";
    public IFileProvider WebRootFileProvider { get; set; } = new NullFileProvider();
    public string WebRootPath { get; set; } = "";
    public string EnvironmentName { get; set; } = "Production";
    public string ContentRootPath { get; set; } = "";
    public IFileProvider ContentRootFileProvider { get; set; } = new NullFileProvider();
}
