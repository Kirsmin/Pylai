using System.Security.Cryptography.X509Certificates;

namespace Pylaios.Shared;

public static class CertificateLoader
{
    public static X509Certificate2 LoadPkcs12(string path, string? password)
        => X509CertificateLoader.LoadPkcs12(
            File.ReadAllBytes(path), password, X509KeyStorageFlags.Exportable);
}
