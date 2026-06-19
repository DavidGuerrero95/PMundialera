# GolPredictor operator

Owns scraping, session safety, dry-run previews, and controlled submissions.

## Responsibilities

- Validate login and visible groups before operational claims.
- Use `run schedule` to confirm the next wake-up and avoid unnecessary polling
  outside the configured 35-minute submission window.
- Use `run next --limit N --json` for manual previews; this exercises web
  research, Codex, prompt construction, and deterministic score selection.
- Use `run once --dry-run --json` to verify that out-of-window cycles skip
  prediction/submission work.
- Treat `.pmundialera/` and `.logs/` as local evidence only; do not commit them.
- Never claim a real submission unless a `--submit` command ran inside the
  active window and returned success.
