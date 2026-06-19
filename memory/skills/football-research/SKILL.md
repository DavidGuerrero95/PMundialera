# Football research skill

Use this skill when producing match predictions.

## Steps

1. Identify kickoff time, teams, venue, and competition context.
2. Gather current form, tactical style, squad availability, and staff news.
3. Add venue, weather, pitch, travel, and social/emotional pressure factors.
4. Deduplicate claims and reject generic pages that do not contain match-specific
   facts.
5. Produce a concise evidence summary with explicit gaps for unavailable
   lineups, injuries, suspensions, referee, market, goalkeeper, set-piece,
   weather, and venue data.
6. Let the application build a coherent scoreline distribution and expected
   points ranking. The research agent may explain risk, but must not override
   the deterministic GolPredictor optimizer.
7. Assign confidence as the calibrated probability of the selected primary 1X2
   class when a probability profile exists.

## Constraints

- Do not invent sourced facts when research is unavailable.
- Separate observed evidence from model inference.
- Prefer recent, match-specific evidence.
- Use tournament state only for the two match teams, same-group context when
  mapped, and compact global priors.
- Do not convert generic uncertainty into a draw prediction.
