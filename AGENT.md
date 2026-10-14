# AGENT.md — Approved Strategy (single current policy)

workflow_version: 2026-10-14-repair-1 · Supersedes the stacked v4/v5 directive text (archived verbatim at
`docs/archive/AGENT_v5_v4_2026-10-07_superseded.md`). This file is STRATEGY ONLY. Other concerns live elsewhere:

| Concern | Document |
|---|---|
| What a run does, in order; discovery; data validation; completion | `WORKFLOW.md` |
| Broker writes: coordination, intents, fills, stops, sessions | `EXECUTION.md` |
| Persistence / git protocol | `PERSISTENCE.md` |
| Emails, notification state, cost lines | `reporting/README.md` |
| Thresholds and numbers | `config.json` (authoritative; this file names the keys, not the values) |
| Scoring math | `scripts/scoring.py` (authoritative) |

Scheduled runs NEVER edit this file, `WORKFLOW.md`, `EXECUTION.md`, `config.json`, `PERSISTENCE.md`, or
scripts. Only an interactive, explicit owner request may; then edit only `claude/trading-state`, say exactly
what changed, validate JSON/Python, add/update tests. The routine prompt is a bootstrap loader and never
overrides these files.

## 1. Purpose
Explicit fun-money, high-variance growth account. Find credible exceptional opportunities — setups with a
defensible case for substantial additional upside FROM THE PROPOSED ENTRY (~50%, exceptionally ~100%+) — early,
and hold real winners long enough to matter. Reject unsupported pumps, dilution traps, illiquid junk, merger-arb
names pinned to a deal price, and fully priced catalysts. This is not a promise of outcomes and not a quota of
trades. Do not invent catalysts, inflate scores, or chase unsupported pumps.

The account is already aggressive on concentration and loss tolerance. Do NOT widen stops, raise the 100%
concentration cap, weaken liquidity gates, remove review-before-place, or average down. Improve discovery,
ranking, rotation, cash deployment and winner management instead. Threshold or risk changes need a separate
explicit owner approval.

## 2. Hard rules (never relaxed by a scheduled run)
- One agentic brokerage account; equities/ETFs only. No options, crypto, shorts, borrowing/new leverage.
- Public information only; never use or solicit MNPI.
- Every open long has a verified live protective `stop_market` GTC. OCO may be unavailable; the stop is still
  required. Documented accepted exceptions (`config.accepted_legacy_exceptions`: fractional lots where a stop is
  infeasible) stay visible in every report and are never counted as "protected".
- `review_equity_order` before every equity order; abort on any broker alert. Verify fills by polling; never
  report an unobserved fill.
- Never intentionally sell shares acquired today (America/New_York trading date, derived from lots — see
  WORKFLOW §B). A same-day protective stop may still fire. Unknown acquisition quantity is not sellable.
- Never average down. Pyramiding only into winners that satisfy the current opportunity model (§8).
- Respect drawdown breaker, PDT/day-trade accounting, tradability, buying power, liquidity and spread limits.
- No active-offering/dilution names, no merger-arb names pinned to a deal price, no fraud/bankruptcy/going-concern.
- STOP check before any new entry. If persistence/serialization or the startup manifest fails, add no new risk
  (a genuinely missing protective order may still be added).
- A run is complete only when `scripts/run_complete.py` returns a COMPLETED_* outcome and persistence succeeds.

## 3. Opportunity model
Rank REMAINING opportunity, not old signal strength. Every actionable candidate has separate fields:
`signal_quality_score` (trustworthiness/primary-source directness), `explosive_upside_score`,
`remaining_upside_score` (forward-looking from the proposed entry: why could it be another 50% higher from
here?), and `opportunity_score` (deterministic composite from `scripts/scoring.py`; never hand-computed).

Candidate inputs: signal_quality_score, catalyst_magnitude_score, volume_price_discovery_score,
structure_squeeze_score, remaining_upside_score, dilution_risk_score, exhaustion_risk_score (all 0-10),
primary_source_verified, catalyst_verified, transformational, continuation_confirmed, chase_pct,
market_catalyst_verified, live_heat_verified, disqualifier(+reason).
Scoring guidance: catalyst magnitude 0 none · 5 material · 8 company-changing · 10 transformational relative to
market cap/revenue/addressable market. Volume/price discovery rewards RVOL, acceleration, turnover, above-VWAP,
new highs; a one-print failed spike scores low. Structure/squeeze rewards genuinely constrained supply or high
short interest WITH a positive catalyst — never guess float/short data (unknown stays unknown). Dilution 10 =
imminent severe. Exhaustion = blow-off, failed VWAP, widening spread; being up a lot is not itself exhaustion.
`market_catalyst_verified` = a real current macro/sector event from a reliable source explaining the group move.
`live_heat_verified` = strong abnormal volume/price discovery (normally ≥3x RVOL, healthy spread, no failed-spike).

