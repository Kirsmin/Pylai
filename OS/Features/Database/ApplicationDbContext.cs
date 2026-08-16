using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using OpenIddict.EntityFrameworkCore.Models;

namespace Pylaios.Features.Database;

public class ApplicationDbContext : DbContext
{
    public DbSet<User> Users => Set<User>();
    public DbSet<UserLogin> UserLogins => Set<UserLogin>();
    public DbSet<AuditLog> AuditLogs => Set<AuditLog>();
    public DbSet<SigningKey> SigningKeys => Set<SigningKey>();
    public DbSet<InviteCodeFailure> InviteCodeFailures => Set<InviteCodeFailure>();
    public DbSet<LoginFailure> LoginFailures => Set<LoginFailure>();
    public DbSet<IpBanAudit> IpBanAudits => Set<IpBanAudit>();
    public DbSet<UserToken> UserTokens => Set<UserToken>();
    public DbSet<UserTokenUsage> UserTokenUsages => Set<UserTokenUsage>();
    public DbSet<ConfirmationFailure> ConfirmationFailures => Set<ConfirmationFailure>();
    public DbSet<UserSession> UserSessions => Set<UserSession>();
    public DbSet<AdminAuthFailure> AdminAuthFailures => Set<AdminAuthFailure>();
    public DbSet<EmailVerificationBlock> EmailVerificationBlocks => Set<EmailVerificationBlock>();
    public DbSet<OAuthClientMetadata> OAuthClientMetadata => Set<OAuthClientMetadata>();
    public DbSet<InviteCode> InviteCodes => Set<InviteCode>();
    public DbSet<ConsentAuditEvent> ConsentAuditEvents => Set<ConsentAuditEvent>();

    public ApplicationDbContext(DbContextOptions<ApplicationDbContext> options)
        : base(options)
    {
    }

    public async Task<int> RevokeAllSessionsAsync(Guid uid)
    {
        var now = DateTimeOffset.UtcNow;
        return await UserSessions
            .Where(s => s.UserUid == uid && s.RevokedAt == null && s.ExpiresAt > now)
            .ExecuteUpdateAsync(setters => setters.SetProperty(s => s.RevokedAt, now));
    }

