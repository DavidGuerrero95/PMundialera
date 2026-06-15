# Hexagonal Python architecture

- `domain/` contains framework-free entities, value objects, and ports.
- `application/` orchestrates use cases and depends only on domain ports.
- `infrastructure/` implements external adapters.
- `interfaces/` exposes CLI and MCP entrypoints.
- Avoid wildcard imports.
- Remove dead code.
- Prefer typed, explicit data structures.
