param(
    [ValidateSet("submit", "dry-run")]
    [string] $Mode = "submit",

    [int] $IntervalSeconds = 60,

    [string] $RepoRoot = "D:\Documentos\worksapce\PMundialera",

    [string] $ShortcutName = "PMundialera Autonomous Watch.lnk",

    [switch] $StartNow
)

$ErrorActionPreference = "Stop"

$runner = Join-Path $RepoRoot "scripts\windows\run-autonomous.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Runner script not found: $runner"
}

$envFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env is required before installing startup shortcut."
}

$shell = New-Object -ComObject WScript.Shell
$startupFolder = $shell.SpecialFolders.Item("Startup")
$shortcutPath = Join-Path $startupFolder $ShortcutName

$arguments = @(
    "-WindowStyle", "Hidden",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$runner`"",
    "-Mode", $Mode,
    "-IntervalSeconds", $IntervalSeconds,
    "-RepoRoot", "`"$RepoRoot`""
) -join " "

$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $RepoRoot
$shortcut.Description = "Runs PMundialera autonomous GolPredictor watch at Windows startup."
$shortcut.Save()

Write-Output "Installed startup shortcut: $shortcutPath"
Write-Output "Mode: $Mode"
Write-Output "IntervalSeconds: $IntervalSeconds"
Write-Output "Runner: $runner"

if ($StartNow) {
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $arguments `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden
    Write-Output "Started autonomous watch now."
}