Mandatory evidence cannot be replaced by a model score: `run_complete.py` recomputes every stated score from its
inputs and rejects any candidate whose qualification scoring.py does not support.

## 4. Candidate tiers (kept distinct — never relabel one as another)
1. **standard** — clears all standard gates: primary source verified, catalyst verified, min signal quality,
   min explosive upside, min remaining upside, min opportunity score, no disqualifier, hard rules pass.
   (The "exceptional" label is reserved for the high/exceptional opportunity-score keys in config.)
2. **tactical** (`cash_deployment_eligible`) — lower bar for putting idle capital to work: needs EITHER a verified
   company-specific primary-source catalyst OR a verified market/sector catalyst PLUS exceptional live heat; plus
   tactical minimum scores, same chase/continuation protections, acceptable liquidity/spread.
3. **best_available** — no hard disqualifier, sane spread/liquidity, and SOME verified reason to own it (company
   catalyst, market catalyst + heat, or verified momentum: RVOL ≥1.5x, up on the day, above VWAP, not a failed
   spike). `momentum_verified` is set only when factually true.
Near-miss rule: a candidate with a verified primary-source catalyst within 1.0 of a gate counts as deployable.
Tactical and best_available holdings keep competing against fresh opportunities (§7).

50%/100% assessment: scoring.py returns implausible / possible / plausible / unusually_plausible labels for
additional upside from the proposed entry. They are ranking labels, not forecasts; every trade journal states both
labels and the factual reason the move could continue.

## 5. Capital deployment policy (cash threshold gates DEPLOYMENT, never discovery)
Discovery happens every active-market run regardless of cash (WORKFLOW §C). Separately:
- Idle cash is a failure mode. `idle_cash_target_pct_of_account` is the goal; `idle_cash_escalation_pct_of_account`
  activates mandatory deployment work; `idle_cash_critical_pct_of_account` means critical search depth.
- deployable_buying_power = unleveraged buying power usable now minus `min_cash_reserve_usd`; never margin or
  unsettled funds.
- REGULAR HOURS with deployable cash ≥ the escalation threshold: the run MUST end with a verified fill + protective
  stop, or a documented HARD BLOCK (PDT/day-trade gate, broker/tradability/halt rejection, persistence/serialization
  failure, drawdown halt, or ZERO reviewed names clearing even best_available after the full review, with each name
  and reason journaled). "Only two names were web-checked" is not a completed review: the deep-review quota
  (`idle_cash_min_candidates_deep_reviewed`) and independent catalyst checks
  (`idle_cash_min_independent_catalyst_checks`) must be genuinely met, or the shortfall recorded as insufficient
  coverage — never as "no opportunity".
- Choice order: (a) best standard candidate; (b) else best tactical; (c) else best_available — via
  `scoring.py deploy-plan`, buying the plan's pick for the plan's spend; (d) a qualifying pyramid into an existing
  winner; (e) rotation (§7). Do not substitute own sizing or veto the plan on "feels weak".
- Sizing to target: spend down to the idle-cash target. Tactical/best_available capped at
  `tactical_cash_position_max_pct_of_account`; standard at `max_position_pct_of_account`; tactical initial stop
  `tactical_cash_initial_stop_loss_pct`.
- Up to `max_open_positions` meaningful positions (≥ `strategic_position_min_usd`); dust below that does not take a
  slot but stays tracked and reported. `max_new_positions_per_run` applies.
- Pre-market/overnight runs usually cannot trade (wide spreads) but still research and build a ranked
  `deployment_queue`; the first run at/after 09:30 ET re-checks quotes and buys from it. Extended-hours entries are
  allowed up to `max_bid_ask_spread_pct_extended` with a marketable limit.
- When cash is low or the book is full, a properly funded rotation (§7) is how a stronger opportunity is funded.

## 6. Catalysts, sources, universe
Tier S: FDA/regulatory reversals, pivotal results, transformative licensing (large non-dilutive upfront vs market
cap), acquisition proposals not pinned to a fixed price, unusually large contracts, court/regulatory outcomes that
change economics, credible activist/13D, dramatic small/mid-cap earnings or guidance inflections.
Tier A: material partnership, major customer win, earnings blowout, large buyback, asset sale/restructuring/
financing improvement, fresh credible activist filing. Tier B (confirmation only): insider cluster/CEO buy,
politician purchase, unusual options, technical breakout without a catalyst.
A routine insider signal must not outrank a fresh Tier S catalyst with a much larger upside profile.
Primary sources: SEC 8-K/6-K/Form 4/13D with exhibits, company IR release (a primary source even before the 8-K),
FDA/government/court/exchange, filed earnings release/official transcript. News search finds the reason; a primary
source verifies it. "Could not verify" is recorded as unverified — never as "no catalyst exists".
Chase rule: price appreciation alone is not a veto. >50% up: penalty only if price discovery weakens. >80% up:
non-transformational → normally reject; transformational → eligible only if continuation is confirmed (strong
abnormal volume, acceptable spread, above-VWAP/healthy discovery, economics supporting more revaluation).
Universe/liquidity: `min_price`, `min_market_cap_usd`, `min_avg_volume_30d_shares`, `max_bid_ask_spread_pct`,
tradable, not deficient/delinquent/bankrupt, `earnings_blackout_trading_days`. Scanner profiles may be narrower.

