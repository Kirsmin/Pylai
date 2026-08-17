using System.Data;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using Npgsql;
using OpenIddict.Server;

namespace Pylaios.Features.OAuth;

public sealed class SigningKeyStatus
{
    public int Id { get; init; }
    public string Thumbprint { get; init; } = string.Empty;
    public DateTimeOffset CreatedAt { get; init; }
    public DateTimeOffset ExpiresAt { get; init; }
    public bool IsActive { get; init; }
    public bool IsRevoked { get; init; }
    public bool UsableNow { get; init; }
}

public static class SigningKeyService
{
    public static void ConfigureKeys(
        OpenIddictServerBuilder options,
        MainConfig config,
        IWebHostEnvironment env)
    {
        if (env.IsDevelopment())
        {
            options.AddDevelopmentSigningCertificate();
            return;
        }

        var configuredPath = config.OpenIddict.Certificates.Signing.Path;
        if (!string.IsNullOrWhiteSpace(configuredPath))
        {
            options.AddSigningCertificate(
                CertificateLoader.LoadPkcs12(configuredPath, config.OpenIddict.Certificates.Signing.Password));
            return;
        }

        var protector = SigningKeyProtector.Load(config);
        using var db = CreateTempDbContext(config.Database.ConnectionString);
        var now = DateTimeOffset.UtcNow;
        var certificates = LoadUsableCertificates(db, protector, now);

        if (certificates.Count == 0)
        {
            throw new InvalidOperationException(
                "数据库中没有可用的加密签名密钥，拒绝启动。请先执行: Pylaios key reencrypt 或 key rotate --if-empty");
        }

        foreach (var certificate in certificates)
            options.AddSigningCertificate(certificate);
    }

    public static async Task<List<SigningKeyStatus>> GetStatusAsync(ApplicationDbContext db)
    {
        var now = DateTimeOffset.UtcNow;
        return await db.SigningKeys
            .OrderByDescending(k => k.CreatedAt)
            .Select(k => new SigningKeyStatus
            {
                Id = k.Id,
                Thumbprint = k.Thumbprint,
                CreatedAt = k.CreatedAt,
                ExpiresAt = k.ExpiresAt,
                IsActive = k.IsActive,
                IsRevoked = k.IsRevoked,
                UsableNow = k.IsActive && !k.IsRevoked && k.ExpiresAt > now
            })
            .ToListAsync();
    }

    public static async Task<bool> RotateIfDueAsync(
        ApplicationDbContext db, MainConfig config, int rotationDays, int validationDays)
    {
        var protector = SigningKeyProtector.Load(config);
        var now = DateTimeOffset.UtcNow;
        var newest = await db.SigningKeys
            .Where(k => k.IsActive && !k.IsRevoked)
            .OrderByDescending(k => k.CreatedAt)
            .FirstOrDefaultAsync();

        if (newest is not null && (now - newest.CreatedAt).TotalDays < rotationDays)
            return false;

        await using var tx = await db.Database.BeginTransactionAsync();
        var currentNewest = await db.SigningKeys
            .Where(k => k.IsActive && !k.IsRevoked)
            .OrderByDescending(k => k.CreatedAt)
            .FirstOrDefaultAsync();

        if (currentNewest is not null && (now - currentNewest.CreatedAt).TotalDays < rotationDays)
            return false;

        var certificate = GenerateSelfSignedCertificate();
        var encrypted = protector.Protect(certificate, certificate.Thumbprint!);
        db.SigningKeys.Add(new SigningKey
        {
            Thumbprint = certificate.Thumbprint!,
            CreatedAt = now,
            ExpiresAt = now.AddDays(rotationDays + validationDays),
            IsActive = true,
            PublicCertificateData = certificate.Export(X509ContentType.Cert),
            EncryptedCertificateData = encrypted.Ciphertext,
            EncryptionNonce = encrypted.Nonce,
            EncryptionTag = encrypted.Tag
        });

        var validationCutoff = now.AddDays(-validationDays);
        var expired = await db.SigningKeys
            .Where(k => k.CreatedAt < validationCutoff && k.IsActive && !k.IsRevoked)
            .ToListAsync();
        foreach (var key in expired)
            key.IsActive = false;

        await db.SaveChangesAsync();
        await tx.CommitAsync();
        return true;
    }

