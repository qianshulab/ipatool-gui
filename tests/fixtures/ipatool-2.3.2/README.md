# ipatool v2.3.2 authentication protocol fixtures

These deterministic JSONL events are derived from official `majd/ipatool` tag `v2.3.2`, commit `ab79e429d5d5d3da6879711f6e04b8a240aabd94`:

- `cmd/auth.go` lines 98–111: non-interactive 2FA challenge message and successful login fields (`name`, `email`, `success`).
- `pkg/log/logger_test.go` lines 53–63: ordinary JSON log messages use the `message` field.
- `cmd/root.go` lines 58–86: command errors emit `success:false` and return exit code 1; a non-interactive 2FA challenge returns normally with exit code 0.

Values are synthetic and are not recordings of a real Apple account or session. Timestamp fields are intentionally omitted because they are non-deterministic and irrelevant to the parser contract.
