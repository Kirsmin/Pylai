using Microsoft.Extensions.Configuration;
using Tomlyn;
using Tomlyn.Model;

namespace Pylaios.Features.Config;





public sealed class TomlConfigurationSource : IConfigurationSource
{
    public required string Path { get; init; }

    public IConfigurationProvider Build(IConfigurationBuilder builder)
        => new TomlConfigurationProvider(this);
}

public sealed class TomlConfigurationProvider : ConfigurationProvider
{
    private readonly string _path;

    public TomlConfigurationProvider(TomlConfigurationSource source)
    {
        _path = source.Path;
    }

    public override void Load()
    {
        Data = new Dictionary<string, string?>();
        if (!File.Exists(_path))
        {
            throw new FileNotFoundException($"配置文件不存在: {_path}");
        }

        var table = TomlSerializer.Deserialize<TomlTable>(File.ReadAllText(_path))
            ?? throw new InvalidOperationException($"配置文件解析失败: {_path}");
        Flatten("", table);
    }

    private void Flatten(string prefix, TomlTable table)
    {
        foreach (var (key, value) in table)
        {
            var fullKey = prefix.Length > 0 ? prefix + ":" + key : key;
            switch (value)
            {
                case TomlTable sub:
                    Flatten(fullKey, sub);
                    break;
                case TomlArray array:
                    for (var i = 0; i < array.Count; i++)
                        Data[$"{fullKey}:{i}"] = ScalarToString(array[i]);
                    break;
                default:
                    Data[fullKey] = ScalarToString(value);
                    break;
            }
        }
    }

    private static string ScalarToString(object? value) => value switch
    {
        null => "",
        string s => s,
        bool b => b ? "true" : "false",
        long l => l.ToString(System.Globalization.CultureInfo.InvariantCulture),
        double d => d.ToString(System.Globalization.CultureInfo.InvariantCulture),
        _ => value.ToString() ?? ""
    };
}

public static class TomlConfigurationExtensions
{

    public static IConfigurationBuilder AddTomlFile(this IConfigurationBuilder builder, string path)
    {
        var fullPath = Path.GetFullPath(path);
        return builder.Add(new TomlConfigurationSource { Path = fullPath });
    }
}
