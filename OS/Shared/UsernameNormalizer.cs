using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Identity;

namespace Pylaios.Shared;

public sealed class PylaiosLookupNormalizer : ILookupNormalizer
{
    public string NormalizeName(string name) => UsernameNormalizer.Normalize(name);
    public string NormalizeEmail(string email) => UsernameNormalizer.Normalize(email);
}

public static class UsernameNormalizer
{
    private static readonly Regex InvalidCharsRegex = new(
        @"[\s\u0000-\u001F\u007F-\u009F\u00AD\u200B-\u200F\u2028-\u202F\u2060\uFEFF]",
        RegexOptions.Compiled);



    private static readonly Dictionary<char, char> HomoglyphMap = new()
    {

        ['\u0430'] = 'a',
        ['\u0431'] = '6',
        ['\u0435'] = 'e',
        ['\u0455'] = 's',
        ['\u0456'] = 'i',
        ['\u0458'] = 'j',
        ['\u043E'] = 'o',
        ['\u0440'] = 'p',
        ['\u0441'] = 'c',
        ['\u0443'] = 'y',
        ['\u0445'] = 'x',


        ['\u0391'] = 'A',
        ['\u0392'] = 'B',
        ['\u0395'] = 'E',
        ['\u0397'] = 'H',
        ['\u0399'] = 'I',
        ['\u039A'] = 'K',
        ['\u039C'] = 'M',
        ['\u039D'] = 'N',
        ['\u039F'] = 'O',
        ['\u03A1'] = 'P',
        ['\u03A4'] = 'T',
        ['\u03A5'] = 'Y',
        ['\u03A7'] = 'X',
        ['\u0396'] = 'Z',
    };

    public static string Normalize(string input)
    {
        if (string.IsNullOrWhiteSpace(input))
            return string.Empty;


        var result = input.Normalize(NormalizationForm.FormC);


        result = ToHalfWidth(result);


        result = MapHomoglyphs(result);


        result = result.ToLowerInvariant();

        return result;
    }

    public static (bool valid, string? error) Validate(string input)
    {
        if (string.IsNullOrWhiteSpace(input))
            return (false, "Username cannot be empty.");

        if (InvalidCharsRegex.IsMatch(input))
            return (false, "Username contains invalid characters (spaces or control characters).");

        var normalized = Normalize(input);
        if (string.IsNullOrEmpty(normalized))
            return (false, "Username cannot be empty after normalization.");

        if (normalized.Length < 2 || normalized.Length > 256)
            return (false, "Username must be between 2 and 256 characters.");

        return (true, null);
    }

    private static string ToHalfWidth(string input)
    {
        var chars = input.ToCharArray();
        for (var i = 0; i < chars.Length; i++)
        {
            var c = chars[i];
            if (c >= '\uFF01' && c <= '\uFF5E')
            {
                chars[i] = (char)(c - '\uFF01' + '!');
            }
            else if (c == '\u3000')
            {
                chars[i] = ' ';
            }
        }
        return new string(chars);
    }

    private static string MapHomoglyphs(string input)
    {
        var sb = new StringBuilder(input.Length);
        foreach (var c in input)
        {
            sb.Append(HomoglyphMap.TryGetValue(c, out var mapped) ? mapped : c);
        }
        return sb.ToString();
    }
}
