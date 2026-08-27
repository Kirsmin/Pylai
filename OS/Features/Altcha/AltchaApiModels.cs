using System.Text.Json.Serialization;

namespace Pylaios.Features.Altcha;

public class AltchaChallenge
{
    public string Algorithm { get; set; } = "SHA-256";
    public string Challenge { get; set; } = string.Empty;
    public string Salt { get; set; } = string.Empty;
    public string Signature { get; set; } = string.Empty;
    public int MaxNumber { get; set; }
}

public class AltchaPayload
{
    public string Algorithm { get; set; } = string.Empty;
    public string Challenge { get; set; } = string.Empty;
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public long Number { get; set; }
    public string Salt { get; set; } = string.Empty;
    public string Signature { get; set; } = string.Empty;
}
