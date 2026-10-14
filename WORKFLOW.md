# WORKFLOW.md — Runtime workflow, data validation, completion

workflow_version: 2026-10-14-repair-1 (must equal `config.json -> workflow_version` and
`scripts/startup_check.py -> WORKFLOW_VERSION`; a mismatch stops the run before any research).
Strategy is in `AGENT.md`; broker-write rules are in `EXECUTION.md`.

## 0. Startup (before anything else)
```
git fetch origin claude/trading-state && git checkout -B claude/trading-state origin/claude/trading-state
python3 scripts/startup_check.py --repo . --out run/manifest.json     # exit 0 required
```
It verifies branch, HEAD == origin tip, no uncommitted edits to instruction/config files, required files, version
match, and that the completion validator rejects an empty run. Failure ⇒ no new trading risk; report the exact error.
Do not read state from any other branch. `run/` is scratch (not committed); evidence goes under `runs/<run_id>/`.

## The sequence (every run, any session)
**A. Reconcile account and protection.** `get_portfolio`, `get_equity_positions`, open `get_equity_orders`
(state=confirmed and queued), quotes for held names. Save raw results. Missing/failed ⇒ the field is *unknown*,
never favorable.
**B. Normalize lots and freshness.** For every held symbol call `get_equity_tax_lots`; save each as
`run/taxlots/<SYM>.json`. Then:
```
python3 scripts/build_inputs.py --now <ISO-UTC> --portfolio run/portfolio.json --positions run/positions_raw.json \
   --orders run/orders.json --quotes run/quotes.json --taxlots-dir run/taxlots --state state.json \
   --trades trades.jsonl --config config.json --out-dir run/
```
This is the ONLY way `positions.json` / `live.json` are produced. Same-day status is derived from lot acquisition
dates against the America/New_York date; the persisted `same_day` flag is ignored (and removed by `persist_run.py`).
Sellable / restricted (acquired today) / unknown quantities are per-lot; a mixed-age position is partly sellable;
unknown or contradictory lot data ⇒ unknown quantity ⇒ sale blocked until reconciled. Protection is checked per
symbol against live GTC stop orders; accepted legacy exceptions are listed separately, never counted as protected.
**C. Discovery (cash-independent, bounded, read-only).** Run every source required for the session
(`config.discovery.required_by_session`) and record each through `scripts/evidence.py record`:
1. The 4 primary scanners, the Early Catalyst Fallback v3 scanner, and the 3 supplemental scanners (by exact title).
2. `earnings_lookback` — `get_earnings_calendar` with a negative `days` window covering the catalyst window.
3. `news_catalyst_search` — at least `config.discovery.min_news_queries` bounded web searches for material
   developments in the window (8-K/6-K/IR releases, FDA/regulatory, contracts, licensing, activist, court, strategic).
4. `held_and_watch_filings` — `get_sec_filing_index` (since = window start) for every held, watchlist and candidate
   symbol (adverse-news check for holdings).
