using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using Microsoft.EntityFrameworkCore;
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

public class SigningKeyService
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

        using var db = CreateTempDbContext(config.Database.ConnectionString);
        var now = DateTimeOffset.UtcNow;
        var certificates = LoadUsableCertificates(db, now);

        if (certificates.Count == 0)
        {
            throw new InvalidOperationException(
                "数据库中没有可用的签名密钥，拒绝启动。请先执行: Pylaios key rotate --if-empty");
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
        ApplicationDbContext db, int rotationDays, int validationDays)
    {
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

        db.SigningKeys.Add(new SigningKey
        {
            Thumbprint = certificate.Thumbprint,
            CreatedAt = now,
            ExpiresAt = now.AddDays(rotationDays + validationDays),
            IsActive = true,
            CertificateData = certificate.Export(X509ContentType.Pkcs12)
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

    private static List<X509Certificate2> LoadUsableCertificates(ApplicationDbContext db, DateTimeOffset now)
    {
        var certificates = new List<X509Certificate2>();
        var keys = db.SigningKeys
            .AsEnumerable()
            .Where(k => k.IsActive && !k.IsRevoked && k.ExpiresAt > now)
            .OrderByDescending(k => k.CreatedAt)
            .ToList();

        foreach (var key in keys)
        {
            try
            {
                certificates.Add(X509CertificateLoader.LoadPkcs12(
                    key.CertificateData, null!, X509KeyStorageFlags.Exportable));
            }
            catch
            {
                // 跳过损坏的密钥记录，不静默降级。
            }
        }

        return certificates;
    }

    private static X509Certificate2 GenerateSelfSignedCertificate()
    {
        using var rsa = RSA.Create(2048);

        var req = new CertificateRequest(
            "CN=Pylaios Signing Key",
            rsa,
            HashAlgorithmName.SHA256,
            RSASignaturePadding.Pkcs1);

        req.CertificateExtensions.Add(
            new X509KeyUsageExtension(
                X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment,
                critical: true));

        return req.CreateSelfSigned(
            DateTimeOffset.UtcNow.AddDays(-1),
            DateTimeOffset.UtcNow.AddDays(365 * 10));
    }

    private static ApplicationDbContext CreateTempDbContext(string connectionString)
    {
        var options = new DbContextOptionsBuilder<ApplicationDbContext>()
            .UseNpgsql(connectionString)
            .Options;

        return new ApplicationDbContext(options);
    }
}
