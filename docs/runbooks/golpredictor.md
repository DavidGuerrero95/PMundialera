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
Before submission, the application derives an auditable probability profile
for home/draw/away, over 2.5, both-teams-to-score, and expected goals from a
single scoreline distribution. The final primary is the scoreline that maximizes
GolPredictor expected points, not necessarily the modal exact score. Decision
guardrails cap confidence and reduce unsupported favorite margins; draw hedges
are used only when draw probability and expected points compete with the primary
class.

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
when the underdog xG is low.

## Pre-submit verification

Use these commands before a matchday window:

```powershell
pmundialera golpredictor login-check
pmundialera golpredictor groups
pmundialera run schedule
pmundialera run next --limit 4 --json
pmundialera run once --dry-run --json
```

The JSON preview should include `probabilities`, `decision_flags`, `primary`,
`hedge`, and `confidence`. For debugging, inspect the local SQLite
`match_research` row to verify `scoreline_distribution` and
`expected_points_candidates`. A real `--submit` run still writes only inside the
configured 35-minute window.

## Feedback loop

The local feedback state lives in `.pmundialera/pmundialera.sqlite3`.

- `predictions`: predictions generated during submission windows
- `outcomes`: settled predictions after GolPredictor publishes results
- `match_research`: full research brief captured before each prediction
- `metadata.learning_memory`: compact lessons injected into future Codex prompts
- `metadata.tournament_state`: current team/tournament form injected into future research

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
