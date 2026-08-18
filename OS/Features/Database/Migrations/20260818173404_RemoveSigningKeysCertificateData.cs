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
            migrationBuilder.DropColumn(
                name: "CertificateData",
                table: "SigningKeys");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<byte[]>(
                name: "CertificateData",
                table: "SigningKeys",
                type: "bytea",
                nullable: false,
                defaultValue: new byte[0]);
        }
    }
}
