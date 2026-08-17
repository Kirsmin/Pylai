using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace Pylaios.Shared;

public static partial class SensitiveDataRedactor
{
    private static readonly HashSet<string> SensitiveNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "password", "passwordhash", "passcode", "token", "accesstoken", "refreshtoken",
        "authorization", "secret", "clientsecret", "invitecode", "verificationcode",
        "sessiontoken", "code", "providerkey", "credential", "pfxpassword", "kek"
    };

    [GeneratedRegex(
        @"(?i)\b(passwordhash|password|passcode|accesstoken|refreshtoken|clientsecret|verificationcode|sessiontoken|providerkey|invitecode|authorization|token|secret|kek)\b\s*([:=])\s*(""[^""]*""|'[^']*'|[^\s,;}]+)",
        RegexOptions.CultureInvariant)]
    private static partial Regex SensitiveValueRegex();

    public static string? Redact(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return value;

        var trimmed = value.TrimStart();
        if (trimmed.StartsWith('{') || trimmed.StartsWith('['))
        {
            try
            {
                var node = JsonNode.Parse(trimmed);
                RedactNode(node);
                return node?.ToJsonString() ?? value;
            }
            catch (JsonException)
            {
                // 非结构化 JSON 继续走文本规则。
            }
        }

        return SensitiveValueRegex().Replace(value, "$1$2[REDACTED]");
    }

    private static void RedactNode(JsonNode? node)
    {
        if (node is JsonObject obj)
        {
            var names = obj.Select(x => x.Key).ToArray();
            foreach (var name in names)
            {
                if (SensitiveNames.Contains(name.Replace("_", "", StringComparison.Ordinal)))
                {
                    obj[name] = "[REDACTED]";
                    continue;
                }

                RedactNode(obj[name]);
            }
            return;
        }

        if (node is JsonArray array)
        {
            foreach (var item in array)
                RedactNode(item);
        }
    }
}
