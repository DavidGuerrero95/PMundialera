param(
    [string] $TaskName = "PMundialera Autonomous Watch"
)

$ErrorActionPreference = "Stop"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Unregistered task: $TaskName"
} else {
    Write-Output "Task not found: $TaskName"
}
