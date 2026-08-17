using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

#nullable disable

namespace Pylaios.Features.Database.Migrations
{
    /// <inheritdoc />
    public partial class SecureHardening : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropPrimaryKey(
                name: "PK_InviteCodes",
                table: "InviteCodes");

            migrationBuilder.DropIndex(
                name: "IX_AuditLogs_SessionToken",
                table: "AuditLogs");

            migrationBuilder.DropColumn(
                name: "SessionToken",
                table: "AuditLogs");

            migrationBuilder.AddColumn<byte[]>(
                name: "PublicCertificateData",
                table: "SigningKeys",
                type: "bytea",
                nullable: true);

            migrationBuilder.AddColumn<byte[]>(
                name: "EncryptedCertificateData",
                table: "SigningKeys",
                type: "bytea",
                nullable: true);

            migrationBuilder.AddColumn<byte[]>(
                name: "EncryptionNonce",
                table: "SigningKeys",
                type: "bytea",
                nullable: true);

            migrationBuilder.AddColumn<byte[]>(
                name: "EncryptionTag",
                table: "SigningKeys",
                type: "bytea",
                nullable: true);

            migrationBuilder.AddColumn<Guid>(
                name: "Id",
                table: "InviteCodes",
                type: "uuid",
                nullable: false,
                defaultValueSql: "gen_random_uuid()");

            migrationBuilder.AddColumn<string>(
                name: "CodeHash",
                table: "InviteCodes",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true);

            migrationBuilder.AddColumn<DateTimeOffset>(
                name: "ExpiresAt",
                table: "InviteCodes",
                type: "timestamp with time zone",
                nullable: false,
                defaultValueSql: "CURRENT_TIMESTAMP + INTERVAL '168 hours'");

            migrationBuilder.AddColumn<string>(
                name: "Prefix",
                table: "InviteCodes",
                type: "character varying(3)",
                maxLength: 3,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Status",
                table: "InviteCodes",
                type: "character varying(16)",
                maxLength: 16,
                nullable: false,
                defaultValue: "Active");

            migrationBuilder.AddPrimaryKey(
                name: "PK_InviteCodes",
                table: "InviteCodes",
                column: "Id");

            migrationBuilder.CreateTable(
                name: "RegistrationSessionBindings",
                columns: table => new
                {
                    SessionTokenHash = table.Column<string>(type: "character varying(64)", maxLength: 64, nullable: false),
                    UserUid = table.Column<Guid>(type: "uuid", nullable: false),
                    CreatedAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_RegistrationSessionBindings", x => x.SessionTokenHash);
                    table.ForeignKey(
                        name: "FK_RegistrationSessionBindings_Users_UserUid",
                        column: x => x.UserUid,
                        principalTable: "Users",
                        principalColumn: "Uid",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "UserMfaSettings",
                columns: table => new
                {
                    UserUid = table.Column<Guid>(type: "uuid", nullable: false),
                    TotpEnabled = table.Column<bool>(type: "boolean", nullable: false),
                    EncryptedTotpSecret = table.Column<string>(type: "character varying(1024)", maxLength: 1024, nullable: true),
                    LastVerifiedAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    CreatedAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    UpdatedAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_UserMfaSettings", x => x.UserUid);
                    table.ForeignKey(
                        name: "FK_UserMfaSettings_Users_UserUid",
                        column: x => x.UserUid,
                        principalTable: "Users",
                        principalColumn: "Uid",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "WebAuthnCredentials",
                columns: table => new
                {
                    Id = table.Column<long>(type: "bigint", nullable: false)
                        .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                    UserUid = table.Column<Guid>(type: "uuid", nullable: false),
                    CredentialId = table.Column<byte[]>(type: "bytea", nullable: false),
                    PublicKey = table.Column<byte[]>(type: "bytea", nullable: false),
                    SignCount = table.Column<long>(type: "bigint", nullable: false),
                    Transports = table.Column<string>(type: "character varying(256)", maxLength: 256, nullable: true),
                    CreatedAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    LastUsedAt = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_WebAuthnCredentials", x => x.Id);
                    table.ForeignKey(
                        name: "FK_WebAuthnCredentials_Users_UserUid",
                        column: x => x.UserUid,
                        principalTable: "Users",
                        principalColumn: "Uid",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_InviteCodes_CodeHash",
                table: "InviteCodes",
                column: "CodeHash",
                unique: true,
                filter: "\"CodeHash\" IS NOT NULL AND \"CodeHash\" <> ''");

            migrationBuilder.CreateIndex(
                name: "IX_InviteCodes_ExpiresAt",
                table: "InviteCodes",
                column: "ExpiresAt");

            migrationBuilder.CreateIndex(
                name: "IX_InviteCodes_Status",
                table: "InviteCodes",
                column: "Status");

            migrationBuilder.CreateIndex(
                name: "IX_RegistrationSessionBindings_UserUid",
                table: "RegistrationSessionBindings",
                column: "UserUid");

            migrationBuilder.CreateIndex(
                name: "IX_WebAuthnCredentials_CredentialId",
                table: "WebAuthnCredentials",
                column: "CredentialId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_WebAuthnCredentials_UserUid",
                table: "WebAuthnCredentials",
                column: "UserUid");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "RegistrationSessionBindings");

            migrationBuilder.DropTable(
                name: "UserMfaSettings");

            migrationBuilder.DropTable(
                name: "WebAuthnCredentials");

            migrationBuilder.DropPrimaryKey(
                name: "PK_InviteCodes",
                table: "InviteCodes");

            migrationBuilder.DropIndex(
                name: "IX_InviteCodes_CodeHash",
                table: "InviteCodes");

            migrationBuilder.DropIndex(
                name: "IX_InviteCodes_ExpiresAt",
                table: "InviteCodes");

            migrationBuilder.DropIndex(
                name: "IX_InviteCodes_Status",
                table: "InviteCodes");

            migrationBuilder.DropColumn(
                name: "EncryptedCertificateData",
                table: "SigningKeys");

            migrationBuilder.DropColumn(
                name: "EncryptionNonce",
                table: "SigningKeys");

            migrationBuilder.DropColumn(
                name: "EncryptionTag",
                table: "SigningKeys");

            migrationBuilder.DropColumn(
                name: "Id",
                table: "InviteCodes");

            migrationBuilder.DropColumn(
                name: "CodeHash",
                table: "InviteCodes");

            migrationBuilder.DropColumn(
                name: "ExpiresAt",
                table: "InviteCodes");

            migrationBuilder.DropColumn(
                name: "Prefix",
                table: "InviteCodes");

            migrationBuilder.DropColumn(
                name: "Status",
                table: "InviteCodes");

            migrationBuilder.DropColumn(
                name: "PublicCertificateData",
                table: "SigningKeys");

            migrationBuilder.AddColumn<string>(
                name: "SessionToken",
                table: "AuditLogs",
                type: "text",
                nullable: true);

            migrationBuilder.AddPrimaryKey(
                name: "PK_InviteCodes",
                table: "InviteCodes",
                column: "Code");

            migrationBuilder.CreateIndex(
                name: "IX_AuditLogs_SessionToken",
                table: "AuditLogs",
                column: "SessionToken");
        }
    }
}
