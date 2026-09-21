# Persistence test write — Workspace A

Written by a fresh `git clone` (not the maintenance session's own working
tree) during the 2026-09-21 repository-state reconciliation, to verify the
startup -> read -> save sequence described in PERSISTENCE.md end to end.

- Cloned fresh, landed on the repo's stale default branch
  (`claude/clever-thompson-2hr5eq`), confirming a plain clone does NOT put
  you on the canonical branch automatically.
- Ran the Startup sequence: `git fetch origin claude/trading-state` +
  `git checkout -B claude/trading-state origin/claude/trading-state`.
- Read `notification_state.json` and confirmed the existing 2026-09-18
  DAILY_CLOSE outbox record (`status: verified_sent`,
  `provider_message_id: 1a0c42c727850f44`) was present and untouched.
- This file is that workspace's Save-step write: a plain,
  non-force `git push origin HEAD:claude/trading-state`.

This is a maintenance-session persistence test, not a scheduled trading
run — no order was placed and no email was sent from this workspace.
