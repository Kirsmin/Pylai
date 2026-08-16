using System.ComponentModel.DataAnnotations;

namespace Pylaios.Features.Registration;




public class InviteCode
{
    [Key]
    [MaxLength(128)]
    public string Code { get; set; } = string.Empty;

    [Required]
    [MaxLength(32)]
    public string Group { get; set; } = AuthConstants.Roles.Normal;

    public int MaxRedemptions { get; set; } = 10;

    public int UsedCount { get; set; }

    public List<string> UsedBy { get; set; } = [];
}
