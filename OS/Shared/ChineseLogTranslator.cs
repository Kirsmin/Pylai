using System.Text.RegularExpressions;

namespace Pylaios.Shared;

/// <summary>
/// 控制台日志中文化：把框架（EF Core / ASP.NET Core Hosting / 请求日志）的英文
/// 日志模板翻译为中文，保证控制台输出统一使用中文。
/// 仅作用于日志文本（stderr），不影响 stdout 的 JSON 契约。
/// </summary>
public static class ChineseLogTranslator
{
    /// <summary>按日志类别翻译消息；未命中已知模板时原样返回。</summary>
    public static string Translate(string category, string message)
    {
        if (string.IsNullOrEmpty(message)) return message;

        if (category.StartsWith("Microsoft.EntityFrameworkCore.Database.Command", StringComparison.Ordinal))
            return TranslateCommand(message);
        if (category.StartsWith("Microsoft.EntityFrameworkCore.Database.Connection", StringComparison.Ordinal))
            return TranslateConnection(message);
        if (category.StartsWith("Microsoft.EntityFrameworkCore.Infrastructure", StringComparison.Ordinal))
            return TranslateInfrastructure(message);
        if (category.StartsWith("Microsoft.EntityFrameworkCore.Migrations", StringComparison.Ordinal))
            return TranslateMigrations(message);
        if (category.StartsWith("Microsoft.AspNetCore.Hosting", StringComparison.Ordinal)
            || category.StartsWith("Microsoft.Hosting.Lifetime", StringComparison.Ordinal))
            return TranslateHosting(message);
        return message;
    }

    /// <summary>把日志类别短名翻译为中文（如 Command → 命令）。</summary>
    public static string TranslateCategoryName(string shortName) => shortName switch
    {
        "Command" => "命令",
        "Connection" => "连接",
        "Infrastructure" => "基础设施",
        "Migrations" => "迁移",
        "Hosting" => "托管",
        "Lifetime" => "生命周期",
        "DataProtection" => "数据保护",
        "Authentication" => "认证",
        "Authorization" => "授权",
        "Routing" => "路由",
        "StaticFiles" => "静态文件",
        "HttpsRedirection" => "HTTPS重定向",
        "CORS" => "跨域",
        "Health" => "健康",
        "Logging" => "日志",
        "Configuration" => "配置",
        "HttpLogging" => "HTTP日志",
        "Sockets" => "套接字",
        "Kestrel" => "Kestrel",
        "Account" => "账户",
        "Admin" => "管理",
        "Audit" => "审计",
        "Auth" => "认证",
        "Backup" => "备份",
        "Clients" => "客户端",
        "Config" => "配置",
        "Database" => "数据库",
        "OAuth" => "OAuth",
        "PasswordReset" => "密码重置",
        "Registration" => "注册",
        "SessionValidation" => "会话校验",
        "Users" => "用户",
        "UserTokens" => "用户令牌",
        "Confirmation" => "二次验证",
        "Pylaios" => "Pylaios",
        _ => shortName
    };

    // ── EF Core Database.Command ────────────────────────────────────────────

    private static readonly (Regex Regex, Func<Match, string, string> Build)[] CommandRules =
    {
        // Creating DbCommand for '{commandType}'.
        (new(@"^Creating DbCommand for '(?<cmd>[^']*)'\.$", RegexOptions.Compiled),
         (m, _) => $"正在创建 DbCommand（命令类型 '{TranslateCommandType(m.Groups["cmd"].Value)}'）。"),
        // Created DbCommand for '{commandType}' ({elapsed}ms).
        (new(@"^Created DbCommand for '(?<cmd>[^']*)' \((?<ms>\d+)ms\)\.$", RegexOptions.Compiled),
         (m, _) => $"已创建 DbCommand（命令类型 '{TranslateCommandType(m.Groups["cmd"].Value)}'，耗时 {m.Groups["ms"].Value}ms）。"),
        // Initialized DbCommand for '{commandType}' ({elapsed}ms).
        (new(@"^Initialized DbCommand for '(?<cmd>[^']*)' \((?<ms>\d+)ms\)\.$", RegexOptions.Compiled),
         (m, _) => $"已初始化 DbCommand（命令类型 '{TranslateCommandType(m.Groups["cmd"].Value)}'，耗时 {m.Groups["ms"].Value}ms）。"),
        // Executing DbCommand [Parameters={parameters}, CommandType='{commandType}', CommandTimeout='{commandTimeout}']
        (new(@"^Executing DbCommand \[Parameters=(?<p>.*), CommandType='(?<t>[^']*)', CommandTimeout='(?<to>[^']*)'\]$", RegexOptions.Compiled),
         (m, _) => $"正在执行 DbCommand [参数={m.Groups["p"].Value}，命令类型='{TranslateCommandType(m.Groups["t"].Value)}'，命令超时='{m.Groups["to"].Value}']"),
        // Executed DbCommand ({elapsed}ms) [Parameters=..., CommandType=..., CommandTimeout=...]{newLine}{command}
        (new(@"^Executed DbCommand \((?<ms>\d+)ms\) \[Parameters=(?<p>.*), CommandType='(?<t>[^']*)', CommandTimeout='(?<to>[^']*)'\]", RegexOptions.Compiled),
         (m, msg) => $"已执行 DbCommand（耗时 {m.Groups["ms"].Value}ms）[参数={m.Groups["p"].Value}，命令类型='{TranslateCommandType(m.Groups["t"].Value)}'，命令超时='{m.Groups["to"].Value}']" + msg[m.Length..]),
        // Failed executing DbCommand ({elapsed}ms) [Parameters=..., CommandType=..., CommandTimeout=...]{newLine}{command}
        (new(@"^Failed executing DbCommand \((?<ms>\d+)ms\) \[Parameters=(?<p>.*), CommandType='(?<t>[^']*)', CommandTimeout='(?<to>[^']*)'\]", RegexOptions.Compiled),
         (m, msg) => $"执行 DbCommand 失败（耗时 {m.Groups["ms"].Value}ms）[参数={m.Groups["p"].Value}，命令类型='{TranslateCommandType(m.Groups["t"].Value)}'，命令超时='{m.Groups["to"].Value}']" + msg[m.Length..]),
        // Canceled DbCommand [Parameters={parameters}, CommandType='{commandType}', CommandTimeout='{commandTimeout}']
        (new(@"^Canceled DbCommand \[Parameters=(?<p>.*), CommandType='(?<t>[^']*)', CommandTimeout='(?<to>[^']*)'\]$", RegexOptions.Compiled),
         (m, _) => $"已取消 DbCommand [参数={m.Groups["p"].Value}，命令类型='{TranslateCommandType(m.Groups["t"].Value)}'，命令超时='{m.Groups["to"].Value}']"),
    };

