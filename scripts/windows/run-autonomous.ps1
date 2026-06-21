param(
    [ValidateSet("submit", "dry-run")]
    [string] $Mode = "submit",

    [int] $IntervalSeconds = 60,

    [int] $Iterations = 0,

    [string] $RepoRoot = "D:\Documentos\worksapce\PMundialera",

    [switch] $RefreshInstall,

    [int] $CycleTimeoutSeconds = 1500,

    [int] $IdlePollSeconds = 21600,

    [int] $PreWindowBufferSeconds = 300
)

$ErrorActionPreference = "Stop"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch {
    Write-Output "Unable to force UTF-8 console output: $($_.Exception.Message)"
}
$mutexName = "Local\PMundialeraAutonomousWatch"
$mutex = New-Object System.Threading.Mutex($false, $mutexName)
$hasLock = $false
$heartbeatFile = $null

function Write-PMundialeraHeartbeat {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Status,

        [int] $Cycle = 0,

        [object] $Schedule = $null,

        [string] $Message = ""
    )

    if (-not $heartbeatFile) {
        return
    }

    $payload = [ordered]@{
        updated_at = (Get-Date).ToString("o")
        status = $Status
        cycle = $Cycle
        mode = $Mode
        repo_root = $RepoRoot
        message = $Message
    }
    if ($null -ne $Schedule) {
        $payload.in_window = $Schedule.in_window
        $payload.sleep_seconds = $Schedule.sleep_seconds
        $payload.reason = $Schedule.reason
        $payload.next_match = $Schedule.next_match
    }
    $payload |
        ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $heartbeatFile -Encoding UTF8
}