    public static async Task<SigningKeyMigrationResult> ReencryptLegacyAsync(ApplicationDbContext db, MainConfig config)
    {
        var protector = SigningKeyProtector.Load(config);
        var connection = db.Database.GetDbConnection();
        if (connection.State != ConnectionState.Open)
            await connection.OpenAsync();

        var legacy = new List<(int Id, string Thumbprint, byte[] Pfx)>();
        await using (var read = connection.CreateCommand())
        {
            read.CommandText = "SELECT \"Id\", \"Thumbprint\", \"CertificateData\" FROM \"SigningKeys\"";
            try
            {
                await using var reader = await read.ExecuteReaderAsync();
                while (await reader.ReadAsync())
                {
                    if (!reader.IsDBNull(2))
                        legacy.Add((reader.GetInt32(0), reader.GetString(1), (byte[])reader.GetValue(2)));
                }
            }
            catch (PostgresException ex) when (ex.SqlState == "42703")
            {
                return new SigningKeyMigrationResult(0, true);
            }
        }

        await using var tx = await db.Database.BeginTransactionAsync();
        foreach (var item in legacy)
        {
            using var certificate = X509CertificateLoader.LoadPkcs12(
                item.Pfx, null, X509KeyStorageFlags.Exportable | X509KeyStorageFlags.EphemeralKeySet);
            var encrypted = protector.Protect(certificate, item.Thumbprint);
            await using var update = connection.CreateCommand();
            update.Transaction = tx.GetDbTransaction();
            update.CommandText = "UPDATE \"SigningKeys\" SET \"PublicCertificateData\"=@public, \"EncryptedCertificateData\"=@cipher, \"EncryptionNonce\"=@nonce, \"EncryptionTag\"=@tag WHERE \"Id\"=@id";
            AddParameter(update, "public", certificate.Export(X509ContentType.Cert));
            AddParameter(update, "cipher", encrypted.Ciphertext);
            AddParameter(update, "nonce", encrypted.Nonce);
            AddParameter(update, "tag", encrypted.Tag);
            AddParameter(update, "id", item.Id);
            await update.ExecuteNonQueryAsync();
        }

        await db.Database.ExecuteSqlRawAsync("ALTER TABLE \"SigningKeys\" DROP COLUMN IF EXISTS \"CertificateData\"");
        await tx.CommitAsync();
        return new SigningKeyMigrationResult(legacy.Count, false);
    }

    private static List<X509Certificate2> LoadUsableCertificates(
        ApplicationDbContext db, SigningKeyProtector protector, DateTimeOffset now)
    {
        var certificates = new List<X509Certificate2>();
        var keys = db.SigningKeys
            .AsNoTracking()
            .Where(k => k.IsActive && !k.IsRevoked && k.ExpiresAt > now)
            .OrderByDescending(k => k.CreatedAt)
            .ToList();

        foreach (var key in keys)
        {
            if (key.EncryptedCertificateData is null
                || key.EncryptionNonce is null
                || key.EncryptionTag is null)
                throw new InvalidOperationException($"SigningKey {key.Thumbprint} 仍为明文/未迁移格式，拒绝启动。");

            var pfx = protector.Unprotect(key.EncryptedCertificateData, key.EncryptionNonce, key.EncryptionTag, key.Thumbprint);
            certificates.Add(X509CertificateLoader.LoadPkcs12(
                pfx, null, X509KeyStorageFlags.EphemeralKeySet));
        }

        return certificates;
    }

    private static X509Certificate2 GenerateSelfSignedCertificate()
    {
        using var rsa = RSA.Create(2048);
        var req = new CertificateRequest(
            "CN=Pylaios Signing Key", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        req.CertificateExtensions.Add(new X509KeyUsageExtension(
            X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment, critical: true));
        return req.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(365 * 10));
    }

    private static ApplicationDbContext CreateTempDbContext(string connectionString)
    {
        var options = new DbContextOptionsBuilder<ApplicationDbContext>().UseNpgsql(connectionString).Options;
        return new ApplicationDbContext(options);
    }

    private static void AddParameter(System.Data.Common.DbCommand command, string name, object value)
    {
        var parameter = command.CreateParameter();
        parameter.ParameterName = name;
        parameter.Value = value;
        command.Parameters.Add(parameter);
    }
}

public sealed record SigningKeyMigrationResult(int Migrated, bool AlreadyMigrated);

public sealed class SigningKeyProtector
{
    private readonly byte[] _key;

    private SigningKeyProtector(byte[] key)
    {
        _key = key;
    }

    public static SigningKeyProtector Load(MainConfig config)
    {
        var path = config.OpenIddict.SigningKeyEncryption.KeyFile;
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            throw new InvalidOperationException("生产环境必须配置数据库边界之外的签名 KEK 文件。");

        var raw = File.ReadAllBytes(path);
        var text = Encoding.UTF8.GetString(raw).Trim();
        if (text.Length == 64 && text.All(Uri.IsHexDigit))
            raw = Convert.FromHexString(text);
        else
        {
            try
            {
                var decoded = Convert.FromBase64String(text);
                if (decoded.Length == 32) raw = decoded;
            }
            catch
            {
            }
        }

        if (raw.Length != 32)
            throw new InvalidOperationException("签名 KEK 必须是 32 字节随机值。");
        return new SigningKeyProtector(raw);
    }

    public (byte[] Ciphertext, byte[] Nonce, byte[] Tag) Protect(X509Certificate2 certificate, string kid)
    {
        var plaintext = certificate.Export(X509ContentType.Pkcs12);
        var nonce = RandomNumberGenerator.GetBytes(12);
        var ciphertext = new byte[plaintext.Length];
        var tag = new byte[16];
        using var aes = new AesGcm(_key, tag.Length);
        aes.Encrypt(nonce, plaintext, ciphertext, tag, Encoding.UTF8.GetBytes(kid));
        return (ciphertext, nonce, tag);
    }

    public byte[] Unprotect(byte[] ciphertext, byte[] nonce, byte[] tag, string kid)
    {
        var plaintext = new byte[ciphertext.Length];
        using var aes = new AesGcm(_key, tag.Length);
        aes.Decrypt(nonce, ciphertext, tag, plaintext, Encoding.UTF8.GetBytes(kid));
        return plaintext;
    }
}