    private static string TranslateCommand(string message)
    {
        foreach (var (regex, build) in CommandRules)
        {
            var m = regex.Match(message);
            if (m.Success) return build(m, message);
        }
        return message;
    }

    private static string TranslateCommandType(string value) => value switch
    {
        "Text" => "文本",
        "StoredProcedure" => "存储过程",
        "TableDirect" => "表直接访问",
        _ => value
    };

    // ── EF Core Database.Connection ─────────────────────────────────────────

    private static readonly (Regex Regex, Func<Match, string, string> Build)[] ConnectionRules =
    {
        // An error occurred using the connection to database '{name}' on server '{server}'.
        (new(@"^An error occurred using the connection to database '(?<n>[^']*)' on server '(?<s>[^']*)'\.$", RegexOptions.Compiled),
         (m, _) => $"连接数据库 '{m.Groups["n"].Value}'（服务器 '{m.Groups["s"].Value}'）时发生错误。"),
        // A transient error occurred during operation. See the inner exception for details.
        (new(@"^A transient error occurred during operation\. See the inner exception for details\.$", RegexOptions.Compiled),
         (_, _) => "操作期间发生瞬时错误，详情见内部异常。"),
        // An error occurred while accessing the database. See the inner exception for details.
        (new(@"^An error occurred while accessing the database\. See the inner exception for details\.$", RegexOptions.Compiled),
         (_, _) => "访问数据库时发生错误，详情见内部异常。"),
    };

    private static string TranslateConnection(string message)
    {
        foreach (var (regex, build) in ConnectionRules)
        {
            var m = regex.Match(message);
            if (m.Success) return build(m, message);
        }
        return message;
    }

    // ── EF Core Infrastructure ──────────────────────────────────────────────

    private static readonly (Regex Regex, Func<Match, string, string> Build)[] InfrastructureRules =
    {
        // Entity Framework Core {version} initialized '{contextType}' using provider '{provider}' with options: {options}
        (new(@"^Entity Framework Core (?<v>.+) initialized '(?<ctx>[^']*)' using provider '(?<p>[^']*)' with options: (?<o>.*)$", RegexOptions.Compiled),
         (m, _) => $"Entity Framework Core {m.Groups["v"].Value} 已初始化上下文 '{m.Groups["ctx"].Value}'，使用数据库提供程序 '{m.Groups["p"].Value}'，选项：{m.Groups["o"].Value}"),
        // Using database provider '{provider}'
        (new(@"^Using database provider '(?<p>[^']*)'$", RegexOptions.Compiled),
         (m, _) => $"正在使用数据库提供程序 '{m.Groups["p"].Value}'"),
        // A data context was detected with the following changes: {changes}
        (new(@"^A data context was detected with the following changes: (?<c>.*)$", RegexOptions.Compiled),
         (m, _) => $"检测到数据上下文存在以下更改：{m.Groups["c"].Value}"),
        // The model for context '{contextType}' has pending changes. {changes}
        (new(@"^The model for context '(?<ctx>[^']*)' has pending changes\. (?<c>.*)$", RegexOptions.Compiled),
         (m, _) => $"上下文 '{m.Groups["ctx"].Value}' 的模型存在待应用的更改：{m.Groups["c"].Value}"),
    };