function Invoke-PMundialeraPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]] $Arguments,

        [Parameter(Mandatory = $true)]
        [int] $TimeoutSeconds
    )

    $stdout = New-TemporaryFile
    $stderr = New-TemporaryFile
    try {
        $process = Start-Process `
            -FilePath "python" `
            -ArgumentList $Arguments `
            -WorkingDirectory $RepoRoot `
            -NoNewWindow `
            -PassThru `
            -RedirectStandardOutput $stdout.FullName `
            -RedirectStandardError $stderr.FullName

        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "Timed out after $TimeoutSeconds seconds: python $($Arguments -join ' ')"
        }

        $stdoutText = Get-Content -LiteralPath $stdout.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        $stderrText = Get-Content -LiteralPath $stderr.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($stdoutText) {
            Write-Output $stdoutText.TrimEnd()
        }
        if ($stderrText) {
            Write-Output $stderrText.TrimEnd()
        }
        $exitCode = $process.ExitCode
        if ($null -ne $exitCode -and $exitCode -ne 0) {
            throw "python $($Arguments -join ' ') failed with exit code $exitCode"
        }
    } finally {
        Remove-Item -LiteralPath $stdout.FullName, $stderr.FullName -Force -ErrorAction SilentlyContinue
    }
}

try {
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) {
        Write-Output "PMundialera autonomous watch is already running."
        exit 0
    }

    Set-Location -LiteralPath $RepoRoot

    $logDir = Join-Path $RepoRoot ".logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logFile = Join-Path $logDir ("autonomous-watch-{0}.log" -f (Get-Date -Format "yyyyMMdd"))
    $dataDir = Join-Path $RepoRoot ".pmundialera"
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $heartbeatFile = Join-Path $dataDir "watch-heartbeat.json"
    Write-PMundialeraHeartbeat -Status "starting" -Message "Autonomous watch acquired mutex."

    Start-Transcript -Path $logFile -Append | Out-Null
    try {
        Write-Output ("[{0}] PMundialera autonomous watch starting. Mode={1}, IntervalSeconds={2}" -f (Get-Date -Format "s"), $Mode, $IntervalSeconds)

        if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot ".env"))) {
            throw ".env is required. Create it from .env.example and keep it out of Git."
        }

        $importCheck = & python -c "import mundialera" 2>&1
        if ($LASTEXITCODE -eq 0 -and -not $RefreshInstall) {
            Write-Output ("[{0}] Existing PMundialera installation detected; skipping pip install." -f (Get-Date -Format "s"))
        } else {
            if ($RefreshInstall) {
                Write-Output ("[{0}] RefreshInstall requested; running editable install." -f (Get-Date -Format "s"))
            } else {
                Write-Output ("[{0}] PMundialera import failed; running editable install. Output: {1}" -f (Get-Date -Format "s"), ($importCheck -join " "))
            }
            python -m pip install --no-build-isolation -e ".[mcp]"
        }

        $cycle = 0
        while ($Iterations -eq 0 -or $cycle -lt $Iterations) {
            $cycle += 1
            $schedule = $null
            Write-Output ("[{0}] PMundialera cycle {1} starting." -f (Get-Date -Format "s"), $cycle)
            Write-PMundialeraHeartbeat -Status "cycle_start" -Cycle $cycle
            try {
                $scheduleOutput = Invoke-PMundialeraPython `
                    -Arguments @(
                        "-m", "mundialera.interfaces.cli", "run", "schedule",
                        "--idle-poll-seconds", $IdlePollSeconds,
                        "--active-poll-seconds", $IntervalSeconds,
                        "--pre-window-buffer-seconds", $PreWindowBufferSeconds
                    ) `
                    -TimeoutSeconds $CycleTimeoutSeconds
                $schedule = $scheduleOutput | ConvertFrom-Json
                $nextMatch = "none"
                if ($null -ne $schedule.next_match) {
                    $nextMatch = "{0} at {1}" -f $schedule.next_match.match, $schedule.next_match.kickoff
                }
                Write-Output (
                    "[{0}] Schedule: in_window={1}, sleep_seconds={2}, reason={3}, next={4}" -f `
                    (Get-Date -Format "s"),
                    $schedule.in_window,
                    $schedule.sleep_seconds,
                    $schedule.reason,
                    $nextMatch
                )
                Write-PMundialeraHeartbeat -Status "schedule_ok" -Cycle $cycle -Schedule $schedule

                if ($schedule.in_window) {
                    if ($Mode -eq "submit") {
                        Invoke-PMundialeraPython `
                            -Arguments @("-m", "mundialera.interfaces.cli", "run", "once", "--submit") `
                            -TimeoutSeconds $CycleTimeoutSeconds
                    } else {
                        Invoke-PMundialeraPython `
                            -Arguments @("-m", "mundialera.interfaces.cli", "run", "once", "--dry-run") `
                            -TimeoutSeconds $CycleTimeoutSeconds
                    }
                    Invoke-PMundialeraPython `
                        -Arguments @("-m", "mundialera.interfaces.cli", "feedback", "settle") `
                        -TimeoutSeconds $CycleTimeoutSeconds
                } else {
                    Write-Output (
                        "[{0}] No active submission window; skipping prediction cycle." -f `
                        (Get-Date -Format "s")
                    )
                }
                Invoke-PMundialeraPython `
                    -Arguments @(
                        "-m", "mundialera.interfaces.cli", "run", "audit",
                        "--json"
                    ) `
                    -TimeoutSeconds $CycleTimeoutSeconds
                Write-PMundialeraHeartbeat -Status "cycle_ok" -Cycle $cycle -Schedule $schedule
            } catch {
                Write-Output ("[{0}] PMundialera cycle {1} failed: {2}" -f (Get-Date -Format "s"), $cycle, $_.Exception.Message)
                Write-PMundialeraHeartbeat -Status "cycle_failed" -Cycle $cycle -Schedule $schedule -Message $_.Exception.Message
            }

            if ($Iterations -gt 0 -and $cycle -ge $Iterations) {
                break
            }
            $sleepSeconds = $IntervalSeconds
            if ($null -ne $schedule -and $null -ne $schedule.sleep_seconds) {
                $sleepSeconds = [int] $schedule.sleep_seconds
            }
            Write-Output ("[{0}] Sleeping {1} seconds." -f (Get-Date -Format "s"), $sleepSeconds)
            Write-PMundialeraHeartbeat -Status "sleeping" -Cycle $cycle -Schedule $schedule
            Start-Sleep -Seconds $sleepSeconds
        }
    } finally {
        Write-PMundialeraHeartbeat -Status "stopping" -Cycle $cycle -Message "Autonomous watch leaving main loop."
        Stop-Transcript | Out-Null
    }
} finally {
    if ($hasLock) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
