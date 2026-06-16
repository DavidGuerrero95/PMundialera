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

The output must include two scorelines with rationale and confidence.

Research evidence should be deduplicated, enriched with bounded HTML scraping
when pages are safely reachable, and scored by source quality. Prefer official
sources and recognized media over aggregators or generic snippets, and carry
evidence gaps into the final confidence instead of inventing missing facts.

Before final score selection, produce calibration signals for draw risk,
favorite-bias risk, missing categories, and evidence quality. A strong market or
ranking favorite must be counterweighted by goalkeeper, defensive, set-piece,
recent-stat, logistics, and conditions evidence before using a comfortable
favorite scoreline.

Prediction selection must be probability-first. Estimate home/draw/away,
over/under, both-teams-to-score, and expected goals before deriving the exact
scoreline. Use learning memory as a weak prior, especially with small samples;
do not memorize one-off team results or overfit a single settled match.

Before submission, apply decision guardrails that cap confidence for weak
evidence, reduce unsupported comfortable favorite margins, and add a draw hedge
when draw risk is high.

## Final engine

The platform collects and structures context. The final score decision belongs
to the configured prediction engine. The preferred engine is Codex CLI via
`codex exec -`, with a strict JSON response contract and heuristic fallback only
when Codex is unavailable or returns invalid output.

## Feedback loop

Every real submission must be persisted locally. After GolPredictor publishes a
result, settle the prediction, calculate exact/winner/goals/difference
performance, and update learning memory. Future Codex prompts must include that
learning memory.
