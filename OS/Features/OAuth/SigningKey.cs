using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace Pylaios.Features.OAuth;

public class SigningKey
{
    [Key]
    public int Id { get; set; }

    [Required]
    [MaxLength(64)]
    public string Thumbprint { get; set; } = string.Empty;

    public DateTimeOffset CreatedAt { get; set; } = DateTimeOffset.UtcNow;

    public DateTimeOffset ExpiresAt { get; set; }

    public bool IsActive { get; set; } = true;

    public bool IsRevoked { get; set; }

    public byte[] CertificateData { get; set; } = [];
}
