namespace Pylaios.Features.Altcha;

[ConfigFile("pylai.toml")]
public class AltchaOptions
{
    public bool Enabled { get; set; } = false;

    [ConfigSensitive]
    [ConfigDescription("AltCHA HMAC 密钥，建议 32+ 字节随机串；生产环境可通过环境变量 PYLAI_ALTCHA_SECRET 覆盖")]
    public string SecretKey { get; set; } = "";

    [ConfigRange(1000, 10_000_000)]
    [ConfigDescription("PoW 难度上限（越大计算越久，建议 50万~200万）")]
    public int MaxNumber { get; set; } = 500_000;

    [ConfigRange(30, 3600)]
    [ConfigDescription("Challenge 有效期（秒）")]
    public int ExpirySeconds { get; set; } = 300;
}