    private static string TranslateInfrastructure(string message)
    {
        foreach (var (regex, build) in InfrastructureRules)
        {
            var m = regex.Match(message);
            if (m.Success) return build(m, message);
        }
        return message;
    }

    // ── EF Core Migrations ──────────────────────────────────────────────────

    private static readonly (Regex Regex, Func<Match, string, string> Build)[] MigrationRules =
    {
        // Applying migration '{migrationId}'.
        (new(@"^Applying migration '(?<id>[^']*)'\.$", RegexOptions.Compiled),
         (m, _) => $"正在应用迁移 '{m.Groups["id"].Value}'。"),
        // Reverting migration '{migrationId}'.
        (new(@"^Reverting migration '(?<id>[^']*)'\.$", RegexOptions.Compiled),
         (m, _) => $"正在回滚迁移 '{m.Groups["id"].Value}'。"),
        // Skipping migration '{migrationId}'.
        (new(@"^Skipping migration '(?<id>[^']*)'\.$", RegexOptions.Compiled),
         (m, _) => $"正在跳过迁移 '{m.Groups["id"].Value}'。"),
        // Migration '{migrationId}' has been applied.
        (new(@"^Migration '(?<id>[^']*)' has been applied\.$", RegexOptions.Compiled),
         (m, _) => $"迁移 '{m.Groups["id"].Value}' 已应用。"),
        // Migration '{migrationId}' has been reverted.
        (new(@"^Migration '(?<id>[^']*)' has been reverted\.$", RegexOptions.Compiled),
         (m, _) => $"迁移 '{m.Groups["id"].Value}' 已回滚。"),
        // Database already exists. No migration has been applied.
        (new(@"^Database already exists\. No migration has been applied\.$", RegexOptions.Compiled),
         (_, _) => "数据库已存在，未应用任何迁移。"),
        // Database '{name}' created.
        (new(@"^Database '(?<n>[^']*)' created\.$", RegexOptions.Compiled),
         (m, _) => $"数据库 '{m.Groups["n"].Value}' 已创建。"),
    };

    private static string TranslateMigrations(string message)
    {
        foreach (var (regex, build) in MigrationRules)
        {
            var m = regex.Match(message);
            if (m.Success) return build(m, message);
        }
        return message;
    }

    // ── ASP.NET Core Hosting / 请求日志 ─────────────────────────────────────

    private static readonly (Regex Regex, Func<Match, string, string> Build)[] HostingRules =
    {
        // Now listening on: {address}
        (new(@"^Now listening on: (?<a>.*)$", RegexOptions.Compiled),
         (m, _) => $"正在监听: {m.Groups["a"].Value}"),
        // Application started. Press Ctrl+C to shut down.
        (new(@"^Application started\. Press Ctrl\+C to shut down\.$", RegexOptions.Compiled),
         (_, _) => "应用程序已启动，按 Ctrl+C 关闭。"),
        // Application is shutting down...
        (new(@"^Application is shutting down\.\.\.$", RegexOptions.Compiled),
         (_, _) => "应用程序正在关闭……"),
        // Hosting environment: {envName}
        (new(@"^Hosting environment: (?<e>.*)$", RegexOptions.Compiled),
         (m, _) => $"托管环境: {m.Groups["e"].Value}"),
        // Content root path: {path}
        (new(@"^Content root path: (?<p>.*)$", RegexOptions.Compiled),
         (m, _) => $"内容根路径: {m.Groups["p"].Value}"),
        // Overriding address(es) '{addresses}'. Binding to {endpoints} instead.
        (new(@"^Overriding address\(es\) '(?<a>.*)'\. Binding to (?<e>.*) instead\.$", RegexOptions.Compiled),
         (m, _) => $"覆盖地址 '{m.Groups["a"].Value}'，改用 {m.Groups["e"].Value} 绑定。"),
        // Request starting HTTP/1.1 {method} {scheme}://{host}{pathBase}{path}{query}
        (new(@"^Request starting HTTP/1\.1 (?<r>.*)$", RegexOptions.Compiled),
         (m, _) => $"请求开始 HTTP/1.1 {m.Groups["r"].Value}"),
        // Request finished HTTP/1.1 {method} {scheme}://{host}{pathBase}{path}{query} - {statusCode} - {contentType} {elapsed}ms
        (new(@"^Request finished HTTP/1\.1 (?<r>.*)$", RegexOptions.Compiled),
         (m, _) => $"请求结束 HTTP/1.1 {m.Groups["r"].Value}"),
        // Failed to determine the https port for redirect.
        (new(@"^Failed to determine the https port for redirect\.$", RegexOptions.Compiled),
         (_, _) => "无法确定 HTTPS 重定向端口。"),
    };

    private static string TranslateHosting(string message)
    {
        foreach (var (regex, build) in HostingRules)
        {
            var m = regex.Match(message);
            if (m.Success) return build(m, message);
        }
        return message;
    }
}
