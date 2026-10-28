using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Pylaios.Features.Database.Migrations
{
    /// <inheritdoc />
    public partial class AddWebAuthnCredentialName : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "Name",
                table: "WebAuthnCredentials",
                type: "character varying(64)",
                maxLength: 64,
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "Name",
                table: "WebAuthnCredentials");
        }
    }
}
