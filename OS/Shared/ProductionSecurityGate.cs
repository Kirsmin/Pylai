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
