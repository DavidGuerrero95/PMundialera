param(
    [ValidateSet("submit", "dry-run")]
    [string] $Mode = "submit",

    [int] $IntervalSeconds = 60,

    [int] $Iterations = 0,

    [string] $RepoRoot = "D:\Documentos\worksapce\PMundialera"
)

$ErrorActionPreference = "Stop"
$mutexName = "Local\PMundialeraAutonomousWatch"
$mutex = New-Object System.Threading.Mutex($false, $mutexName)
$hasLock = $false

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

        python -m pip install -e ".[mcp]"

        $iterationArgs = @()
        if ($Iterations -gt 0) {
            $iterationArgs = @("--iterations", $Iterations)
        }

        if ($Mode -eq "submit") {
            python -m mundialera.interfaces.cli run watch --interval-seconds $IntervalSeconds @iterationArgs --submit
        } else {
            python -m mundialera.interfaces.cli run watch --interval-seconds $IntervalSeconds @iterationArgs --dry-run
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
