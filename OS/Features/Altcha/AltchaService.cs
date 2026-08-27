using System.Security.Cryptography;
using System.Text;

namespace Pylaios.Features.Altcha;

public interface IAltchaService
{
    AltchaChallenge GenerateChallenge();
    bool VerifyPayload(AltchaPayload payload, out string? error);
}

public class AltchaService : IAltchaService
{
    private readonly AltchaOptions _opts;
    private readonly ILogger<AltchaService> _logger;

    public AltchaService(MainConfig config, ILogger<AltchaService> logger)
    {
        _opts = config.Altcha;
        _logger = logger;

        if (_opts.Enabled && string.IsNullOrEmpty(_opts.SecretKey))
        {
            _logger.LogWarning("AltCHA 已启用但 SecretKey 为空，验证将始终失败。请配置 PYLAI_ALTCHA_SECRET 环境变量或 [Altcha].SecretKey。");
        }
    }

    public AltchaChallenge GenerateChallenge()
    {
        var saltBytes = RandomNumberGenerator.GetBytes(16);
        var salt = Convert.ToBase64String(saltBytes);
        var number = Random.Shared.Next(1, _opts.MaxNumber);
        var expiry = DateTimeOffset.UtcNow.AddSeconds(_opts.ExpirySeconds).ToUnixTimeSeconds();

        var challenge = Hash(salt + number);
        var signature = SignWithExpiry(challenge, expiry);

        return new AltchaChallenge
        {
            Algorithm = "SHA-256",
            Challenge = challenge,
            Salt = salt,
            Signature = signature,
            MaxNumber = _opts.MaxNumber
        };
    }

    public bool VerifyPayload(AltchaPayload p, out string? error)
    {
        error = null;

        if (p is null)
        {
            error = "missing_payload";
            return false;
        }

        if (!TryParseExpiry(p.Signature, out var expiry)
            || DateTimeOffset.UtcNow.ToUnixTimeSeconds() > expiry)
        {
            error = "expired";
            return false;
        }

        if (!VerifySignatureWithExpiry(p.Challenge, p.Signature))
        {
            error = "invalid_signature";
            return false;
        }

        var recomputed = Hash(p.Salt + p.Number);
        if (!recomputed.Equals(p.Challenge, StringComparison.OrdinalIgnoreCase))
        {
            error = "invalid_pow";
            return false;
        }

        return true;
    }

    private static bool TryParseExpiry(string signature, out long expiry)
    {
        expiry = 0;
        if (string.IsNullOrEmpty(signature)) return false;
        var idx = signature.IndexOf(':');
        if (idx < 0) return false;
        var expiryStr = signature[..idx];
        return long.TryParse(expiryStr, out expiry);
    }

    private string SignWithExpiry(string challenge, long expiry)
    {
        var payload = $"{challenge}:{expiry}";
        var hmac = HmacSign(payload);
        return $"{expiry}:{hmac}";
    }

    private bool VerifySignatureWithExpiry(string challenge, string signature)
    {
        if (string.IsNullOrEmpty(_opts.SecretKey)) return false;
        if (!TryParseExpiry(signature, out var expiry)) return false;
        var expected = SignWithExpiry(challenge, expiry);
        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(expected),
            Encoding.UTF8.GetBytes(signature));
    }

    private string Hash(string input)
    {
        using var sha = SHA256.Create();
        var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    private string HmacSign(string input)
    {
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(_opts.SecretKey));
        var bytes = hmac.ComputeHash(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    private bool HmacVerify(string input, string signature)
    {
        if (string.IsNullOrEmpty(_opts.SecretKey)) return false;
        var expected = HmacSign(input);
        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(expected),
            Encoding.UTF8.GetBytes(signature));
    }
}
