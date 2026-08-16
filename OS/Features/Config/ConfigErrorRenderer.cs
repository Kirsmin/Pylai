using System.Text;

namespace Pylaios.Features.Config;





public static class ConfigErrorRenderer
{
    private static readonly Dictionary<string, string> Titles = new()
    {
        ["E001"] = "TOML 解析失败",
        ["E002"] = "未知配置项",
        ["E003"] = "类型不匹配",
        ["E004"] = "必填项缺失",
        ["E005"] = "数值越界",
        ["E006"] = "URL 校验失败",
        ["E007"] = "证书校验失败",
        ["E008"] = "配置绑定失败",
    };

    private static readonly Dictionary<string, string> Helps = new()
    {
        ["E001"] = "检查 TOML 语法：键必须以字母、数字或下划线开头；字符串需加引号；数组元素需逗号分隔",
        ["E002"] = "检查拼写是否错误；该配置项在当前版本中不存在，请参照 pylai.example.toml",
        ["E003"] = "请将该配置项的值改为提示中的类型（string/integer/boolean/array/object）",
        ["E004"] = "该配置项为必填项，不能为空",
        ["E005"] = "请将值调整到提示的允许范围内",
        ["E006"] = "必须是合法 URL（形如 http(s)://host[:port][/path]）",
        ["E007"] = "证书文件路径不存在或内容不合法（需 PEM/PFX 格式）",
        ["E008"] = "配置结构绑定出错，请检查是否存在重复或不兼容的配置段",
    };


    public static string Render(IReadOnlyList<ConfigIssue> errors, string configPath)
    {
        var sb = new StringBuilder();
        var fileCache = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase);
        var index = 0;
        foreach (var issue in errors)
        {
            if (index++ > 0) sb.AppendLine();
            sb.AppendLine($"error[{issue.Code}]: {Titles.GetValueOrDefault(issue.Code, issue.Code)} — {issue.Message}");

            if (issue.Line is int line)
            {
                var lines = LinesFor(issue.File, configPath, fileCache);
                var column = Math.Max(1, issue.Col ?? 1);
                sb.AppendLine($"  --> {issue.File}:{line}:{column}");
                sb.AppendLine("   |");

                var start = Math.Max(0, line - 2);
                var end = Math.Min(lines.Length, line);
                for (var i = start; i < end; i++)
                    sb.AppendLine($"{(i + 1).ToString().PadLeft(3)} | {lines[i]}");

                if (line - 1 < lines.Length)
                {
                    var lineText = lines[line - 1];
                    var caretLen = Math.Max(1, Math.Min(issue.Length ?? 1, lineText.Length - column + 1));
                    sb.AppendLine($"   | {new string(' ', column - 1)}{new string('^', caretLen)} {issue.Message}");
                }
                else
                {
                    sb.AppendLine($"   | {new string(' ', column - 1)}^ {issue.Message}");
                }
                sb.AppendLine("   |");
            }
            else
            {
                sb.AppendLine($"   = {issue.Message}");
            }

            sb.AppendLine($"   = help: {Helps.GetValueOrDefault(issue.Code, "请检查配置内容")}");
        }
        return sb.ToString();
    }

    private static string[] LinesFor(string fileName, string configPath,
        Dictionary<string, string[]> cache)
    {
        if (string.IsNullOrEmpty(fileName)) return [];
        var path = fileName.Equals(Path.GetFileName(configPath), StringComparison.OrdinalIgnoreCase)
            ? configPath
            : Path.Combine(Path.GetDirectoryName(configPath) ?? ".", fileName);
        if (cache.TryGetValue(path, out var cached)) return cached;
        string[] lines = [];
        if (File.Exists(path))
        {
            try
            {
                lines = File.ReadAllLines(path);
            }
            catch (IOException)
            {
                lines = [];
            }
        }
        cache[path] = lines;
        return lines;
    }
}
