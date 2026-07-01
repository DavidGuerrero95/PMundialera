# GolPredictor operations

- Login uses ASP.NET WebForms hidden state fields.
- Scraping must tolerate pagination and accented team names.
- Submissions must be auditable and default to `dry-run`.
- Real submission requires an explicit `submit` flag and an active pre-match
  window.
- Real submission must be idempotent by group and match: if SQLite already has a
  successful non-dry-run submission for that group/match, the automation must
  skip it instead of posting the same score every cycle.
- The configured default window is 35 minutes before kickoff.
- The effective write window closes at the platform lock: 10 minutes before
  kickoff. Do not attempt new submissions or edits inside the final 10 minutes.
- Supported active groups are `Mundial CoreX` and `Mundial FIFA 2026`.
- Windows production automation should use the scheduled task runner with a
  periodic watchdog trigger. The Startup-folder shortcut is only a fallback.
- The watcher must write `.pmundialera/watch-heartbeat.json` and run
  `pmundialera run audit --json` so missed recent submission windows are visible
  without manual SQLite/log inspection.
- `run schedule` and the watcher heartbeat must expose `next_matches` when
  several matches share kickoff or are simultaneously active. Treat `next_match`
  as a compatibility summary only; never infer that it is the full workload.
- For speed, `run schedule` may use only the first configured group as the
  tournament calendar source. Real submission must still use every configured
  group through `run once`.
- In the Windows runner, audit is useful but non-critical. Audit timeouts or
  failures must not block the next sleep/submission cycle.