    protected override void OnModelCreating(ModelBuilder builder)
    {
        base.OnModelCreating(builder);

        builder.UseOpenIddict();

        builder.Entity<User>(entity =>
        {
            entity.HasKey(e => e.Uid);
            entity.HasIndex(e => e.Name).IsUnique();
            entity.HasIndex(e => e.Group);
            entity.HasIndex(e => e.Email);
            entity.HasIndex(e => e.NormalizedEmail).IsUnique();
            entity.HasIndex(e => e.RegisterTime);

            entity.Property(e => e.Status).HasMaxLength(32).IsRequired().HasConversion<string>();
            entity.Property(e => e.Name).HasMaxLength(256).IsRequired();
            entity.Property(e => e.DisplayName).HasMaxLength(256);
            entity.Property(e => e.Email).HasMaxLength(256);
            entity.Property(e => e.Group).HasMaxLength(32).IsRequired();
        });

        builder.Entity<UserLogin>(entity =>
        {
            entity.HasKey(e => new { e.LoginProvider, e.ProviderKey });
            entity.HasIndex(e => e.UserUid);
            entity.Property(e => e.LoginProvider).HasMaxLength(128).IsRequired();
            entity.Property(e => e.ProviderKey).HasMaxLength(512).IsRequired();

            entity.HasOne(e => e.User)
                  .WithMany(u => u.UserLogins)
                  .HasForeignKey(e => e.UserUid);
        });

        builder.Entity<InviteCodeFailure>(entity =>
        {
            entity.HasKey(e => e.IpAddress);
            entity.Property(e => e.IpAddress).HasMaxLength(45);
            entity.Property(e => e.BanId).HasMaxLength(128);
            entity.HasIndex(e => e.BanExpiresAt);
        });

        builder.Entity<LoginFailure>(entity =>
        {
            entity.HasKey(e => e.IpAddress);
            entity.Property(e => e.IpAddress).HasMaxLength(45);
            entity.Property(e => e.BanId).HasMaxLength(128);
            entity.HasIndex(e => e.BanExpiresAt);
        });

        builder.Entity<IpBanAudit>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.BanId).HasMaxLength(128).IsRequired();
            entity.Property(e => e.IpAddress).HasMaxLength(45).IsRequired();
            entity.Property(e => e.BanType).HasMaxLength(32).IsRequired();
            entity.HasIndex(e => e.BanId).IsUnique();
            entity.HasIndex(e => e.IpAddress);
            entity.HasIndex(e => e.BanType);
        });

        builder.Entity<UserToken>(entity =>
        {
            entity.ToTable("UserToken");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.TokenHash).HasMaxLength(64).IsRequired();
            entity.Property(e => e.TokenPrefix).HasMaxLength(8).IsRequired();
            entity.Property(e => e.LastIpAddress).HasMaxLength(45);
            entity.HasIndex(e => e.TokenHash).IsUnique();
            entity.HasIndex(e => e.UserUid);
            entity.HasIndex(e => e.ExpiresAt);
            entity.HasIndex(e => e.RevokedAt);
            entity.HasIndex(e => e.UserUid)
                  .IsUnique()
                  .HasDatabaseName("UX_UserToken_ActiveUser")
                  .HasFilter("\"RevokedAt\" IS NULL");
        });

        builder.Entity<UserTokenUsage>(entity =>
        {
            entity.ToTable("UserTokenUsage");
            entity.HasKey(e => e.Id);
            entity.Property(e => e.TokenPrefix).HasMaxLength(16).IsRequired();
            entity.Property(e => e.Method).HasMaxLength(8);
            entity.Property(e => e.Endpoint).HasMaxLength(256);
            entity.Property(e => e.IpAddress).HasMaxLength(45);
            entity.Property(e => e.UserAgent).HasMaxLength(512);
            entity.HasIndex(e => e.UserTokenId);
            entity.HasIndex(e => e.OccurredAt);
        });

        builder.Entity<ConfirmationFailure>(entity =>
        {
            entity.HasKey(e => e.UserUid);
            entity.Property(e => e.BanId).HasMaxLength(128);
            entity.HasIndex(e => e.BanExpiresAt);
        });

        builder.Entity<AdminAuthFailure>(entity =>
        {
            entity.HasKey(e => e.IpAddress);
            entity.Property(e => e.IpAddress).HasMaxLength(45);
            entity.Property(e => e.BanId).HasMaxLength(128);
            entity.HasIndex(e => e.BanExpiresAt);
        });

        builder.Entity<EmailVerificationBlock>(entity =>
        {
            entity.HasKey(e => e.IpAddress);
            entity.Property(e => e.IpAddress).HasMaxLength(45);
            entity.Property(e => e.BanId).HasMaxLength(128);
            entity.HasIndex(e => e.BanExpiresAt);
        });

        builder.Entity<UserSession>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.TokenHash).HasMaxLength(64).IsRequired();
            entity.HasIndex(e => e.TokenHash).IsUnique();
            entity.HasIndex(e => e.UserUid);
            entity.HasIndex(e => e.RevokedAt);
        });

        builder.Entity<AuditLog>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.HasIndex(e => e.EventType);
            entity.HasIndex(e => e.UserId);
            entity.HasIndex(e => e.ClientId);
            entity.HasIndex(e => e.Timestamp);
            entity.HasIndex(e => e.Endpoint);
            entity.HasIndex(e => e.SessionToken);
            entity.Property(e => e.Details).HasMaxLength(AuditLog.DetailsMaxLength);
        });

        builder.Entity<OAuthClientMetadata>(entity =>
        {
            entity.HasKey(e => e.ApplicationId);
            entity.Property(e => e.ApplicationId).HasMaxLength(128);
        });

        builder.Entity<SigningKey>(entity =>
        {
            entity.HasIndex(e => e.Thumbprint).IsUnique();
            entity.HasIndex(e => e.IsActive);
            entity.HasIndex(e => e.CreatedAt);
        });

        builder.Entity<InviteCode>(entity =>
        {
            entity.Property(e => e.Code).HasMaxLength(128).IsRequired();
            entity.Property(e => e.Group).HasMaxLength(32).IsRequired();
            entity.Property(e => e.UsedBy).HasColumnType("jsonb");
        });

        builder.Entity<ConsentAuditEvent>(entity =>
        {
            entity.HasKey(e => e.Id);
            entity.Property(e => e.Subject).HasMaxLength(128).IsRequired();
            entity.Property(e => e.ClientId).HasMaxLength(128).IsRequired();
            entity.Property(e => e.Action).HasMaxLength(64).IsRequired();
            entity.Property(e => e.PreviousScopes).HasColumnType("jsonb");
            entity.Property(e => e.RequestedScopes).HasColumnType("jsonb");
            entity.Property(e => e.GrantedScopes).HasColumnType("jsonb");
            entity.HasIndex(e => e.Subject);
            entity.HasIndex(e => e.ClientId);
            entity.HasIndex(e => e.Action);
            entity.HasIndex(e => e.CreatedAt);
        });

        builder.Entity<OpenIddictEntityFrameworkCoreAuthorization>(entity =>
        {
            entity.HasIndex("Subject", "ApplicationId")
                  .IsUnique()
                  .HasDatabaseName("UX_OpenIddictAuthorizations_ActiveUserClient")
                  .HasFilter("\"Status\" = 'valid' AND \"Type\" = 'permanent'");
        });
    }
}
