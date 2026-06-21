param(
    [ValidateSet("submit", "dry-run")]
    [string] $Mode = "submit",

    [int] $IntervalSeconds = 60,

    [string] $RepoRoot = "D:\Documentos\worksapce\PMundialera",

    [string] $TaskName = "PMundialera Autonomous Watch",

    [int] $WatchdogIntervalMinutes = 15,

    [switch] $StartNow
)

$ErrorActionPreference = "Stop"

function Set-PMundialeraScheduledTaskRuntimeSettings {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name
    )

    try {
        $service = New-Object -ComObject "Schedule.Service"
        $service.Connect()
        $folder = $service.GetFolder("\")
        $task = $folder.GetTask($Name)
        $definition = $task.Definition
        $definition.Settings.DisallowStartIfOnBatteries = $false
        $definition.Settings.StopIfGoingOnBatteries = $false
        $definition.Settings.ExecutionTimeLimit = "P30D"
        $folder.RegisterTaskDefinition($Name, $definition, 6, $null, $null, 3, $null) | Out-Null
        Write-Output "Adjusted task runtime settings."
    } catch {
        Write-Output "Task runtime settings could not be adjusted: $($_.Exception.Message)"
    }
}

$runner = Join-Path $RepoRoot "scripts\windows\run-autonomous.ps1"
if (-not (Test-Path -LiteralPath $runner)) {
    throw "Runner script not found: $runner"
}

$envFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env is required before registering the task."
}

$argument = @(
    "-WindowStyle", "Hidden",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$runner`"",
    "-Mode", $Mode,
    "-IntervalSeconds", $IntervalSeconds,
    "-RepoRoot", "`"$RepoRoot`""
) -join " "

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument -WorkingDirectory $RepoRoot
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn
)
if ($WatchdogIntervalMinutes -gt 0) {
    $triggers += New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $WatchdogIntervalMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
}
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 30) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description "Runs PMundialera autonomous GolPredictor watch at Windows logon." `
        -Force | Out-Null
    $registeredWith = "Register-ScheduledTask"
} catch {
    if ($_.Exception.Message -notlike "*Acceso denegado*" -and $_.Exception.Message -notlike "*Access is denied*") {
        throw
    }
    $taskRun = "powershell.exe $argument"
    $scheduleMinutes = [Math]::Max(1, $WatchdogIntervalMinutes)
    & schtasks.exe /Create /TN $TaskName /SC MINUTE /MO $scheduleMinutes /TR $taskRun /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to register task with Register-ScheduledTask and schtasks.exe."
    }
    $registeredWith = "schtasks.exe"
}

Write-Output "Registered task: $TaskName"
Write-Output "RegisteredWith: $registeredWith"
Write-Output "Mode: $Mode"
Write-Output "IntervalSeconds: $IntervalSeconds"
Write-Output "WatchdogIntervalMinutes: $WatchdogIntervalMinutes"
Write-Output "Runner: $runner"

if ($StartNow) {
    if ($registeredWith -eq "Register-ScheduledTask") {
        Start-ScheduledTask -TaskName $TaskName
    } else {
        & schtasks.exe /Run /TN $TaskName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Registered task but failed to start it with schtasks.exe."
        }
    }
    Write-Output "Started task now."
}

Set-PMundialeraScheduledTaskRuntimeSettings -Name $TaskName