Window = last successful check minus `catalyst_window_overlap_hours`, capped at `catalyst_window_max_hours`
(`discovery.catalyst_window`); events deduplicated by `discovery.dedupe_events` against `state.catalyst_seen`.
ACTUAL SCOPE (do not claim more): saved-scanner rows are top-N snapshots at request time; there is no market-wide
SEC/news feed in this environment (the filing index is per-symbol; web search is sampled); polling is hourly at best,
so moves that begin and fade between runs can be missed. Every ledger entry carries a `coverage_note` saying so.
A catalyst with a concrete reference enters research WITHOUT a price/volume move (`discovery.enters_research`).
**D. New / materially changed.** `discovery.material_change` vs the stored snapshot (price move, RVOL increase, new
filing, new news). A prior rejection is reusable only if `cached_rejection_usable` — otherwise recheck the evidence.
**E. Research within budget.** `discovery.plan_research(queue, research_budget.max_deep_reviews_per_run)` ranks by
strategy (catalyst tier/primary source/size vs market cap/held/changed), not scanner order or share price. Selected
items are deep-reviewed into candidate records (`discovery.CANDIDATE_REQUIRED`: source, timestamps, catalyst refs,
fact/inference/unknown split, dilution and adverse checks, score inputs and `scoring.py opportunity-score` output,
remaining-upside case, strongest counterargument, invalidation conditions, exact reasons, reconsider trigger+expiry).
Anything over budget is recorded as `research.deferred` (state RESEARCH_DEFERRED_BUDGET) — NOT as "no opportunity".
Cash-trigger quota: with deployable cash ≥ the escalation threshold, `idle_cash_min_candidates_deep_reviewed` real
reviews are required; if fewer candidates exist, record insufficient coverage. Never invent candidates.
Holdings due for reassessment (missing/stale/unevidenced per `scoring.positions_needing_reassessment`) are reviewed
here too and recorded in `holdings_reassessed` with `assessment_run_id` + `evidence_ref`.
**F. Compare with replaceable holdings.** `scoring.py rotation` / `fast-check` against `run/positions.json`. Only the
fresh, lot-verified weakest sellable holding can be rotated; a stale incumbent ⇒ reassess first. If the book is full
or cash is low and a candidate qualified, the rotation evaluation is mandatory in the run record.
**G. Allocation, broker and risk checks.** `scoring.py deploy-plan`, day-trade gate, drawdown, tradability,
spread, buying power (re-read unleveraged buying power after any sale).
**H. Execute** only per `EXECUTION.md` (lease → durable intent → review → place → poll → protect).
**I. Persist.** Assemble `run/run.json`, then run the single completion path:
```
python3 scripts/run_complete.py check --run run/run.json --config config.json     # preview
python3 scripts/persist_run.py --run run/run.json --config config.json --state state.json --git .
```
`persist_run.py` validates, writes state/evidence/journal (first token = validator outcome), commits, plain-pushes
to `claude/trading-state`, and prints the observed tip. A run is not done until a tip SHA was observed
(PERSISTENCE.md). Then `scripts/cost_estimate.py update ...` is recorded per `reporting/README.md`.

## Outcomes (the only vocabulary for run results)
| Outcome | Meaning | "no action" claim allowed |
|---|---|---|
| COMPLETED_NO_QUALIFYING_TRADE | all required discovery evidenced; nothing qualified | yes (journal token NO_ACTION) |
| COMPLETED_TRADE_BLOCKED | qualified trade blocked; `block.kind` broker\|strategy + reason + evidence | no |
| COMPLETED_TRADE_EXECUTED | order with intent, review, verified fill | no |
| INCOMPLETE_DISCOVERY | required source missing / not run / invalid, or cash quota unmet | no |
| STALE_OR_FAILED_DATA | account/protection unknown or stale; source failed/stale | no |
| INCOMPLETE_HOLDING_REVIEW | stale/missing holding score not reassessed or deferred | no |
| RESEARCH_DEFERRED_BUDGET | researchable names deferred by budget | no |
| EXECUTION_PENDING_OR_AMBIGUOUS | unresolved/ambiguous order intent | no |
| PROTECTION_PROBLEM | a required stop is missing | no |
| INVALID_RUN_RECORD | contradictory/unsupported evidence (stated score ≠ recomputed, order without intent/evidence, qualified candidate dropped, manifest mismatch) | no |
A broker or safety block may stop a trade; it never cancels safe read-only discovery. When one source fails the
healthy sources are still used and degraded coverage is reported (`ranking_claim_valid=false`).

## Run record (`run/run.json`) — required fields
`run_id, now, market_session, manifest, account{observed_at, account_value, buying_power|deployable_buying_power},
protection{required_symbols, verified_symbols, accepted_exceptions, checked_at}, positions (build_inputs output),
holdings_reassessed, discovery{run_id, sources[]}, catalyst_window, catalyst_seen, research{reviewed, deferred,
budget, queued}, rotation{evaluated, result, blocked_reason}, block, execution{unresolved, orders,
post_sale_buying_power_verified}`. Raw tool results are referenced by `result_ref` + `result_sha256`; the validator
checks shape and freshness, `persist_run.py` stores the record under `runs/<run_id>/run.json`.

## Budget and cost
Reduce tokens by compact inputs (the adapter, not hand-edited JSON), deduplicated events, and cached evidence for
unchanged symbols — never by skipping a required source. Costs are labeled ESTIMATED (assumed token profiles) unless
real token counts are recorded with `cost_estimate.py record-actual` and a stated source.

## Scheduling reality
The platform runs the saved routine on a cron-like schedule; each firing is a fresh session. Editing the prompt or
sleeping inside a run does not create continuous monitoring. In-session rechecks are bounded and optional. Anything
needing sub-hourly or market-wide coverage is a separately approved dependency (hosted scanner), not assumed here.
