using System.Security.Cryptography;
using System.Text;
using System.Xml.Linq;
using Microsoft.AspNetCore.DataProtection.XmlEncryption;

namespace Pylaios.Shared;

/// <summary>
/// Encrypts ASP.NET Core DataProtection key descriptors with an independent 256-bit AES-GCM KEK.
/// The KEK is loaded from PYLAI_DP_KEK_FILE and may be raw 32 bytes, 64-char hex, or Base64.
/// </summary>
public sealed class AesGcmXmlEncryptor : IXmlEncryptor, IXmlDecryptor
{
    public const string KeyFileEnvironmentVariable = "PYLAI_DP_KEK_FILE";
    private const int NonceSize = 12;
    private const int TagSize = 16;
    private static readonly byte[] AssociatedData = Encoding.UTF8.GetBytes("Pylaios.DataProtection.KeyRing.v1");
    private readonly byte[] _key;

    public AesGcmXmlEncryptor()
    {
        _key = LoadKeyFromEnvironment();
    }

    public AesGcmXmlEncryptor(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        _key = LoadKey(path);
    }

    public EncryptedXmlInfo Encrypt(XElement plaintextElement)
    {
        ArgumentNullException.ThrowIfNull(plaintextElement);

        var plaintext = Encoding.UTF8.GetBytes(plaintextElement.ToString(SaveOptions.DisableFormatting));
        var nonce = RandomNumberGenerator.GetBytes(NonceSize);
        var ciphertext = new byte[plaintext.Length];
        var tag = new byte[TagSize];
        try
        {
            using var aes = new AesGcm(_key, TagSize);
            aes.Encrypt(nonce, plaintext, ciphertext, tag, AssociatedData);

            var encrypted = new XElement("pylai-aes-gcm",
                new XAttribute("version", "1"),
                new XElement("nonce", Convert.ToBase64String(nonce)),
                new XElement("ciphertext", Convert.ToBase64String(ciphertext)),
                new XElement("tag", Convert.ToBase64String(tag)));
            return new EncryptedXmlInfo(encrypted, typeof(AesGcmXmlEncryptor));
        }
        finally
        {
            CryptographicOperations.ZeroMemory(plaintext);
        }
    }

    public XElement Decrypt(XElement encryptedElement)
    {
        ArgumentNullException.ThrowIfNull(encryptedElement);
        if (!string.Equals(encryptedElement.Name.LocalName, "pylai-aes-gcm", StringComparison.Ordinal)
            || !string.Equals((string?)encryptedElement.Attribute("version"), "1", StringComparison.Ordinal))
        {
            throw new CryptographicException("Unsupported DataProtection key envelope.");
        }

        var nonce = ReadBase64(encryptedElement, "nonce", NonceSize);
        var ciphertext = ReadBase64(encryptedElement, "ciphertext", null);
        var tag = ReadBase64(encryptedElement, "tag", TagSize);
        var plaintext = new byte[ciphertext.Length];
        try
        {
            using var aes = new AesGcm(_key, TagSize);
            aes.Decrypt(nonce, ciphertext, tag, plaintext, AssociatedData);
            return XElement.Parse(Encoding.UTF8.GetString(plaintext), LoadOptions.PreserveWhitespace);
        }
        catch (FormatException ex)
        {
            throw new CryptographicException("Invalid DataProtection key envelope.", ex);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(plaintext);
        }
    }

    private static byte[] ReadBase64(XElement parent, string name, int? expectedLength)
    {
        var text = parent.Element(name)?.Value
            ?? throw new CryptographicException($"DataProtection key envelope is missing '{name}'.");
        byte[] value;
        try
        {
            value = Convert.FromBase64String(text);
        }
        catch (FormatException ex)
        {
            throw new CryptographicException($"DataProtection key envelope field '{name}' is invalid.", ex);
        }

        if (expectedLength is not null && value.Length != expectedLength.Value)
            throw new CryptographicException($"DataProtection key envelope field '{name}' has an invalid length.");
        return value;
    }

    private static byte[] LoadKeyFromEnvironment()
    {
        var path = Environment.GetEnvironmentVariable(KeyFileEnvironmentVariable);
        if (string.IsNullOrWhiteSpace(path))
            throw new InvalidOperationException($"{KeyFileEnvironmentVariable} is required when the DataProtection key ring is persisted.");

        return LoadKey(path);
    }

    private static byte[] LoadKey(string path)
    {
        var raw = File.ReadAllBytes(path);
        if (raw.Length == 32)
            return raw;

        var text = Encoding.ASCII.GetString(raw).Trim();
        CryptographicOperations.ZeroMemory(raw);

        try
        {
            if (text.Length == 64)
            {
                var hex = Convert.FromHexString(text);
                if (hex.Length == 32) return hex;
            }

            var b64 = Convert.FromBase64String(text);
            if (b64.Length == 32) return b64;
            CryptographicOperations.ZeroMemory(b64);
        }
        catch (FormatException)
        {
            // Normalized below to one startup error that does not reveal secret material.
        }

        throw new InvalidOperationException($"{KeyFileEnvironmentVariable} must point to a 256-bit key (32 raw bytes, 64-char hex, or Base64).");
    }
}
