# Security and secrets

- Never hardcode credentials, cookies, tokens, or private URLs.
- Use environment variables for GolPredictor credentials.
- Keep `.env`, session dumps, scraped HTML, and run evidence out of source.
- Default destructive or external writes to `dry-run`.
- Log usernames only when needed; never log passwords.
- Treat automated submission as a production operation.
