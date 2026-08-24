// Pylaios 入口：全局 flag 预解析 + 分发（serve → WebAppStartup，其余 → CliAppStartup）。
// 具体启动流程见 Shared/WebAppStartup.cs 与 Shared/CliAppStartup.cs。
var rest = new List<string>();
string? configFlag = null;
var testMode = false;
var versionFlag = false;

for (var i = 0; i < args.Length; i++)
{
    var a = args[i];
    if (a == "--config" && i + 1 < args.Length) { configFlag = args[++i]; continue; }
    if (a.StartsWith("--config=", StringComparison.Ordinal)) { configFlag = a["--config=".Length..]; continue; }
    if (a == "--output" && i + 1 < args.Length) { CliHelpers.OutputFormat = args[++i]; continue; }
    if (a.StartsWith("--output=", StringComparison.Ordinal)) { CliHelpers.OutputFormat = a["--output=".Length..]; continue; }
    if (a == "--TestMode") { testMode = true; continue; }
    if (a == "--version") { versionFlag = true; continue; }
    rest.Add(a);
}

if (versionFlag)
{
    Console.Out.WriteLine(CliHelpers.SerializeJson(new
    {
        success = true,
        name = "Pylaios",
        version = CliHelpers.VersionInfo()
    }));
    return 0;
}

var cliArgs = rest.ToArray();
return cliArgs.Length == 0 || cliArgs[0] == "serve"
    ? await WebAppStartup.RunAsync(testMode, configFlag)
    : await CliAppStartup.RunAsync(cliArgs, cliArgs, configFlag);
