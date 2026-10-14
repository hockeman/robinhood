# Promotion runbook and activation blockers (repair branch claude/repair-discovery-workflow)

NOT promoted. Production `claude/trading-state` is unchanged by this work (tip 052ab41 at last check, 2026-10-14T18:46Z).
The repair branch is based on 052ab41, so promotion is a fast-forward if the tip has not moved.

## Why promotion was not performed
1. Cannot establish that no old writer is running. `CronList` shows only session-local jobs ("No scheduled jobs");
   the platform scheduler / saved routine, its cadence and overlap behaviour are not visible from here. Hourly runs
   were landing at :15 (last observed 17:15Z); no 18:15Z commit was observed by 18:46Z — cause UNVERIFIED (missed run,
   delayed run, or in progress). A run that started before promotion and saves after it would write old-format state
   on top of the new layout.
2. The saved routine prompt cannot be edited from this environment. The old prompt tells runs to treat branch files
   as authoritative, so promoting files alone would partially switch behaviour (new AGENT/WORKFLOW text, old prompt
   wording) without the startup gate being called by the prompt.
3. Evidence capture depends on the agent saving tool results; nothing in the platform writes tool output to disk.

## Owner actions (in order)
1. Pause the routine (or confirm it is idle) so no run is mid-flight. Confirm `git ls-remote origin claude/trading-state`
   is stable across two scheduled slots, or that the platform shows no active session.
2. Review the diff `git diff 052ab41..claude/repair-discovery-workflow` (policy documents, scripts, config additions; no threshold changed).
3. Fast-forward: `git fetch origin && git checkout claude/trading-state && git merge --ff-only claude/repair-discovery-workflow && git push origin claude/trading-state`
   (plain push; abort if not fast-forward — do not force). If the tip moved, merge the new tip into the repair
   branch first and re-run the tests.
4. Paste the prompt from `BOOTSTRAP_PROMPT.md` into the routine.
5. Resume. The first compliant run applies the additive migrations: `scripts/notify_state.py migrate` (notification
   state) and the automatic removal of persisted `same_day` flags by `persist_run.py`. Watch its journal: the first
   token must be a validator outcome, and `runs/<run_id>/run.json` must exist.
6. If the first run misbehaves: `git revert` the promotion merge on `claude/trading-state` (history is preserved) and restore the old prompt.

## Known remaining limitations (not repaired here)
- The execution lease is cooperative: a session that calls the broker without `execguard` is not stopped.
- No continuous / market-wide monitoring: hourly polling of saved scanners, a sampled web search that is weak for
  same-day news, and a per-symbol SEC index; filing text was unavailable (404) for the three 8-Ks read in the demo run.
  A hosted scanner/news feed is a separate, unapproved dependency.
- Same-day buys are only detectable from broker tax-lot dates; if the broker's lot sync lags (is_selectable=false)
  the lot is treated as restricted (conservative).
- Costs remain ESTIMATES unless the owner supplies real usage counts.
- Daily-close emails: the audit found no daily-close record for 2026-10-05 .. 2026-10-13; whether they were sent is
  unknown from the notification state. Not backfilled (no fabrication).
