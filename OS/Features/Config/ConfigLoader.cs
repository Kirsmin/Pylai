using System.Reflection;
using Microsoft.Extensions.Configuration;
using Tomlyn;
using Tomlyn.Model;
using Tomlyn.Parsing;
using Tomlyn.Syntax;

namespace Pylaios.Features.Config;




public sealed record ConfigIssue(string File, string Path, string Code, string Message,
    int? Line = null, int? Col = null, int? Length = null);

public sealed class ConfigLoadResult
{
    public MainConfig? Config { get; set; }
    public List<ConfigIssue> Errors { get; } = [];
    public List<string> Warnings { get; } = [];
}







public static class ConfigLoader
{

    public static ConfigLoadResult Load(string path, string environment)
    {
        var result = new ConfigLoadResult();
        var fileName = Path.GetFileName(path);

        if (!File.Exists(path))
        {
            result.Errors.Add(new ConfigIssue(fileName, "", "E004",
                $"配置文件不存在: {path}"));
            return result;
        }


        var text = File.ReadAllText(path);
        var doc = SyntaxParser.Parse(text, fileName);
        if (doc.HasErrors)
        {
            foreach (var diag in doc.Diagnostics)
            {
                if (diag.Kind != DiagnosticMessageKind.Error) continue;
                result.Errors.Add(new ConfigIssue(fileName, "", "E001",
                    diag.Message, diag.Span.Start.Line + 1, diag.Span.Start.Column + 1,
                    diag.Span.Length > 0 ? diag.Span.Length : null));
            }
            return result;
        }

        var map = new Dictionary<string, (int Line, int Column)>(StringComparer.Ordinal);
        foreach (var kv in doc.KeyValues)
            CollectPath(kv, "", map);
        foreach (var tableSyntax in doc.Tables)
            foreach (var kv in tableSyntax.Items)
                CollectPath(kv, tableSyntax.Name?.ToString().Trim() ?? "", map);


        var table = TomlSerializer.Deserialize<TomlTable>(text)!;
        Walk(table, typeof(MainConfig), "", fileName, map, result);
        if (result.Errors.Count > 0) return result;


        try
        {
            var configuration = new ConfigurationBuilder()
                .AddTomlFile(path)
                .Build();
            var config = new MainConfig();
            ClearCollectionDefaults(config, new HashSet<object>());
            configuration.Bind(config);
            result.Config = config;
        }
        catch (Exception ex)
        {
            var message = ex.Message.Replace('\r', ' ').Replace('\n', ' ');
            if (message.Length > 300) message = message[..300] + " ...";
            result.Errors.Add(new ConfigIssue(fileName, "", "E008", message));
            return result;
        }


        ConfigValidator.ValidateValues(result.Config, environment, result);
        return result;
    }

