namespace Pylaios.Features.Config;





[AttributeUsage(AttributeTargets.Class | AttributeTargets.Property)]
public sealed class ConfigFileAttribute(string fileName) : Attribute
{
    public string FileName { get; } = fileName;
}


[AttributeUsage(AttributeTargets.Property)]
public sealed class ConfigSensitiveAttribute : Attribute;


[AttributeUsage(AttributeTargets.Class | AttributeTargets.Property)]
public sealed class ConfigDescriptionAttribute(string description) : Attribute
{
    public string Description { get; } = description;
}


[AttributeUsage(AttributeTargets.Property)]
public sealed class ConfigRequiredAttribute : Attribute;

[AttributeUsage(AttributeTargets.Property)]
public sealed class ConfigNotEmptyAttribute : Attribute;


[AttributeUsage(AttributeTargets.Property)]
public sealed class ConfigRangeAttribute(int min, int max) : Attribute
{
    public int Min { get; } = min;
    public int Max { get; } = max;
}
