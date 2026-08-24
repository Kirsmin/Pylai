using System.Data;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Pylaios.Shared;

public static class ProductionSecurityGate
{
    public static async Task ValidateAsync(IServiceProvider services, MainConfig config, IWebHostEnvironment env)
    {
        if (env.IsDevelopment())
            return;

        if (string.IsNullOrWhiteSpace(config.InviteCode.ServerPepper))
            throw new InvalidOperationException("生产环境未配置邀请码 HMAC pepper。");

        RejectKnownDefaultSecrets(config);

        using var scope = services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<ApplicationDbContext>();
        if (await db.InviteCodes.AnyAsync(c => c.Status == InviteCodeStatus.Active
            && (c.CodeHash == null || c.CodeHash == "")))
        {
            throw new InvalidOperationException("检测到未完成 HMAC 迁移的邀请码，拒绝启动。");
        }

        var connection = db.Database.GetDbConnection();
        if (connection.State != ConnectionState.Open)
            await connection.OpenAsync();

        if (await ColumnExistsAsync(connection, "InviteCodes", "Code"))
            throw new InvalidOperationException("InviteCodes 仍包含 legacy 明文字段，请先执行 invite migrate-legacy。");

        if (await ColumnExistsAsync(connection, "SigningKeys", "CertificateData"))
            throw new InvalidOperationException("SigningKeys 仍包含 legacy 明文 PFX 字段，请先执行 key reencrypt。");

        if (await db.SigningKeys.AnyAsync(k =>
                k.PublicCertificateData == null
                || k.EncryptedCertificateData == null
                || k.EncryptionNonce == null
                || k.EncryptionTag == null))
            throw new InvalidOperationException("检测到未完成 AES-GCM 加密迁移的签名密钥，拒绝启动。");
    }

    /// <summary>
    /// 已知默认/弱密码 Fail Closed：连接串与 Redis 密码命中示例值即拒绝启动（仅非 Development）。
    /// 与 deploy/entrypoint.py 的 WEAK_SECRETS 保持同一清单。
    /// </summary>
    private static void RejectKnownDefaultSecrets(MainConfig config)
    {
        HashSet<string> weak = new(StringComparer.OrdinalIgnoreCase)
            { "change-me", "changeme", "password", "secret", "123456", "pylai" };

        string? dbPassword = null;
        try
        {
            var builder = new System.Data.Common.DbConnectionStringBuilder
            {
                ConnectionString = config.Database.ConnectionString
            };
            if (builder.TryGetValue("Password", out var value) && value is string s && s.Length > 0)
                dbPassword = s;
        }
        catch (ArgumentException)
        {
            // 连接串解析失败交由后续数据库连接阶段报错，这里不做二次诊断
        }

        if (dbPassword is not null && weak.Contains(dbPassword.Trim()))
            throw new InvalidOperationException("[Database].ConnectionString 使用了已知默认/弱密码，拒绝启动。请改为随机生成的强密码。");

        if (!string.IsNullOrWhiteSpace(config.Redis.Password) && weak.Contains(config.Redis.Password.Trim()))
            throw new InvalidOperationException("[Redis].Password 使用了已知默认/弱密码，拒绝启动。请改为随机生成的强密码。");
    }

    private static async Task<bool> ColumnExistsAsync(System.Data.Common.DbConnection connection, string table, string column)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = "SELECT 1 FROM information_schema.columns WHERE table_name=@table AND column_name=@column";
        var parameter = command.CreateParameter();
        parameter.ParameterName = "table";
        parameter.Value = table;
        command.Parameters.Add(parameter);
        parameter = command.CreateParameter();
        parameter.ParameterName = "column";
        parameter.Value = column;
        command.Parameters.Add(parameter);
        return await command.ExecuteScalarAsync() is not null;
    }
}
