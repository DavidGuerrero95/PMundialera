param(
    [ValidateSet("submit", "dry-run")]
    [string] $Mode = "submit",

    [int] $IntervalSeconds = 60,

    [int] $Iterations = 0,

    [string] $RepoRoot = "D:\Documentos\worksapce\PMundialera",

    [switch] $RefreshInstall,

    [int] $CycleTimeoutSeconds = 1500
)

$ErrorActionPreference = "Stop"
$mutexName = "Local\PMundialeraAutonomousWatch"
$mutex = New-Object System.Threading.Mutex($false, $mutexName)
$hasLock = $false

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

        $stdoutText = Get-Content -LiteralPath $stdout.FullName -Raw -ErrorAction SilentlyContinue
        $stderrText = Get-Content -LiteralPath $stderr.FullName -Raw -ErrorAction SilentlyContinue
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
            Write-Output ("[{0}] PMundialera cycle {1} starting." -f (Get-Date -Format "s"), $cycle)
            try {
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
            } catch {
                Write-Output ("[{0}] PMundialera cycle {1} failed: {2}" -f (Get-Date -Format "s"), $cycle, $_.Exception.Message)
            }

            if ($Iterations -gt 0 -and $cycle -ge $Iterations) {
                break
            }
            Start-Sleep -Seconds $IntervalSeconds
        }
    } finally {
        Stop-Transcript | Out-Null
    }
} finally {
    if ($hasLock) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
