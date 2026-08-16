using System.Reflection;
using System.Text.Json.Nodes;
using Cocona;
using Tomlyn;
using Tomlyn.Model;

namespace Pylaios.Features.Config;




public sealed class ConfigCommands
{
    private static string EnvironmentName
        => Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT") ?? "Production";

    [Command("validate", Description = "严格校验 TOML 配置文件（--output human 渲染中文诊断）")]
    public int Validate()
    {
        var result = ConfigLoader.Load(CliHelpers.ConfigPath, EnvironmentName);

        if (CliHelpers.OutputFormat == "human")
        {
            if (result.Errors.Count > 0)
            {
                Console.Out.WriteLine(ConfigErrorRenderer.Render(result.Errors, CliHelpers.ConfigPath));
                return 1;
            }
            Console.Out.WriteLine($"配置校验通过（{result.Warnings.Count} 条警告）");
            foreach (var w in result.Warnings)
                Console.Out.WriteLine($"warning: {w}");
            return 0;
        }

        var config = result.Config;
        Console.Out.WriteLine(CliHelpers.SerializeJson(new
        {
            success = result.Errors.Count == 0,
            configPath = CliHelpers.ConfigPath,
            environment = EnvironmentName,
            server = config is null
                ? null
                : new { url = config.Server.Url, frontendUrl = config.Frontend.Url },
            errors = result.Errors,
            warnings = result.Warnings
        }));
        return result.Errors.Count == 0 ? 0 : 1;
    }

    [Command("effective", Description = "输出最终有效配置（[--redact] 脱敏敏感字段）")]
    public int Effective([Option("redact", Description = "敏感字段打码为 ***")] bool redact)
    {
        var result = ConfigLoader.Load(CliHelpers.ConfigPath, EnvironmentName);
        if (result.Errors.Count > 0 || result.Config is null)
        {
            Console.Out.WriteLine(CliHelpers.SerializeJson(new
            {
                success = false,
                errors = result.Errors
            }));
            return 2;
        }

        var json = CliHelpers.SerializeJson(result.Config);
        if (redact)
        {
            var node = JsonNode.Parse(json);
            Redact(node);
            Console.Out.WriteLine(node?.ToJsonString());
        }
        else
        {
            Console.Out.WriteLine(json);
        }
        return 0;
    }

    [Command("export", Description = "导出无秘密的 TOML 配置文件（敏感字段留空，方便社区反馈）")]
    public int Export()
    {
        var result = ConfigLoader.Load(CliHelpers.ConfigPath, EnvironmentName);
        if (result.Errors.Count > 0 || result.Config is null)
        {
            Console.Out.WriteLine(CliHelpers.SerializeJson(new
            {
                success = false,
                errors = result.Errors
            }));
            return 2;
        }

        var table = TomlSerializer.Deserialize<TomlTable>(TomlSerializer.Serialize(result.Config));
        BlankSensitive(table, typeof(MainConfig));
        Console.Out.WriteLine(TomlSerializer.Serialize(table));
        return 0;
    }


    private static void BlankSensitive(TomlTable table, Type type)
    {
        foreach (var key in table.Keys.ToList())
        {
            var prop = type.GetProperty(key, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
            if (prop is null) continue;

            var propType = Nullable.GetUnderlyingType(prop.PropertyType) ?? prop.PropertyType;
            if (prop.GetCustomAttribute<ConfigSensitiveAttribute>() is not null)
            {
                table[key] = "";
                continue;
            }

            if (table[key] is TomlTable sub && propType.IsClass && propType != typeof(string)
                && !typeof(System.Collections.IDictionary).IsAssignableFrom(propType))
            {
                BlankSensitive(sub, propType);
            }
        }
    }


    private static void Redact(JsonNode? node, string prefix = "")
    {
        if (node is not JsonObject obj) return;
        foreach (var (key, value) in obj.ToList())
        {
            var path = prefix.Length > 0 ? prefix + "." + key : key;
            if (value is JsonObject or JsonArray)
            {
                Redact(value, path);
            }
            else if (IsSensitiveProperty(path))
            {
                obj[key] = "***";
            }
        }
    }




    private static bool IsSensitiveProperty(string key)
    {
        var parts = key.Split('.');
        Type? current = typeof(MainConfig);
        foreach (var part in parts)
        {
            if (current is null) return false;
            var prop = current.GetProperty(part, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
            if (prop is null) return false;
            if (prop.GetCustomAttribute<ConfigSensitiveAttribute>() is not null)
                return true;
            current = Nullable.GetUnderlyingType(prop.PropertyType) ?? prop.PropertyType;
            if (current.IsPrimitive || current == typeof(string)) current = null;
        }
        return false;
    }
}
