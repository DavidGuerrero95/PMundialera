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

The scheduled task is the production mechanism. It registers both a logon
trigger and a 15-minute watchdog trigger. `run-autonomous.ps1` holds a named
mutex, so the watchdog trigger does not create duplicate workers; it only starts
the worker again if the hidden PowerShell process died.

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
- skips real submissions that already have a successful local submission record
- writes `.pmundialera/watch-heartbeat.json` on start, every cycle, sleep, and stop
- runs `pmundialera run audit --json` every cycle so recently due matches without
  local submission coverage are visible in the log
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
Before submission, the application derives an auditable probability profile
for home/draw/away, over 2.5, both-teams-to-score, and expected goals from a
single scoreline distribution. The final primary starts from GolPredictor
expected points, but the current pool strategy is `aggressive_high`: with the
account configured as `40/50`, risk pressure is about `0.80`, so a higher-margin,
higher-total, or differentiated score can beat the EP leader if it stays within
the configured EP/probability thresholds. Winner changes require a close
alternative class, no strong favorite, and an open enough match profile.
Decision guardrails cap confidence and reduce unsupported favorite margins. The
same primary scoreline is submitted for every configured group.

Prompt context must stay scoped: use the two match teams, same-group state when
mapped, and compact global tournament priors. Do not inject detailed state for
unrelated teams, global hot-attack lists, global leaky-defense lists, generic xG
explainers, search failures, or research tasks as football evidence.
Prediction calibration must also avoid repeated bucket defaults. A `2-1`, `1-0`,
or any other common scoreline is valid only when the scoreline distribution and
GolPredictor expected-points optimizer select it. Global open/BTTS tempo is a
weak prior, not direct evidence for both teams to score in a specific match.
Clear market/ranking/squad-quality superiority should affect margin, not only
confidence. Missing lineups, goalkeeper detail, or set pieces reduce certainty,
but they should not automatically compress a clear favorite into a 1-goal result
when the underdog xG is low. In `aggressive_high` mode, supported favorites can
expand to 3-0 or 0-3 when recent production/form plus ranking, market, or squad
quality support the margin. Open matches can move from 2-1 to 3-1 or from 1-2 to
1-3 when EP is close, while 2-2 requires draw, over, and BTTS all live.

## Pre-submit verification

Use these commands before a matchday window:

```powershell
pmundialera golpredictor login-check
pmundialera golpredictor groups
pmundialera run schedule
pmundialera run audit --json
pmundialera run next --limit 4 --json
pmundialera run once --dry-run --json
```

The JSON preview should include `probabilities`, `decision_flags`, `primary`,
and `confidence`. For debugging, inspect the local SQLite
`match_research` row to verify `scoreline_distribution` and
`expected_points_candidates`. A real `--submit` run still writes only inside the
configured 35-minute window.

When several matches share the same kickoff, `run once` processes all configured
groups by unique match first, not by completing one group at a time. This avoids
missing the second pool while Codex is still researching another match on the
same hour. After each real WebForms save, the GolPredictor page cache is refreshed
from the returned HTML so the next row on that page uses current hidden fields.

## Submission coverage audit

```powershell
pmundialera run audit --json
pmundialera run audit --fail-on-missing
```

The audit checks configured groups for matches that already entered the
35-minute submission window inside the recent lookback window, which defaults to
36 hours. Status values:

- `missing_submission`: no successful local submission and no visible platform prediction
- `platform_prediction_without_local_record`: GolPredictor has a prediction but
  SQLite does not have a matching successful submission record

This command is intended to catch the operational failure mode where the watcher
process dies before a late match window opens.

## Feedback loop

The local feedback state lives in `.pmundialera/pmundialera.sqlite3`.

- `predictions`: predictions generated during submission windows
- `outcomes`: settled predictions after GolPredictor publishes results
- `match_research`: full research brief captured before each prediction
- `metadata.learning_memory`: compact lessons injected into future Codex prompts
- `metadata.tournament_state`: current team/tournament form injected into future research
- `metadata.strategy_memory`: recent 24-match strategy performance for risk mode

Prediction records include probabilities and guardrail flags so future analysis
can improve calibration without overfitting to one match. Tournament state is
regenerated from settled GolPredictor results and may summarize team form, goals
for/against, open/closed profile, BTTS profile, hot attacks, leaky defenses, and
tournament tempo. Prediction prompts must inject only match-relevant team state,
same-group state when mapped, and compact global priors.

`match_research` stores match/team metadata, raw evidence, structured evidence,
uncertainties, calibration, probability profile, `scoreline_distribution`,
`expected_points_candidates`, and analysis dimensions for teams, tournament
state, players, differential players, referees, fouls/cards, fans,
venue/pitch/weather, starters, bench, injuries/suspensions/callups, rhythm,
attack quality, and defensive quality. It also stores `star_player_signals` as a
dedicated field for star or disruptive players that can change attacking ceiling,
BTTS, over/under, or match volatility. Dedicated JSON signal fields also track
team state, likely starters, bench/rotation, availability, individual player
discipline, and rhythm so the LLM prompt can be audited without parsing generic
evidence blobs.

Commands:

```powershell
pmundialera feedback status
pmundialera feedback settle
```
