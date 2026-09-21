# Repository state reconciliation — 2026-09-21T13:35Z

Maintenance session (no trading, no live email sent from this session).
Repository: `hockeman/robinhood`. GitHub-reported default branch at the
time of this reconciliation: `claude/clever-thompson-2hr5eq` (the original
bootstrap commit, `d5697362242d33374f172936671b2c2f38a10f12`) — still not
repointed by the owner as of this run.

## What was found

60 remote branches existed at the start of this session (61 after adding
this run's own working branch, 62 counting `claude/journal` from the prior
session). Every branch traced back to the same bootstrap commit. Two
patterns:

- **~57 "orphan" branches** (`claude/clever-thompson-*`): each one is a
  single session that cold-started on the stale default branch, did its
  run, and committed/pushed only to its own newly-created branch. Each
  contributed exactly one `journal/*.md` file and its own from-scratch
  `state.json` (built by re-deriving from the live broker each time, not
  by reading a prior run's state).
- **A short "lineage"** (`claude/clever-thompson-2vyun4` →
  `claude/clever-thompson-p936tf` → `main`): three runs that *did*
  successfully read and continue from `main` per an earlier AGENT.md fix,
  accumulating journal entries `2026-09-20-0316` through `2026-09-21-0718`
  plus `dashboard/template.html`. `main` stopped advancing after
  2026-09-21T10:16:11Z even though at least three later runs happened
  (`gipv4x` @ 11:16Z, `xsfzqi` @ 12:15Z, `moql19` @ 13:23Z) — each of those
  cold-started on the stale default branch again and never reached `main`.
- A 2026-09-21T13:32Z session (`claude/elegant-tesla-opd7nk` /
  `claude/journal`) read `main` and `moql19`, reconstructed a merged
  `state.json`, and introduced the first `notification_state.json` and the
  first sent DAILY_CLOSE email — but did not recover `main`'s accumulated
  journal files or `dashboard/template.html` (a gap fixed in this session).

No branch, at any point, ever contained `trades.jsonl` — confirmed by
checking all 60 branches directly. This is consistent with the account
having zero agent-initiated entries: all four open positions (MSTR, ALVO,
DSP, UROY) are `"legacy"` — adopted from pre-existing broker state at
bootstrap, never opened by this routine. `trades.jsonl` is created empty on
`claude/trading-state`, not fabricated.

## What was merged, and how conflicts were resolved

**`account_value_history`**: every branch's `state.json` was parsed and
every `{ts, value}` pair collected. 62 unique timestamps, zero numeric
conflicts (no timestamp had two different values across branches) —
straightforward union, sorted by time. `peak_account_value` is the max
across all of them: `7727.2372613663` at `2026-09-21T13:17:00Z`
(pre-market, from `moql19`), independently corroborated by that same value
appearing in the two most recent branches.

**`day_trades` / `stopped_out_recently` / `candidates_seen`**: checked all
60 branches — every single one has these as empty (`[]` / `{}` / `{}`).
Nothing to recover; the true history is that no day trade, cooldown, or
scored candidate has ever been recorded by this routine. Left empty, not
reset — there was never anything here to lose.

**`journal/`**: every unique filename across all 60 branches was
identified (61 unique names) and its content copied verbatim via
`git show <branch>:<path>`. Two filenames existed with **different**
content on two different branches (both are real, distinct run outputs
that happened to land on the same ET-rounded timestamp, not the same event
recorded twice):
- `journal/2026-09-19-1814.md` — kept the `claude/clever-thompson-8vdqdx`
  version under its original name; the `claude/clever-thompson-tb47ch`
  version (pushed later, describes itself as the "18:14 ET" run
  independently) is preserved as `journal/2026-09-19-1814-b.md`.
- `journal/2026-09-20-0514.md` — kept the `claude/clever-thompson-cb2jdo`
  version; the `claude/clever-thompson-qu7v0q` version is preserved as
  `journal/2026-09-20-0514-b.md`.

63 journal files total now live on `claude/trading-state` (61 unique dates
+ 2 disambiguated duplicates + `.gitkeep`). Every other journal filename
that appeared on more than one branch was byte-identical across all its
copies (verified programmatically) — no other disambiguation was needed.

**`anomalies`**: 15 distinct `detected` timestamps existed across all
branches, the large majority of them repeated re-confirmations of the same
underlying two issues (the AAPL fractional lot and the MSTR same-day-add)
written independently by orphan runs that couldn't see each other's
reports. Consolidated into 4 canonical entries on `claude/trading-state`,
each carrying its full timeline in `action_taken` rather than duplicating
15 near-identical top-level entries: `aapl-fractional-lot`,
`mstr-same-day-add`, `advanced-orders-disabled` (a standing account
capability note, not something needing owner action), and
`git-branch-persistence` (this reconciliation itself, plus the one
remaining manual step). No anomaly content was discarded — every distinct
observation fed into one of these four; the raw per-branch entries remain
individually readable on their original branches (nothing was deleted).

**`notification_state.json`**: existed on exactly two branches
(`claude/elegant-tesla-opd7nk`, `claude/journal`), both with identical
content — nothing to merge. Its one outbox record, the delayed 2026-09-18
DAILY_CLOSE, was independently re-verified this session via a read-only
Gmail `get_message(1a0c42c727850f44)` call: `labelIds` includes `SENT`,
`to` is `ferrell@chacetech.com`, dated `2026-09-21T13:34:02Z`. Status
upgraded from `accepted` to `verified_sent` on that evidence. **This report
was not resent.**

**Live broker reconciliation**: `get_equity_orders` (account `604824292`)
was re-checked read-only during this session. All four protective orders
match what the most recent branches already recorded — MSTR
`6ab12e3d-...` (stop $149.30 / limit $149.00), ALVO `6aad6bf8-...`
($5.65/$5.60), DSP `6aad67c9-...` ($11.20/$11.15), UROY `6aad8872-...`
($4.28/$4.25) — all `confirmed`, unchanged. Live data is the ground truth
used in `positions`, not any branch's possibly-stale copy.

## What remains uncertain (carried forward, not resolved)

- **Owner acknowledgment of the AAPL lot and MSTR same-day-add.** A single
  branch (`claude/clever-thompson-moql19`, 2026-09-21T13:17Z) recorded that
  the owner acknowledged both in a live conversation and asked not to keep
  flagging them. No other branch, and no artifact this session could read,
  independently corroborates that conversation happened. Carried forward
  in `state.json` with that caveat explicit — treat it as reported, not
  verified, if it matters for a future decision.
- **Whether any push-notification (the pre-email-system channel) was ever
  actually delivered** for the events described in the pre-2026-09-21
  anomaly entries ("owner notified out-of-band this run", "escalating to
  the owner directly", etc.). No artifact records a delivery receipt for
  those; they predate `notification_state.json` entirely. Not something
  this reconciliation can verify one way or the other.
- **The exact intraday high for MSTR before the 149.30 stop was set**
  (recorded as $165.888 from `moql19`'s own read at the time) was not
  re-derived from `get_equity_historicals` this session — carried forward
  as previously recorded, consistent with the still-confirmed live stop
  order.

## What this session changed

- Created branch `claude/trading-state` from `claude/elegant-tesla-opd7nk`
  (this session's own starting point), then added: all 63 journal files,
  `dashboard/template.html` (recovered from `main`, kept as a historical
  artifact only — see `AGENT.md`), a rebuilt `state.json`, an updated
  `notification_state.json`, an empty (and now documented) `trades.jsonl`,
  `reporting/` (README + two HTML templates — the actual current email
  implementation), `PERSISTENCE.md` (the new fetch/save/serialization
  protocol), this file, and an updated `AGENT.md` pointing at all of the
  above.
- Did **not** delete, force-push, or rewrite history on any existing
  branch. Every branch listed above is still present and unchanged;
  nothing here is recoverable-only-from-this-file — it was recoverable
  before this session too, just scattered.
- Did **not** place, modify, or cancel any Robinhood order, and did not
  send any email.

See the end of this maintenance session's chat transcript for the verified
remote commit SHA this reconciliation produced, the two-fresh-workspace
persistence test results, and the exact replacement text for the routine's
saved Instructions.
