# PMundialera memory

This directory is the canonical source of truth for repository behavior.
Adapters in `.codex/`, `.cursor/`, and `.agents/` must point here instead of
duplicating rules.

## Read order

1. `MANIFEST.md`
2. `policies/`
3. `rules/`
4. `skills/`
5. `agents/`

## Domain intent

PMundialera coordinates football research subagents, generates calibrated score
predictions, and operates GolPredictor groups safely through explicit ports and
adapters.

The prediction contract is production-oriented: research feeds a coherent
scoreline distribution, the platform optimizes GolPredictor expected points
deterministically, and the LLM explains evidence and risk without overriding the
mathematical primary selection.
