# GolPredictor runbook

## Setup

1. Copy `.env.example` to `.env`.
2. Fill `GOLPREDICTOR_USERNAME` and `GOLPREDICTOR_PASSWORD`.
3. Install the project with `python -m pip install -e ".[dev,mcp]"`.

## Dry-run window

```powershell
pmundialera run window --group "Mundial CoreX" --dry-run
```

## Preview now

```powershell
pmundialera run next --limit 2 --json
```

La prediccion final usa Codex CLI si `PMUNDIALERA_PREDICTION_ENGINE=codex`.
El comando recomendado en Windows es `npx -y @openai/codex --search exec -`
porque el alias de la app puede no poder lanzarse desde subprocess.

## Autonomous dry-run

```powershell
pmundialera run once --dry-run
pmundialera run watch --interval-seconds 60 --dry-run
pmundialera run schedule
```

## Fully automatic Windows startup

Register the Windows logon task:

```powershell
.\scripts\windows\register-autostart-task.ps1 -Mode submit -IntervalSeconds 60
```

Register and start immediately:

```powershell
.\scripts\windows\register-autostart-task.ps1 -Mode submit -IntervalSeconds 60 -StartNow
```

If Task Scheduler returns `Access denied`, install the per-user Startup shortcut
instead:

```powershell
.\scripts\windows\install-startup-shortcut.ps1 -Mode submit -IntervalSeconds 60 -StartNow
```

The task runs `scripts/windows/run-autonomous.ps1`, which:

- uses `.env` for credentials and Codex config
- reuses the existing editable install when `mundialera` already imports
- installs/refreshes the editable package only when missing, or when launched with `-RefreshInstall`
- reads GolPredictor fixtures and computes the next wake-up before the configured
  submission window instead of polling every minute while idle
- runs `pmundialera run once --submit` only inside an active submission window
- runs each autonomous cycle through a PowerShell watchdog so a hung Python call is
  killed after `-CycleTimeoutSeconds` and the next interval can continue
- settles completed predictions and updates learning memory every cycle
- writes local logs under `.logs/`
- uses a named mutex so duplicate watchers do not run

Stop future automatic starts:

```powershell
.\scripts\windows\unregister-autostart-task.ps1
.\scripts\windows\uninstall-startup-shortcut.ps1
```

## Submit window

```powershell
pmundialera run window --group "Mundial CoreX" --submit
```

Real submission is allowed only when kickoff is within the configured 35-minute window
unless `PMUNDIALERA_SUBMISSION_WINDOW_MINUTES` is overridden.

## Research quality

Production research uses categorized web queries for availability, individual player context,
personal/professional news, tactics, venue/weather, form, news, market, ranking,
referee/discipline, table incentives, rest/travel, goalkeepers/defense, recent match stats,
under/over, both-teams-to-score, corners, and set pieces.
Results are deduplicated, enriched with bounded HTML scraping when reachable, and scored by
source tier before the final Codex prompt is built.
Each prediction receives calibration signals for draw risk, favorite-bias risk,
missing evidence categories, and evidence quality.

## Feedback loop

The local feedback files live under `.pmundialera/`:

- `predictions.jsonl`: predictions generated during submission windows
- `outcomes.jsonl`: settled predictions after GolPredictor publishes results
- `learning-memory.md`: compact lessons injected into future Codex prompts

Commands:

```powershell
pmundialera feedback status
pmundialera feedback settle
```
