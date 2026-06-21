# Prediction workflow

For each match, collect or synthesize:

- Team current form.
- Squad availability, likely starters, injuries, suspensions, and staff context.
- Individual player context, recent minutes, goalkeeper status, key-player news,
  and relevant personal/professional developments that can affect availability or
  performance.
- Tactical style and matchup.
- Venue, weather, pitch, travel, and local conditions.
- Historical head-to-head without over-weighting stale results.
- World Cup pressure, social, emotional, and tournament incentives.
- Recent tournament results to avoid single-source bias.
- Recent match stats, shots, shots on target, goalkeeper saves, corners, set-piece
  goals, under/over profile, both-teams-to-score profile, and draw probability.
- Ranking/ELO and squad quality gap.
- Market odds and public bias.
- Referee, cards, penalties, and discipline.
- Rest, travel, time zone, and fatigue.
- Group-table incentives and goal-difference pressure.
- Goalkeepers, defensive line, and set pieces.

The output must include two scorelines with rationale and confidence, but the
primary scoreline must be selected by the deterministic expected-points
optimizer when a probability profile is available.

Research evidence should be deduplicated, enriched with bounded HTML scraping
when pages are safely reachable, and scored by source quality. Prefer official
sources and recognized media over aggregators or generic snippets, and carry
evidence gaps into the final confidence instead of inventing missing facts.

Before final score selection, produce calibration signals for draw risk,
favorite-bias risk, missing categories, and evidence quality. A strong market or
ranking favorite must be counterweighted by goalkeeper, defensive, set-piece,
recent-stat, logistics, and conditions evidence before using a comfortable
favorite scoreline. Do not treat operational failures, search tasks, or generic
metric pages as football evidence.

Prediction selection must be probability-first and internally coherent. Build one
scoreline distribution, derive home/draw/away, over/under,
both-teams-to-score, expected goals, and exact-score probabilities from that
same distribution, then rank candidate scorelines by GolPredictor expected
points:

```text
EP(h,a) = 5 * P(same 1X2 class)
        + 2 * P(home goals = h)
        + 2 * P(away goals = a)
        + 1 * P(goal difference = h-a)
```

For knockout rounds the weights double. The current leaderboard strategy is
`aggressive_high` because the account is configured around position `40/50`:
primary starts from the highest-EP scoreline, but may select a higher-margin,
higher-total, or strategically differentiated candidate when it stays close in
EP, keeps enough exact probability, and respects result-class thresholds.
Winner changes require a close alternative class, no strong favorite, and an
open enough match profile. Confidence represents the calibrated probability of
the selected primary 1X2 class, not generic document quality.
Do not let uncertainty collapse into a repeated score bucket such as `2-1` or
`1-0`. If those scorelines win, they must win through the distribution and EP,
not because they are a generic football default. Compact global tournament priors
must remain weak; global open-profile, hot-attack, or leaky-defense lists are not
direct BTTS/over evidence unless they describe one of the two match teams.
When market, ranking, squad quality, and attacking ceiling align behind a clear
favorite, missing secondary categories should lower confidence but must not erase
the margin signal by default. Evaluate two- and three-goal favorite margins when
the underdog xG is low and the evidence describes clear superiority.

Use learning memory as a weak prior, especially with small samples; do not
memorize one-off team results or overfit a single settled match.
Use SQLite `metadata.strategy_memory` as a bounded strategy prior over the last
24 unique settled matches: raise total/margin upside when recent predictions
underestimated totals or margins, penalize unsupported draw uncertainty when
false draws exceed missed draws, and penalize repeated buckets unless EP clearly
dominates.
After each settled matchday, persist current tournament state: team form, goals
for/against, open/closed profile, BTTS profile, hot attacks, leaky defenses, and
draw/open-match tournament tempo. Inject into the prompt only match-relevant team
state, same-group state when mapped, and compact global tournament priors. Do
not inject detailed state for unrelated teams or global hot/leaky team lists into
LLM context.
General uncertainty is not draw evidence. Draw must be supported by concrete
signals such as market draw price, under profile, low block, goalkeeper edge,
low conversion, fatigue, or matchup constraints. When class gap, market, form,
and attacking ceiling align, prefer a favorite win by one or two goals even when
secondary evidence categories are incomplete.

Before submission, apply decision guardrails that cap confidence for weak
evidence and reduce unsupported comfortable favorite margins.
All configured GolPredictor groups must submit the same primary scoreline. Do
not submit a secondary scoreline to a separate group.

## Final engine

The platform collects and structures context. The configured prediction engine
explains the football evidence and risk, but deterministic application code
selects the final primary from the scoreline distribution whenever a probability
profile is available. The preferred engine is Codex CLI via `codex exec -`, with
a strict one-scoreline JSON response contract and heuristic fallback only when
Codex is unavailable or returns invalid output.

## Feedback loop

Every real submission must be persisted locally. After GolPredictor publishes a
result, settle the prediction, calculate exact/winner/goals/difference
performance, and update learning memory. Future Codex prompts must include that
learning memory. Research records must persist `probabilities`,
`scoreline_distribution`, `expected_points_candidates`, calibration, coverage,
and dedicated signal fields so future agents can audit the prompt without
parsing generic evidence blobs.
