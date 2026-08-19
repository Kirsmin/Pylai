using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Pylaios.Features.Database.Migrations
{
    /// <inheritdoc />
    public partial class RemoveSigningKeysCertificateData : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // 幂等：v0.0.2 的 key reencrypt 曾用直接 SQL 删除该列（不记录迁移历史），
            // 已删除过的库再 DROP 会 42703 失败；IF EXISTS 兼容两种状态。
            migrationBuilder.Sql("ALTER TABLE \"SigningKeys\" DROP COLUMN IF EXISTS \"CertificateData\"");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql("ALTER TABLE \"SigningKeys\" ADD COLUMN IF NOT EXISTS \"CertificateData\" bytea");
        }
    }
}
