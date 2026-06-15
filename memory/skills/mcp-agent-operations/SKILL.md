# MCP agent operations skill

Use this skill when exposing PMundialera to external agents.

## Tools

- Login check
- Group listing
- Fixture scraping
- Single-match prediction
- Prediction-window execution

## Safety

- Tools that can write external state must expose a `dry_run` argument.
- Default `dry_run` to `true`.
- Never expose secrets in MCP responses.