    private static void ClearCollectionDefaults(object instance, HashSet<object> visited)
    {
        if (instance is null || !visited.Add(instance))
            return;

        var type = instance.GetType();
        foreach (var property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
        {
            if (!property.CanWrite || property.GetIndexParameters().Length > 0)
                continue;

            var propertyType = property.PropertyType;
            var value = property.GetValue(instance);
            if (propertyType.IsArray && propertyType.GetElementType() is { } elementType)
            {
                property.SetValue(instance, Array.CreateInstance(elementType, 0));
                continue;
            }

            if (propertyType.IsGenericType
                && propertyType.GetGenericTypeDefinition() == typeof(List<>)
                && value is System.Collections.IList)
            {
                property.SetValue(instance, Activator.CreateInstance(propertyType));
                continue;
            }

            if (value is not null
                && propertyType.IsClass
                && propertyType != typeof(string)
                && !typeof(System.Collections.IEnumerable).IsAssignableFrom(propertyType))
            {
                ClearCollectionDefaults(value, visited);
            }
        }
    }

    private static void CollectPath(KeyValueSyntax kv, string prefix,
        Dictionary<string, (int Line, int Column)> map)
    {
        var key = kv.Key?.ToString().Trim() ?? "";
        if (key.Length == 0) return;
        var full = prefix.Length > 0 ? prefix + "." + key : key;
        map[full] = (kv.Span.Start.Line + 1, kv.Span.Start.Column + 1);
    }

    private static void Walk(TomlTable table, Type type, string prefix, string fileName,
        Dictionary<string, (int Line, int Column)> map, ConfigLoadResult result)
    {
        foreach (var (key, value) in table)
        {
            var path = prefix.Length > 0 ? prefix + "." + key : key;
            var prop = type.GetProperty(key, BindingFlags.Public | BindingFlags.Instance | BindingFlags.IgnoreCase);
            if (prop is null)
            {
                AddIssue(result, map, path, fileName, "E002", $"配置项 {path} 在当前版本中不存在");
                continue;
            }

            var propType = Nullable.GetUnderlyingType(prop.PropertyType) ?? prop.PropertyType;
            var isCollection = propType.IsArray
                || (propType.IsGenericType && propType.GetGenericTypeDefinition() == typeof(List<>));

            if (value is TomlTable sub)
            {
                if (typeof(System.Collections.IDictionary).IsAssignableFrom(propType))
                {
                    CheckDictionary(sub, propType, path, fileName, map, result);
                }
                else if (propType.IsClass && propType != typeof(string))
                {
                    Walk(sub, propType, path, fileName, map, result);
                }
                else
                {
                    AddTypeMismatch(result, map, path, fileName, JsonTypeName(propType), "object");
                }
                continue;
            }

            if (value is TomlArray arr)
            {
                if (!isCollection)
                {
                    AddTypeMismatch(result, map, path, fileName, JsonTypeName(propType), "array");
                    continue;
                }

                if (arr.Count == 0 && prop.GetCustomAttribute<ConfigNotEmptyAttribute>() is not null)
                {
                    AddIssue(result, map, path, fileName, "E004", $"{path} 不能为空数组");
                    continue;
                }

                var elemType = propType.IsArray
                    ? propType.GetElementType()
                    : propType.GetGenericArguments()[0];
                if (elemType is not null && !typeof(System.Collections.IDictionary).IsAssignableFrom(elemType))
                {
                    foreach (var item in arr)
                    {
                        if (!TypeMatches(item, elemType, out var expected, out var found))
                            AddTypeMismatch(result, map, path, fileName, $"{expected} 数组", found);
                    }
                }
                continue;
            }

            if (propType.IsClass && propType != typeof(string)
                && !typeof(System.Collections.IDictionary).IsAssignableFrom(propType))
            {
                AddTypeMismatch(result, map, path, fileName, "object", FoundName(value));
                continue;
            }

            if (!TypeMatches(value, propType, out var exp, out var fnd))
            {
                AddTypeMismatch(result, map, path, fileName, exp, fnd);
                continue;
            }

            CheckConstraints(prop, value, path, fileName, map, result);
        }
    }

    private static void CheckDictionary(TomlTable sub, Type dictType, string path, string fileName,
        Dictionary<string, (int Line, int Column)> map, ConfigLoadResult result)
    {
        var args = dictType.GetGenericArguments();
        if (args.Length != 2) return;
        foreach (var (k, v) in sub)
        {
            if (!TypeMatches(v, args[1], out var expected, out var found))
                AddTypeMismatch(result, map, path + "." + k, fileName, expected, found);
        }
    }

    private static void CheckConstraints(PropertyInfo prop, object value, string path, string fileName,
        Dictionary<string, (int Line, int Column)> map, ConfigLoadResult result)
    {
        if (prop.GetCustomAttribute<ConfigRequiredAttribute>() is not null
            && prop.PropertyType == typeof(string) && value is string s
            && string.IsNullOrWhiteSpace(s))
        {
            AddIssue(result, map, path, fileName, "E004", $"{path} 不能为空");
        }

        if (prop.GetCustomAttribute<ConfigRangeAttribute>() is { } range
            && value is long n
            && (n < range.Min || n > range.Max))
        {
            AddIssue(result, map, path, fileName, "E005",
                $"值 {n} 超出范围 [{range.Min}, {range.Max}]");
        }
    }

    private static void AddIssue(ConfigLoadResult result,
        Dictionary<string, (int Line, int Column)> map, string path, string file, string code, string message)
    {
        var (line, col) = map.TryGetValue(path, out var m)
            ? ((int?)m.Line, (int?)m.Column)
            : ((int?)null, (int?)null);
        result.Errors.Add(new ConfigIssue(file, path, code, message, line, col));
    }

    private static void AddTypeMismatch(ConfigLoadResult result,
        Dictionary<string, (int Line, int Column)> map, string path, string fileName,
        string expected, string found)
    {
        AddIssue(result, map, path, fileName, "E003", $"应为 {expected}，实际为 {found}");
    }

    private static bool TypeMatches(object? value, Type type, out string expected, out string found)
    {
        expected = JsonTypeName(type);
        found = FoundName(value);

        return value is not null && type switch
        {
            var t when t == typeof(string) => value is string,
            var t when t == typeof(int) || t == typeof(long) => value is long,
            var t when t == typeof(bool) => value is bool,
            var t when t == typeof(double) || t == typeof(float) => value is double or long,
            var t when t.IsArray || (t.IsGenericType && t.GetGenericTypeDefinition() == typeof(List<>))
                => value is TomlArray,
            _ => false
        };
    }

    private static string FoundName(object? value) => value switch
    {
        null => "null",
        string => "string",
        long => "integer",
        bool => "boolean",
        double or float => "number",
        DateTimeOffset or DateTime => "datetime",
        TomlArray => "array",
        TomlTable => "object",
        _ => value.GetType().Name
    };


    public static string JsonTypeName(Type type)
    {
        type = Nullable.GetUnderlyingType(type) ?? type;
        return type switch
        {
            var t when t == typeof(string) => "string",
            var t when t == typeof(bool) => "boolean",
            var t when t == typeof(int) || t == typeof(long) => "integer",
            var t when t == typeof(double) || t == typeof(float) => "number",
            var t when t == typeof(DateTimeOffset) || t == typeof(DateTime) => "datetime",
            var t when t.IsArray || (t.IsGenericType && t.GetGenericTypeDefinition() == typeof(List<>)) => "array",
            _ => "object"
        };
    }
}
