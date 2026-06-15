# ADR 0001: Hexagonal agent architecture

## Status

Accepted.

## Context

The project needs GolPredictor automation, football research, prediction logic,
CLI execution, and MCP integration without coupling core decisions to external
frameworks.

## Decision

Use a hexagonal Python architecture:

- `domain`: framework-free models and ports.
- `application`: orchestration and subagent coordination.
- `infrastructure`: GolPredictor, research, and storage adapters.
- `interfaces`: CLI and MCP entrypoints.

## Consequences

- Prediction logic can be tested without network access.
- GolPredictor scraping can evolve independently from the domain.
- MCP tools stay thin wrappers over application services.