## 7. Holdings, freshness and rotation
- Every meaningful holding carries v2 fields (signal quality, explosive, remaining upside, opportunity score,
  class transformational/durable/momentum, `opportunity_score_date`) plus `assessment_run_id` and an
  `assessment_evidence_ref`. Missing score and stale score are different conditions; BOTH require a real review
  (quote, thesis/catalyst re-verification, dilution/bad-news check, remaining-upside). Cadence:
  `holding_reassessment_max_age_trading_days` per class, and immediately on a material development. A date bump
  without the review is rejected by `persist_run.py`.
- Score decay classes (`*_score_decay` in config) are applied by scoring.py only; legacy one-dimensional scores are
  capped by `legacy_old_score_cap_for_opportunity`. Neither stale flags nor an old narrative may permanently protect
  an incumbent, and a stale score is never by itself a reason to sell.
- Rotation compares a qualified candidate with the weakest holding that has a legally sellable quantity (lots
  derived per WORKFLOW §B). Candidate must clear `min_opportunity_score` and beat the incumbent's FRESH score by
  `rotation_min_opportunity_advantage`. If the incumbent is stale/unevidenced: status REASSESS_INCUMBENT_FIRST
  (refresh, then re-run). Same-day and unknown quantities are never replaceable. Ties: free the larger dollar
  position, then the oldest. Re-verify price/spread/tradability immediately before acting; account for execution
  cost and verify unleveraged buying power after the sale before treating proceeds as usable. Do not rotate merely
  because a score decayed or to create activity. Selling a loser or winner is irrelevant; rotation is forward-looking.
- Near-miss watchlist: maintained every run, regardless of cash. Persist near misses (opportunity ≥ tactical minimum
  − 1.0, no disqualifier, verified catalyst) with ref price, catalyst, trigger, and expiry (3 trading days or negative
  news); create a price alert at the trigger if available; re-quote and re-score first thing each run using real
  current evidence. Retained candidate records: see WORKFLOW §E.

## 8. Sizing, pyramiding, winners, exits, day-trade gate
- Size by opportunity score after hard gates: below `opportunity_size_tier_mid` → `size_pct_low`; ≥ mid →
  `size_pct_mid`; ≥ `opportunity_size_tier_high` → `size_pct_high`; capped by `max_position_pct_of_account`
  (never above 100%), spendable unleveraged buying power minus reserve, and broker restrictions. No token positions.
- Pyramiding only when the position is up ≥ `pyramid_min_unrealized_pct`, no averaging down, current opportunity and
  remaining-upside still clear their gates, no new dilution/bad news, no PDT problem, ≤ `max_pyramids_per_position`.
- Winners: do not auto-sell at +20/50/75/100%; the 50%/100% objective is not a take-profit cap. At each new
  high_since_entry compute the high-water gain and protect at least `winner_stop_floors_pct` when technically
  possible, never lowering the existing stop, and also apply `trail_distance_pct`; use the highest valid stop below
  market and journal any constraint. A negative catalyst overrides "let it run".
- Bad-news exit: verified active dilutive offering, failed pivotal/adverse regulatory decision, deal break, major
  guidance cut, invalidating insider-selling cluster, activist exit, fraud/restatement/going-concern → exit a legally
  sellable position instead of waiting for the stop (same-day rule applies), journaling the verified source.
- Day-trade gate: do not open a new position if day trades in the last 5 business days + same-day lots held would
  exceed `day_trade_limit_rolling_5_days` + 1; defer to the next session.

## 9. Still never
Average down · bypass broker review alerts · claim unobserved fills · intentionally sell a same-day lot · act on
MNPI · skip protective-order verification · treat missing safety data as favorable · use old score strength as a
permanent blocker against a stronger current opportunity · hard-reject a verified transformational catalyst solely
because it is up >80% · call a setup "50%-100% potential" without the remaining-upside case from the entry · report
"no action" when `run_complete.py` did not return COMPLETED_NO_QUALIFYING_TRADE.
