param(
    [ValidateSet("submit", "dry-run")]
    [string] $Mode = "submit",

    [int] $IntervalSeconds = 60,

    [string] $RepoRoot = "D:\Documentos\worksapce\PMundialera",

    [string] $TaskName = "PMundialera Autonomous Watch",

    [switch] $StartNow
)

$ErrorActionPreference = "Stop"

$runner = Join-Path $RepoRoot "scripts\windows\run-autonomous.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Runner script not found: $runner"
}

$envFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env is required before registering the task."
}

$argument = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$runner`"",
    "-Mode", $Mode,
    "-IntervalSeconds", $IntervalSeconds,
    "-RepoRoot", "`"$RepoRoot`""
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 30) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs PMundialera autonomous GolPredictor watch at Windows logon." `
    -Force | Out-Null

Write-Output "Registered task: $TaskName"
Write-Output "Mode: $Mode"
Write-Output "IntervalSeconds: $IntervalSeconds"
Write-Output "Runner: $runner"

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Started task now."
}
