# Repair report — discovery, state, execution (workflow_version 2026-10-14-repair-1)

Baseline: `claude/trading-state` @ 052ab4193c42434a3479f1aac07947a47369be5b (still the production tip at 2026-10-14T18:46Z).
Repair branch: `claude/repair-discovery-workflow` (based on that commit). STAGED, NOT DEPLOYED — see PROMOTION.md.

## What the routine really executed (verified vs unverified)
Verified: the routine prompt text (received as this session's scheduled-task prompt) tells each run to fetch/checkout
`claude/trading-state`, read PERSISTENCE/AGENT/config/state/notification_state/scoring.py, and treat branch files as
authoritative. It names no completion helper, no adapter, no startup check, no lease. Commit history shows ~hourly runs
at :15 UTC (291 per `claude_cost.runs`). Connectors listed as connected: Gmail, Robinhood Trading.
No code built `positions.json`/`live.json`: the model hand-assembled them from `state.json` (no adapter exists in the
baseline `scripts/`). Persistence = end-of-run plain push; no pre-trade coordination existed.
UNVERIFIED (inaccessible): the platform's saved routine configuration, schedule/overlap policy, environment settings,
whether two runs can overlap in practice, and why no 18:15Z commit was observed.

## Root causes (baseline references)
1. Discovery coupled to cash: `scoring.py:fast_check` only escalated on `idle_cash_status.requires_escalation`; with ~1.8%
   deployable cash nothing required scanners, catalyst search or deep review. AGENT.md's "discovery every run" was prose only.
2. Absent data became success: `fast_check` used `live.get("stop_orders_ok", True)`; scanner/filing fields defaulted to
   empty lists; `idle_cash_status` accepted `independent_catalyst_sweep_complete: true` plus a list of names, with no
   evidence of any request (repro R5: five reviewed names scored 1.0 + bare booleans => `completed: True`).
3. Stale `same_day`: `scoring.py:replaceable_holdings` skipped `pos.get("same_day")`; `same_day` was a boolean persisted in
   `state.json` and never recomputed (GME/APOG/BKV/TEVA still true 5-9 days later; broker tax lots show 2026-10-05/07/07/09
   acquisition dates). No adapter derived it from lots or dates. Mixed-age lots could not be represented.
4. Unknown value treated as small: state positions lack `value_usd`, so `positions_missing_v2` (value < 100) skipped them.
5. Stale scores neither refreshed nor flagged: `effective_opportunity_score` decays scores to 0 (BKV/TEVA 0.0, GME 1.19), so
   incumbents looked weakest on old numbers while nothing required re-review; with four holdings excluded, the "weakest
   replaceable" became ANGX, a $15 fractional lot (repro R2).
6. Git push is a state lock, not a broker lock: PERSISTENCE.md serialization happens after brokerage side effects.
7. Reporting: notification_state mixes `accepted`/`sent`/`verified_sent`; 13 reported ids lack observed records; 1 event
   permanently pending; no daily-close record exists for 2026-10-05..10-13; cost line presented profile-based numbers.

## Files changed (all on the repair branch)
| File | Change / what it fixes |
|---|---|
| scripts/lots.py (new) | Lot-level same-day/sellable/unknown derivation from broker tax lots and the NY date (cause 3) |
| scripts/build_inputs.py (new) | The missing adapter: broker results + state -> positions.json/live.json; per-symbol protection check; accepted exceptions kept separate (3, 4) |
| scripts/discovery.py (new) | Source ledger validation, catalyst window/dedupe, catalyst-first intake, materiality, strategy ranking, budget deferral, candidate-record schema (1, 2) |
| scripts/evidence.py (new) | Saves each raw result, derives status/count/hash; empty scan needs a saved empty response (2) |
| scripts/run_complete.py (new) | Completion validator; 10 outcomes; recomputes scores; blocks no-action on missing evidence (2) |
| scripts/persist_run.py (new) | Single completion path: validates, journals the validator outcome, rejects date-bump refreshes, removes persisted same_day, plain-pushes and observes tip |
| scripts/execguard.py (new), execution_state.json | Lease + durable intents via git CAS; ambiguity -> reconcile, never resubmit; lot-aware sell guard (6) |
| scripts/startup_check.py (new) | Pins branch/commit/version/hashes; validator self-test; run record must carry a passing manifest |
| scripts/scoring.py | Derived lots in `replaceable_holdings`; `assessment_status`; rotation `eligible` vs `executable`/REASSESS_INCUMBENT_FIRST; unknown protection no longer default-safe; discovery/reassessment reasons independent of cash; dust excluded as rotation source; unknown value not exempt |
| scripts/notify_state.py (new) | Evidence-derived delivery states, aggregate pending, non-destructive migration/audit (7) |
| scripts/cost_estimate.py | Lines labeled ESTIMATED; `record-actual` for measured usage; no billed-spend claim |
| config.json | ADDED keys only (workflow_version, discovery, research_budget, reassessment cadence, execution, freshness, accepted_legacy_exceptions). No existing value changed (verified by diff). |
| AGENT.md / WORKFLOW.md / EXECUTION.md / PERSISTENCE.md / reporting/README.md | One consolidated policy; strategy/workflow/execution/reporting separated; old text archived at docs/archive/ |
| scripts/test_workflow.py, docs/repair/* | 35 new tests; repro + verify scripts; e2e evidence |
