using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Logging.Console;
using Microsoft.Extensions.Options;

namespace Pylaios.Shared;

public sealed class EmojiConsoleFormatter : ConsoleFormatter, IDisposable
{
    private readonly IDisposable? _optionsReloadToken;
    private ConsoleFormatterOptions _options;

    public EmojiConsoleFormatter(IOptionsMonitor<ConsoleFormatterOptions> options)
        : base("emoji")
    {
        _options = options.CurrentValue;
        _optionsReloadToken = options.OnChange(o => _options = o);
    }

    public override void Write<TState>(
        in LogEntry<TState> logEntry,
        IExternalScopeProvider? scopeProvider,
        TextWriter textWriter)
    {
        // 全新数据库首启时，EF 迁移探测查询 __EFMigrationsHistory 会触发 42P01，
        // 命令层以 Error（EventId 20102 "Failed executing DbCommand"）记录——正常
        // 首启流程噪音（EF 内部已捕获并按"尚无迁移"处理，迁移门禁显式兜底），
        // 此处抑制；其余 Error（真实查询失败）照常输出。
        if (logEntry.Category == "Microsoft.EntityFrameworkCore.Database.Command"
            && logEntry.EventId.Id == 20102)
            return;

        var message = logEntry.Formatter?.Invoke(logEntry.State, logEntry.Exception);
        if (message is null && logEntry.Exception is not null)
            message = logEntry.Exception.ToString();
        if (message is null) return;

        // 框架英文日志模板统一翻译为中文（EF Core / ASP.NET Core Hosting 等）
        message = ChineseLogTranslator.Translate(logEntry.Category, message);

        var (emoji, color) = GetEmojiAndColor(logEntry.LogLevel);
        var timestamp = _options.TimestampFormat is not null
            ? DateTimeOffset.Now.ToString(_options.TimestampFormat)
            : null;
        var shortName = ChineseLogTranslator.TranslateCategoryName(GetShortName(logEntry.Category));

        const string reset = "\x1b[0m";

        textWriter.Write(color);
        textWriter.Write(timestamp);
        textWriter.Write("  ");
        textWriter.Write(emoji);
        textWriter.Write("  ");
        textWriter.Write(shortName.PadRight(14));
        textWriter.Write(reset);
        textWriter.Write(' ');
        textWriter.WriteLine(message);

        if (logEntry.Exception is not null && logEntry.Formatter is not null)
        {
            textWriter.Write(color);
            textWriter.Write(timestamp);
            textWriter.Write("  ");
            textWriter.Write(emoji);
            textWriter.Write("  ");
            textWriter.Write(shortName.PadRight(14));
            textWriter.Write(reset);
            textWriter.Write(' ');
            textWriter.WriteLine(logEntry.Exception.ToString());
        }
    }

    public void Dispose() => _optionsReloadToken?.Dispose();

    private static string GetShortName(string category)
    {
        var lastDot = category.LastIndexOf('.');
        return lastDot >= 0 ? category[(lastDot + 1)..] : category;
    }

    private static (string emoji, string color) GetEmojiAndColor(LogLevel level) => level switch
    {
        LogLevel.Trace => ("\U0001F4DD", "\x1b[90m"),
        LogLevel.Debug => ("\U0001F4DD", "\x1b[37m"),
        LogLevel.Information => ("\u2705", "\x1b[92m"),
        LogLevel.Warning => ("\u26A0\uFE0F", "\x1b[93m"),
        LogLevel.Error => ("\u274C", "\x1b[91m"),
        LogLevel.Critical => ("\u2620\uFE0F", "\x1b[35m"),
        _ => ("\u2753", "\x1b[0m")
    };
}
