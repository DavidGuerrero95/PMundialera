param(
    [string] $ShortcutName = "PMundialera Autonomous Watch.lnk"
)

$ErrorActionPreference = "Stop"

$shell = New-Object -ComObject WScript.Shell
$startupFolder = $shell.SpecialFolders.Item("Startup")
$shortcutPath = Join-Path $startupFolder $ShortcutName

if (Test-Path -LiteralPath $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
    Write-Output "Removed startup shortcut: $shortcutPath"
} else {
    Write-Output "Startup shortcut not found: $shortcutPath"
}
