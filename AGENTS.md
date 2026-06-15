# PMundialera operating guide

`memory/` is the canonical source of truth for agent behavior in this repository.
Adapter folders such as `.codex/`, `.cursor/`, and `.agents/` must stay thin and
point back to canonical memory content.

## Read path

Use these sources in order:

1. `memory/README.md`
2. `memory/MANIFEST.md`
3. `memory/policies/*`
4. `memory/rules/*`
5. The active skill under `memory/skills/*`
6. The active agent under `memory/agents/*`
7. `README.md`
8. `docs/`
9. `.codex/`
10. `.cursor/`

## Working agreements

- Inspect before editing.
- Prefer minimal diffs.
- Keep domain code framework-free.
- Respect hexagonal boundaries.
- Do not hardcode secrets.
- Treat credential files and runtime evidence as local-only.
- Run targeted validation for touched modules, then full validation when feasible.
- Update docs when contracts, flows, or operations change.
- Use repo skills and agents instead of repeating long prompts.
- Never duplicate canonical content into adapter folders.

## Project context

PMundialera is a Python agentic system for football prediction pools. Its core
goals are:

- Research upcoming matches rigorously.
- Coordinate specialized subagents.
- Scrape and update GolPredictor groups safely.
- Expose the workflow through CLI and MCP tools.
- Submit predictions only inside the configured pre-match window.

## Stack

- Python 3.12+
- Hexagonal architecture
- Typer CLI
- HTTPX + BeautifulSoup for GolPredictor WebForms automation
- Pydantic domain/application models
- Optional MCP server for external agent orchestration
- Pytest, Ruff, Mypy for quality gates
