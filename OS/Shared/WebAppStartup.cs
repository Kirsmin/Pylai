using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.DataProtection.KeyManagement;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging.Console;

namespace Pylaios.Shared;

/// <summary>
/// serve（Web）启动路径：配置加载 → 服务注册 → 日志 → 迁移门禁 → 请求管线。
/// Program.cs 只保留 flag 预解析与分发，具体流程集中于此。
/// </summary>
public static class WebAppStartup
{
    public static async Task<int> RunAsync(bool testMode, string? configFlag)
    {
        var builder = WebApplication.CreateBuilder();
        CliHelpers.ConfigPath = CliHelpers.ResolveConfigPath(builder.Environment.ContentRootPath, configFlag);

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
        {
            try
            {
                AuthHelper.EnsureTestModeAllowed(builder.Environment);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"错误  Pylaios       {ex.Message}");
                return 3;
            }
            Console.Error.WriteLine($"\x1b[93m{DateTimeOffset.Now:yyyy/MM/dd HH:mm:ss}  \u26A0\uFE0F  Pylaios       TestMode \u2014 邮件不会实际发送，验证码将输出到控制台\x1b[0m");
        }

        if (!string.IsNullOrEmpty(config.Server.Url))
            builder.WebHost.UseUrls(config.Server.Url);

        builder.WebHost.ConfigureKestrel(options =>
        {
            var mb = config.Server.MaxRequestBodyMB > 0 ? config.Server.MaxRequestBodyMB : 2;
            options.Limits.MaxRequestBodySize = mb * 1024L * 1024L;
        });

        var dataProtectionPath = string.IsNullOrWhiteSpace(config.DataProtection.KeyDirectory)
            ? Environment.GetEnvironmentVariable("PYLAI_DATA_DIR")
            : config.DataProtection.KeyDirectory;
        if (!string.IsNullOrWhiteSpace(dataProtectionPath))
        {
            Directory.CreateDirectory(dataProtectionPath);

            var dataDir = Environment.GetEnvironmentVariable("PYLAI_DATA_DIR");
            var dpKekPath = Environment.GetEnvironmentVariable(AesGcmXmlEncryptor.KeyFileEnvironmentVariable);
            if (string.IsNullOrWhiteSpace(dpKekPath) && !string.IsNullOrWhiteSpace(dataDir))
                dpKekPath = Path.Combine(dataDir, "dp-kek");

            if (string.IsNullOrWhiteSpace(dpKekPath) || !File.Exists(dpKekPath))
            {
                Console.Error.WriteLine(
                    $"错误  Pylaios       DataProtection KEK 缺失，拒绝以明文密钥环启动。请通过 {AesGcmXmlEncryptor.KeyFileEnvironmentVariable} 注入 32 字节独立密钥文件");
                return 3;
            }

            try
            {
                // EncryptedXmlInfo stores the decryptor type; DataProtection later constructs it
                // with the parameterless constructor, so publish the resolved path for decryption too.
                Environment.SetEnvironmentVariable(AesGcmXmlEncryptor.KeyFileEnvironmentVariable, dpKekPath);
                var xmlEncryptor = new AesGcmXmlEncryptor(dpKekPath);
                builder.Services.AddDataProtection()
                    .PersistKeysToFileSystem(new DirectoryInfo(dataProtectionPath));
                builder.Services.Configure<KeyManagementOptions>(options => options.XmlEncryptor = xmlEncryptor);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"错误  Pylaios       DataProtection KEK 无效，拒绝启动: {ex.Message}");
                return 3;
            }
        }

        try
        {
            builder.Services.AddPylaios(config, builder.Environment);
            builder.Services.Configure<MvcOptions>(options => options.Filters.Add<ApiEnvelopeResultFilter>());
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"错误  Pylaios       服务配置失败，拒绝启动: {ex.Message}");
            return 3;
        }

        ConfigureLogging(builder.Logging, config, builder.Environment);

        var app = builder.Build();


        MigrationCheckResult migrationCheck;
        try
        {
            migrationCheck = await MigrationGate.CheckAsync(app.Services);
        }
        catch (Exception ex)
        {
            app.Logger.LogError(ex, "迁移状态查询失败，拒绝启动");
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
            app.Logger.LogError("检测到未应用的数据库迁移，拒绝启动。请先执行: Pylaios db migrate");
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
            app.Logger.LogError("数据库迁移超前于当前程序（databaseAhead），拒绝启动");
            Console.Out.WriteLine(CliHelpers.SerializeJson(new
            {
                success = false,
                error = "数据库版本超前于当前程序，拒绝启动。请升级程序或恢复数据库",
                ahead = migrationCheck.Ahead
            }));
            return 3;
        }
        if (migrationCheck.Pending is null)
            app.Logger.LogWarning("数据库连接失败，无法确认迁移状态（/health/ready 将反映数据库状态）");

        if (migrationCheck.Pending is not null)
        {
            try
            {
                await ProductionSecurityGate.ValidateAsync(app.Services, config, app.Environment);
            }
            catch (Exception ex)
            {
                app.Logger.LogError(ex, "生产安全启动门禁失败，拒绝启动");
                return 3;
            }
        }

        if (!testMode
            && (string.IsNullOrEmpty(config.Email.Smtp.Host) || string.IsNullOrEmpty(config.Email.FromAddress)))
        {
            app.Logger.LogWarning("邮件服务未配置（[Email.Smtp.Host] / [Email.FromAddress]）— 注册/重置密码等验证码邮件将不会发送");
        }


        app.UseHostFiltering();
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
        app.UseMiddleware<GlobalExceptionMiddleware>();
        app.UseMiddleware<AuditMiddleware>();
        app.UseMiddleware<AdminApiIpBanMiddleware>();
        app.UseAuthentication();
        app.UseMiddleware<AdminBffCsrfMiddleware>();
        app.UseMiddleware<CookieCsrfMiddleware>();
        app.UseMiddleware<SessionValidationMiddleware>();
        app.UseAuthorization();
        app.MapControllers();

        await app.RunAsync();
        return 0;
    }

    internal static void ConfigureLogging(ILoggingBuilder logging, MainConfig config, IWebHostEnvironment env)
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
    internal static void ConfigureEfLogging(ILoggingBuilder logging)
    {
        logging.AddFilter("Microsoft.EntityFrameworkCore.Database.Command", LogLevel.Error);
        logging.AddFilter("Microsoft.EntityFrameworkCore.Database.Connection", LogLevel.Error);
        logging.AddFilter("Microsoft.EntityFrameworkCore.Database.Transaction", LogLevel.Error);
    }
}
