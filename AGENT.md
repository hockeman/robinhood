OWNER DIRECTIVE 2026-10-07 v5 — ZERO IDLE CASH, AGGRESSIVE DEPLOYMENT (supersedes v4 where they conflict)
This is the owner's explicit fun-money growth experiment. IDLE CASH IS THE FAILURE MODE. On 2026-10-06 $2.36k sat
idle through four full regular-hours runs because the best candidate (APOG, verified 8-K beat/raise) scored 4.25
against a 4.5 bar. That must never happen again.

ZERO-IDLE-CASH RULES (mandatory, override anything below that says otherwise)
1. REGULAR HOURS (09:30-16:00 ET) with deployable cash >= idle_cash_escalation_pct_of_account (2.5%): the run MUST
   place a buy. Finish only by (a) a verified fill + protective stop, or (b) a documented HARD BLOCK: PDT/day-trade
   gate, broker/tradability/halt rejection, persistence/serialization failure, drawdown halt, or ZERO reviewed
   names clearing even the best_available tier after the full review (journal each name + reason).
2. Candidate tiers, in order: standard > tactical > best_available (see scripts/scoring.py; all thresholds in
   config.json). Run `python3 scripts/scoring.py opportunity-score` on every deep-reviewed name, put the outputs in
   a list, and run `python3 scripts/scoring.py deploy-plan --results r.json --live live.json --config config.json`.
   BUY the plan's pick for the plan's spend_usd. Do not substitute your own sizing or veto it on "feels weak".
3. best_available means: no hard disqualifier, sane spread/liquidity, and SOME verified reason to own it (company
   catalyst, market catalyst + heat, or verified momentum: RVOL >= 1.5x, up on the day, holding above VWAP, not a
   failed spike). Set "momentum_verified": true in candidate.json only when that is factually true.
4. Near-miss rule: a candidate with a verified primary-source catalyst within 1.0 of a gate counts as deployable.
5. Discovery MUST include the supplemental scans in config.json -> deploy_supplemental_scans (Cheap Momentum,
   Exceptional Momentum, Catalyst Momentum) in addition to the four v2 scans and the fallback v3 scan.
6. NO_ACTION with idle cash above target in regular hours is a FAILED RUN unless rule 1(b) applies. A completion
   claim never overrides a candidate that clears any tier (scoring.py raises CASH_DEPLOYMENT_DUE).
7. Size to the target: spend down to idle_cash_target_pct_of_account (1.5%). Tactical/best_available positions are
   capped at tactical_cash_position_max_pct_of_account (50%); standard at max_position_pct_of_account.
8. PRE-MARKET / OVERNIGHT runs cannot usually trade (wide spreads). They must still do the research: build a
   ranked `deployment_queue` in state.json (symbol, tier, opportunity_score, catalyst, source links, intended
   limit logic). The first run at/after 09:30 ET re-checks quotes and BUYS from the queue immediately, then
   continues down the queue/scans until idle cash is at target or max_new_positions_per_run is hit.
   Extended-hours entries are allowed up to max_bid_ask_spread_pct_extended (6%) with a marketable limit.
9. Hard safety that stays: protective stop_market GTC on every position, review_equity_order before every order,
   verified fills, no averaging down, no same-day sells, universe/liquidity floors, no active-offering/dilution,
   no merger-arb names pinned to a deal price, no fraud/bankruptcy/going-concern. Everything else is aggressive.

EMAIL COST LINE: every run (including NO_ACTION) runs `python3 scripts/cost_estimate.py update --kind
light|full|trade --run-id <ISO ts>`; every ACTION_UPDATE / DAILY_CLOSE email must include its printed `line`
(running estimate of Claude spend) via {{CLAUDE_COST_LINE}}. See reporting/README.md.

--- v4 text below; where it conflicts with the v5 rules above, v5 wins ---
OWNER DIRECTIVE 2026-10-05 v4 — EXPLOSIVE CATALYST + MANDATORY CASH DEPLOYMENT MODE
This file is the authoritative standing strategy for the autonomous Robinhood routine.
It supersedes older strategy text whenever there is a conflict.

ACCOUNT PURPOSE
This is explicitly fun-money, high-variance capital. Optimize for asymmetric catalyst setups that can plausibly
move another ~50% from the proposed entry and, in exceptional cases, ~100%+. Do not interpret that objective as
a promise or required outcome for every trade. The goal is to find rare revaluation events early and hold real
winners long enough to matter, while rejecting unsupported pumps, dilution traps, illiquid junk, merger-arb names
pinned near consideration value, and names whose catalyst has already been fully priced.

The account is already aggressive enough on concentration and loss tolerance. Do NOT make it "more aggressive"
by widening stops, increasing the 100% concentration cap, weakening liquidity gates, removing review-before-place,
or blindly averaging down. Improve discovery, ranking, rotation, cash deployment, and winner management instead.

CAPITAL DEPLOYMENT POLICY
During a session in which new entries are allowed, the target is <= idle_cash_target_pct_of_account of total account
value in deployable cash. Cash >= idle_cash_escalation_pct_of_account (2.5%) is not a neutral NO_ACTION condition; it activates
mandatory cash-deployment mode. Standard explosive candidates remain first choice, but if none clears the standard
gate, a verified tactical catalyst candidate may be used under the separate CASH DEPLOYMENT GATE below. The system
must not leave ANY meaningful cash idle merely because no perfect 50%-100% candidate appeared in the first scan.

AUTHORITATIVE STARTUP — EVERY RUN
1. Follow PERSISTENCE.md first. Explicitly fetch and switch to origin/claude/trading-state.
2. Read this AGENT.md, config.json, state.json, notification_state.json, and scripts/scoring.py from that branch.
3. Treat these repository files as the source of truth. A scheduled-routine prompt is only a bootstrap loader and
   must not override newer instructions committed here.
4. Scheduled/unattended runs must NEVER edit AGENT.md, config.json, PERSISTENCE.md, or strategy code. The owner may
   authorize edits only in an interactive session.
5. Check STOP before any new entry. If serialization/persistence cannot be established, no new risk may be added.

HARD RULES — NEVER RELAX IN A SCHEDULED RUN
- One Agentic brokerage account; equities/ETFs only. No options, crypto, shorts, or new leverage.
- Public information only. Never use or solicit MNPI.
- Every open long must have a verified live protective stop_market GTC. OCO may be SERVICE_DISABLED; that does not
  remove the stop requirement.
- review_equity_order before every equity order. Abort on any broker alert.
- Verify fills by polling. Never report a fill that was not observed.
- Never intentionally sell shares bought today. A same-day protective stop may still fire.
- Never average down. Pyramiding is allowed only into winners that satisfy the current opportunity model.
- Respect the drawdown breaker, PDT/day-trade accounting, tradability, buying power, liquidity, and spread limits.
- Entries are normally regular-hours. Extended/all-day entries are allowed only when the broker reports the symbol
  eligible and a limit order can be used at a sane price.
- A run is not complete until persistence succeeds exactly as PERSISTENCE.md requires.
- Notification policy remains ACTION_UPDATE / DAILY_CLOSE only, max one action email per run.

PRIMARY OBJECTIVE: RANK REMAINING OPPORTUNITY, NOT OLD SIGNAL STRENGTH
The old one-dimensional insider/flow score is no longer the primary trading score.

Every actionable candidate must have these separate fields:
1. signal_quality_score (0-10)
   How trustworthy and directly verified the public evidence is. Primary-source company/SEC/FDA/government/court
   material scores higher than headlines, aggregators, social posts, or inference.

2. explosive_upside_score (0-10)
   How capable the setup is of producing an outsized move. This is driven by catalyst magnitude relative to the
   company's size, abnormal volume/price discovery, float/supply structure, short-interest squeeze potential when
   reliable, and whether the event changes the company's economics.

3. remaining_upside_score (0-10)
   Forward-looking from the PROPOSED ENTRY, not from yesterday's close or the pre-catalyst price. Ask:
   "Why could this reasonably be another 50% higher from here?" Consider how much revaluation has already occurred,
   remaining valuation room, nearby supply/resistance, cash runway, dilution risk, and whether price discovery is
   still active.

4. opportunity_score (0-10)
   Deterministic composite produced by scripts/scoring.py. In this mode, explosive_upside_score and
   remaining_upside_score dominate signal_quality_score.

Use:
  python3 scripts/scoring.py opportunity-score --candidate candidate.json --config config.json

Do not hand-wave the final number. Build candidate.json from verified facts and use the script.

CANDIDATE JSON INPUTS
At minimum:
{
  "symbol": "XYZ",
  "signal_quality_score": 0-10,
  "catalyst_magnitude_score": 0-10,
  "volume_price_discovery_score": 0-10,
  "structure_squeeze_score": 0-10,
  "remaining_upside_score": 0-10,
  "dilution_risk_score": 0-10,
  "exhaustion_risk_score": 0-10,
  "primary_source_verified": true/false,
  "catalyst_verified": true/false,
  "transformational": true/false,
  "continuation_confirmed": true/false,
  "chase_pct": number,
  "market_catalyst_verified": true/false,
  "live_heat_verified": true/false,
  "disqualifier": true/false,
  "disqualifier_reason": "..."
}

Scoring guidance:
- catalyst_magnitude_score: 0=no meaningful economics, 5=material, 8=company-changing, 10=transformational relative
  to current market cap/enterprise value/revenue/addressable market.
- volume_price_discovery_score: reward RVOL, volume acceleration, strong turnover, above-VWAP behavior, new highs,
  and healthy consolidation near highs. A one-print spike that immediately fails scores low.
- structure_squeeze_score: reward genuinely constrained supply/low effective float, high short interest with a
  positive catalyst, and obvious price-discovery conditions. Do not guess float/short data.
- dilution_risk_score: shelf/ATM/offering/warrants/convertibles/cash crisis. 10 = imminent/active severe dilution.
- exhaustion_risk_score: blow-off behavior, failed VWAP, repeated halts with lower highs, widening spread, or
  exhausted volume. Do not punish a stock merely for being up a lot.
- market_catalyst_verified: true only when a real, current macro/sector event is verified from a reliable public
  source and clearly explains the group move.
- live_heat_verified: true only when the individual stock has strong abnormal volume/price discovery (normally
  >=3x RVOL, healthy spread/liquidity, strong relative performance, and no obvious failed-spike behavior).
  This pair can satisfy the tactical cash-deployment source requirement even without a company-specific filing.

ACTION GATES
A candidate is normally actionable only when scripts/scoring.py returns eligible=true. Current config gates are:
- primary source verified
- catalyst verified
- signal_quality_score >= min_signal_quality_score
- explosive_upside_score >= min_explosive_upside_score
- remaining_upside_score >= min_remaining_upside_score
- opportunity_score >= min_opportunity_score
- no hard disqualifier
- all broker/universe/PDT/risk hard rules pass

A candidate can be interesting but non-actionable under the STANDARD gate. Record why.
Material idle deployable cash is an ACTIONABLE DEPLOYMENT CONDITION: broaden discovery, re-underwrite the book, and
then apply the separate tactical cash-deployment gate. Do not buy unsupported junk, but do not require every dollar
of the account to wait for a perfect standard-gate monster either.

CASH DEPLOYMENT GATE
When idle-cash escalation is active and no STANDARD candidate is eligible, scripts/scoring.py also returns
cash_deployment_eligible using the tactical thresholds in config.json. A tactical candidate still requires either:
- a verified company-specific public catalyst / primary source, OR
- a verified broad market/sector catalyst PLUS exceptional live heat in the individual stock
and always:
- no hard disqualifier
- acceptable liquidity/spread/tradability
- minimum signal quality, explosive upside, remaining upside, and opportunity score
- the same chase/continuation protections
This is intentionally a lower bar than the standard 50%-100% gate, because its purpose is to put otherwise-idle
capital to work in a real catalyst/momentum setup rather than hold 15%-20% cash indefinitely.
If one or more candidates are cash_deployment_eligible, rank by opportunity_score, then explosive_upside_score, then
remaining_upside_score. With deployable cash available, BUY the best eligible candidate; do not require a rotation.

50% / 100% ASSESSMENT
The scoring helper returns scenario labels for additional upside FROM THE PROPOSED ENTRY:
- implausible
- possible
- plausible
- unusually_plausible

These are ranking labels, not forecasts or guarantees. Every trade journal entry must state the 50% label and the
100% label plus the factual reason the move could continue.

CATALYST HIERARCHY
Tier S — highest priority for this experiment:
- FDA/regulatory approval or rejection reversal that changes commercial prospects
- pivotal/Phase 3 clinical results or similarly decisive technical validation
- transformative licensing/partnership transaction, especially large upfront non-dilutive cash vs market cap
- acquisition/strategic proposal with meaningful upside not already pinned to a fixed consideration price
- unusually large contract/award relative to company size/revenue
- court/regulatory outcome that materially changes economics
- activist/13D situation with a credible strategic path
- dramatic small/mid-cap earnings or guidance inflection

Tier A:
- material commercial partnership
- major customer win
- earnings blowout
- large buyback relative to market cap
- meaningful asset sale / restructuring / financing improvement
- fresh activist filing with credible plan

Tier B — confirmation, not automatic priority:
- insider cluster / CEO or director purchase
- politician equity purchase
- unusual options activity
- technical breakout without a company-changing catalyst

A routine insider signal with an old score of 8-10 must NOT automatically outrank a fresh Tier S catalyst with a
much higher explosive/remaining-upside profile.

PRIMARY-SOURCE VERIFICATION
Use the best available source of record:
- SEC 8-K/6-K/Form 4/13D/13D-A and actual exhibits
- company investor-relations press release
- FDA / government / court / exchange source
- filed earnings release / official transcript where available

Use web/news search to discover the reason quickly, then verify the material claim from a primary source when one
exists. A headline with no verifiable catalyst is not enough.

DISCOVERY — EVERY ACTIVE-MARKET RUN
Run the four saved explosive scanners by exact title when present:
- Agentic Catalyst Ignition v2
- Agentic Nuclear Volume v2
- Agentic Explosive Continuation v2
- Agentic Gap Catalyst v2

Their canonical parameters are in config.json -> scanner_profiles. If one is missing and the Robinhood scanner API
is available, create it from config before continuing. Do not silently substitute the older "Cheap Momentum" or
"Exceptional Momentum" rules as the primary discovery engine. Older scans may still be run as supplemental coverage.

Idle-cash fallback scanner (run only when the IDLE CASH ESCALATION below triggers):
- Agentic Early Catalyst Fallback v3

This fallback deliberately catches earlier/less-developed moves: lower RVOL and price-change thresholds than the four
primary scans. Standard candidates use the standard gate; during idle-cash escalation, fallback names may also qualify
under the tactical CASH DEPLOYMENT GATE.

IMPORTANT: do not bulk-dismiss fallback names as "unchanged." On every idle-cash run, current-run verify at least the
configured minimum number of distinct candidates. Any fallback name with >=8% same-day change, RVOL >=1.75x, market
cap <=$1B, or a material change since the prior run MUST get a current-run catalyst/news/filing check before rejection.
A prior-run "no catalyst" note is not sufficient when price/volume has materially changed.

The four jobs:
A. CATALYST IGNITION
   Find abnormal activity before the giant move whenever possible. Moderate price gain is enough if RVOL is strong.
B. NUCLEAR VOLUME
   Extreme relative volume even when price has not yet moved much. The purpose is to catch information discovery
   before price catches up.
C. EXPLOSIVE CONTINUATION
   Stocks already up materially. Investigate whether a real catalyst supports another leg instead of rejecting them
   just because they are already +20%, +50%, or more.
D. GAP CATALYST
   Significant gap + abnormal activity. Immediately determine why it gapped.

For every new or materially changed hit:
1. Get current quote/spread/tradability.
2. Verify the catalyst.
3. Check latest 8-K/6-K/10-Q/10-K/Form 4/13D as relevant.
4. Check dilution/supply and cash runway when material.
5. Evaluate RVOL/volume acceleration, VWAP/price discovery, and session-high behavior.
6. Build candidate.json and run opportunity-score.
7. Persist the result in candidates_seen with the new score fields and source references.

FAST PATH — CHEAP WHEN NOTHING CHANGED, BUT DO NOT MISS A NEW CATALYST
Steps 1 and 2 below are always full safety checks. The fast path may skip deep research only when discovery data
is genuinely unchanged.

1. Snapshot the account and open positions.
2. Verify every protective order.
3. Run the four v2 scanners plus any supplemental saved scanners.
4. Compare:
   - new symbols
   - materially higher RVOL/volume acceleration
   - new gap or new session-high behavior
   - fresh filing/primary-source event detected for a previously seen symbol
   - held position making a new high or crossing a winner-management zone
   - candidate score inputs materially changed
5. Build positions.json and live.json, then run:
   python3 scripts/scoring.py fast-check --positions positions.json --live live.json --config config.json --as-of <date>
6. If actionable=false, use the one-line NO_ACTION journal path and persist.
7. If actionable=true, research the tripped symbols/reasons deeply. If the reason includes IDLE_CASH_ESCALATION,
   V2_POSITION_RESCORE_DUE, or IDLE_CASH_CRITICAL, follow the mandatory escalation section below before NO_ACTION.
8. After completing an idle-cash escalation with no eligible deployment, set idle_cash_escalation_completed=true in
   live.json for the final fast-check/reconciliation so the same run may finish honestly without looping forever.

live.json may include:
{
  "stop_orders_ok": true,
  "new_high_any_position": false,
  "position_count_changed": false,
  "scanner_new_symbols": [],
  "scanner_acceleration_symbols": [],
  "fresh_filing_symbols": [],
  "winner_management_due": [],
  "candidate_score_inputs_changed": [],
  "drawdown_state_changed": false,
  "day_trade_count_changed": false,
  "account_value": 7500.0,
  "deployable_buying_power": 1500.0,
  "market_session": "regular_hours",
  "session_allows_entries": true,
  "entry_blocked": false,
  "entry_blocked_reason": "",
  "idle_cash_escalation_completed": false,
  "independent_catalyst_sweep_complete": false,
  "independent_catalyst_symbols_reviewed": [],
  "known_candidates": {
    "XYZ": {
      "current_run_deep_reviewed": true,
      "opportunity_score": 5.2,
      "cash_deployment_eligible": true
    }
  }
}

IDLE CASH ESCALATION — MANDATORY
The objective is not to sit on a large cash balance while the market is open. It is also not to force a bad trade.

Definitions:
- deployable_buying_power = unleveraged buying power actually usable for a new equity order now, minus
  min_cash_reserve_usd. Never count margin borrowing or unsettled/restricted funds as deployable.
- meaningful/strategic position = current market value >= strategic_position_min_usd. Fractional dust below that
  threshold remains tracked but does not consume one of max_open_positions strategic slots.
- idle_cash_pct = deployable_buying_power / total account value * 100.

Trigger:
- If session_allows_entries=true and idle_cash_pct >= idle_cash_escalation_pct_of_account (currently 2.5%), fast-check
  MUST return actionable until the required review is genuinely complete.
- At idle_cash_pct >= idle_cash_critical_pct_of_account (currently 6%), treat it as CRITICAL SEARCH DEPTH.
- idle_cash_escalation_completed is NOT trusted by itself. scripts/scoring.py validates that enough current-run deep
  reviews and independent catalyst checks are present. If not, it reports IDLE_CASH_REVIEW_INCOMPLETE.
- The target after a tactical deployment is <= idle_cash_target_pct_of_account (currently 1.5%), not "spend a little."

Before NO_ACTION is allowed under an idle-cash trigger, do ALL of the following:
1. V2 RE-UNDERWRITE THE EXISTING BOOK:
   Every meaningful open position lacking opportunity_score must be re-researched and assigned the v2 fields. This
   includes current quote/technicals, original thesis/catalyst verification, current dilution/bad-news check,
   remaining-upside assessment, and opportunity_score. Persist the v2 fields in state.json. Same-day holdings are
   still scored even though they cannot be sold.
2. PRIMARY SCANS:
   Run all four v2 scanners and fully evaluate every genuinely new/materially changed hit.
3. FALLBACK SCAN:
   Run "Agentic Early Catalyst Fallback v3". Investigate the highest-quality abnormal-volume names rather than
   dismissing the entire scan because some hits are junk.
4. FRESH-CATALYST SWEEP:
   Search primary/company/news sources for material developments from the last 48 hours, including 8-K/6-K,
   investor-relations releases, FDA/regulatory actions, earnings/guidance, contracts, licensing, activist filings,
   court decisions, and strategic transactions. A company investor-relations release IS a primary source even if an
   8-K has not yet appeared. Review at least idle_cash_min_independent_catalyst_checks distinct fresh candidates from
   a discovery channel independent of the Robinhood scanner list when the cash trigger is active.
5. DEEP-REVIEW QUOTA:
   Current-run deep-review at least idle_cash_min_candidates_deep_reviewed distinct candidates. A deep review means
   current quote/spread + current catalyst check + dilution/supply check when relevant + candidate.json scoring.
   Do not satisfy this quota by copying forward old rejection notes.
6. DEPLOYMENT CHOICES, in order:
   a. Best new candidate that clears the STANDARD opportunity gates.
   b. If none clears STANDARD and idle cash remains above target, the best candidate with
      cash_deployment_eligible=true MUST be bought with available cash, subject to hard broker/PDT/risk rules.
   c. A qualifying pyramid into an EXISTING WINNER may be used only if the winner is >= pyramid_min_unrealized_pct
      and refreshed opportunity/remaining-upside still clear the applicable gate.
   d. Rotation out of the weakest legally replaceable holding if a stronger candidate clears the rotation rule.
   Do not average down merely to deploy cash.
7. TACTICAL CASH POSITION SIZING:
   For a cash_deployment_eligible candidate, spend enough to move deployable cash toward
   idle_cash_target_pct_of_account, capped by tactical_cash_position_max_pct_of_account and buying power. Use
   tactical_cash_initial_stop_loss_pct for the initial stop if supported by the order workflow. Do not open a token
   position that leaves most of the cash untouched when a qualifying tactical candidate exists.
8. POSITION CEILING:
   Up to max_open_positions meaningful strategic positions are allowed (currently 5). Fractional dust below
   strategic_position_min_usd does not consume a strategic slot.
9. IF NOTHING QUALIFIES:
   Cash may remain idle only after the deep-review quota AND independent catalyst sweep are complete and NO standard
   or tactical cash-deployment candidate qualifies. Journal:
   IDLE_CASH_REVIEW_COMPLETE | idle_cash_pct=<x> | deployable=<amount> | deep_reviewed=<n> |
   independent_catalyst_checks=<n> | best_standard_rejected=<symbols/scores> |
   best_tactical_rejected=<symbols/scores> | reason=<why>
   (Valid ONLY under ZERO-IDLE-CASH rule 1(b).) Then set idle_cash_escalation_completed=true for this run. "Only two new names were web-checked" is NOT a valid
   completed idle-cash review.

NEAR-MISS WATCHLIST + INTER-RUN RECHECKS (owner directive 2026-10-07)
Hourly snapshots miss moves that start and fade between runs. To cover the gaps:
1. WATCHLIST. At the end of any run where idle-cash escalation was active, persist every candidate that was a near miss
   (opportunity_score >= tactical_cash_min_opportunity_score - 1.0, no hard disqualifier, verified catalyst) in
   state.json -> watchlist as {symbol, score, catalyst, ref_price, added_ts, trigger}. Trigger = the condition that would
   change the verdict (e.g. holds above a price with spread <= max_bid_ask_spread_pct and volume still accelerating).
   Drop entries after 3 trading days or on negative news.
2. FIRST STEP OF EVERY RUN. Before the scanners, re-quote every watchlist symbol and re-score it with
   scripts/scoring.py using current price/volume. A watchlist hit that is eligible (standard or cash_deployment_eligible)
   goes through the normal entry workflow. Re-scoring must use real current evidence, not a bumped input.
3. SERVER-SIDE ALERTS. When adding a watchlist entry, create a Robinhood price alert (create_alert) at its trigger price
   if the tool is available, and read get_alerts / get_alert_log at the start of the next run. Alerts are a hint only;
   every entry still needs the full quote/spread/catalyst/scoring check.
4. IN-SESSION RECHECKS. If idle_cash_pct >= idle_cash_escalation_pct_of_account, the market is in regular hours, and the
   watchlist is non-empty, do not end the run immediately after a NO_ACTION verdict. Run up to 3 additional
   watchlist-only rechecks about 10-15 minutes apart (background wait, then re-quote, re-score), stopping as soon as the
   market closes or a candidate qualifies. Each recheck is cheap: watchlist quotes + scoring.py only, no full scanner
   sweep unless a new scanner symbol appears in a quick re-run of the four v2 scans. Journal each recheck on one line.
5. RUN CADENCE. The routine schedule itself is set by the owner outside this repo. The owner has asked for denser
   coverage; when the schedule is changed to every 15-30 minutes during regular hours, rule 4 may be skipped
   because the schedule provides the rechecks. Scheduled runs must never edit the schedule, this file, or config.json.
6. Recheck runs obey every hard rule above (PDT, same-day lots, review_equity_order, protective stop, persistence).

V2 POSITION MIGRATION — NO GRANDFATHERED OLD SCORES
Until every meaningful position has v2 fields, the migration itself is actionable work.
- A meaningful position missing opportunity_score causes V2_POSITION_RESCORE_DUE in fast-check.
- Re-score it under the same framework used for new candidates, based on CURRENT remaining upside.
- Preserve historical old score fields for audit history but do not let them substitute for v2 fields.
- Fractional dust below strategic_position_min_usd is exempt from forced v2 migration unless it becomes material.

CHASE / "ALREADY UP A LOT" RULE
Do not use price appreciation alone as an automatic veto.

- Up >50% from the pre-catalyst/signal price: apply an exhaustion/chase penalty only if price discovery is weakening.
- Up >80%:
  - non-transformational catalyst: normally reject under the chase gate.
  - transformational catalyst: NOT an automatic rejection. It may remain eligible only if continuation is confirmed:
    strong abnormal volume, acceptable spread/liquidity, above-VWAP or equivalent healthy price discovery, and
    economics capable of supporting additional revaluation from the proposed entry.
- A +100% empty spike and a +100% stock after company-changing public news are not the same setup.
- Never chase simply because a stock is in a scanner. The 50%/100% labels must still be based on remaining upside.

UNIVERSE / LIQUIDITY
Broad hard universe comes from config.json:
- price >= min_price
- market cap >= min_market_cap_usd
- 30-day average volume >= min_avg_volume_30d_shares
- bid/ask spread <= max_bid_ask_spread_pct
- tradable and not financially deficient/delinquent/bankrupt
- earnings_blackout_trading_days applies as configured

The scanner profiles can be narrower than the broad hard universe.

SESSION SELECTION
Before any order, use the broker's market-hours/session information when available.
- Regular 09:30-16:00 ET: regular_hours. Marketable limit preferred.
- Extended 07:00-09:30 or 16:00-20:00 ET: limit orders only, extended_hours.
- Overnight 20:00-07:00 ET next weekday: only if explicitly 24-hour eligible; limit orders only, all_day_hours.
- Extended/overnight: do not pay ghost prints. Respect the spread cap and use a sane limit near the live market.
- If session selection is rejected, do not resubmit blindly. Journal SESSION_REJECT and wait for a valid session.

ROTATION — COMPARE REMAINING OPPORTUNITY
Use opportunity_score, not the old signal score, as the primary rotation metric.

Every held position should progressively acquire:
- signal_quality_score
- explosive_upside_score
- remaining_upside_score
- opportunity_score
- opportunity_class: transformational / durable / momentum
- opportunity_score_date

Until an older position is re-scored under v2, scripts/scoring.py caps its old one-dimensional score at
legacy_old_score_cap_for_opportunity so an old score-10 insider signal cannot permanently block a fresh catalyst.

Use:
  python3 scripts/scoring.py rotation --candidate-opportunity-score <N>     --positions positions.json --config config.json --as-of <date>

Rules:
- Compare only against the weakest legally replaceable holding.
- Same-day lots are never replaceable.
- Candidate must clear min_opportunity_score and beat the weakest holding by rotation_min_opportunity_advantage.
- If there is idle buying power, do not require a rotation just to use it.
- If multiple holdings tie, free the larger dollar position first, then the oldest.
- Re-verify current price/spread/tradability immediately before acting on a rotation.
- Selling a loser or winner is irrelevant by itself. Rotation is forward-looking.

SCORE FRESHNESS / DECAY
Three classes:
- transformational: verified company-changing catalyst. Slowest decay, but remaining_upside_score must still be
  refreshed when price materially reprices.
- durable: insider/13D/buyback/earnings-type information that remains relevant but fades.
- momentum: RVOL/top-gainer/options-only heat without a durable catalyst. Fast decay.

scripts/scoring.py is authoritative for decay. Do not hand-calculate it.

SIZING
Size by current opportunity_score after all hard gates:
- eligible but below opportunity_size_tier_mid: size_pct_low
- >= opportunity_size_tier_mid and < opportunity_size_tier_high: size_pct_mid
- >= opportunity_size_tier_high: size_pct_high

Budget remains capped by:
- max_position_pct_of_account
- spendable unleveraged buying power minus min_cash_reserve_usd
- broker restrictions

Up to max_open_positions meaningful strategic positions may be held. A position below strategic_position_min_usd is
fractional dust for slot-counting purposes, not a reason to block a new strategic position. It remains visible in
risk/state reporting.

100% single-name concentration remains allowed for an exceptional setup. Do not increase the cap beyond 100%.
Do not create tiny positions just to appear active. Conversely, if deployable cash is above the idle-cash threshold,
do not finish via the ordinary fast path until the mandatory escalation work is complete.

PYRAMIDING
Allowed only when:
- existing position is already a winner by at least pyramid_min_unrealized_pct
- no averaging down
- current opportunity_score remains >= min_opportunity_score
- remaining_upside_score still clears its gate
- no new dilution/bad-news issue
- the added lot does not create a PDT problem

WINNER MANAGEMENT — LET REAL RUNNERS RUN
Do not auto-sell merely because a name reaches +20%, +50%, +75%, or +100%.
Do not use the 50%/100% objective as a take-profit cap.

At each new high_since_entry:
1. Compute the high-water gain from entry.
2. Use config.json winner_stop_floors_pct to determine the minimum gain that should be protected.
3. Also calculate the ordinary trailing stop from trail_distance_pct.
4. New protective stop = the highest valid stop that:
   - never lowers the existing stop
   - protects at least the configured floor when technically possible
   - remains below the current market enough for the broker to accept
5. If normal small-cap volatility makes the configured floor impossible without placing the stop above/too near
   current market, do not force an invalid stop. Use the highest valid stop and journal the constraint.

Configured intent:
- once ~+20% has been achieved, try to eliminate a full-loss outcome
- ~+35%: protect a modest gain
- ~+50%: protect a meaningful gain
- ~+75%: protect a larger gain
- ~+100%: protect roughly half or more of the original gain while still leaving room for continuation

A negative catalyst overrides "let it run."

BAD-NEWS EXIT
After verifying a genuinely negative public development such as:
- active dilutive offering / unexpected financing pressure
- failed pivotal trial / adverse regulatory decision
- deal break
- major guidance cut
- insider-selling cluster that invalidates the thesis
- activist/13D exit
- material fraud/restatement/going-concern development

Exit a legally sellable position rather than waiting passively for the stop, subject to broker review and the
same-day-lot rule. Journal the verified source and reason.

DAY-TRADE GATE
Count every lot bought today as possible day-trade exposure because its protective stop can fire today.
Do not open a new position if:
  day trades in last 5 business days + same-day lots currently held
would exceed:
  day_trade_limit_rolling_5_days + 1
Defer to the next session instead.

ENTRY / EXECUTION
- review_equity_order, then place_equity_order.
- Prefer a marketable limit around the current ask during regular hours.
- Poll to verified fill <= 60 seconds. Cancel stale remainder if partial.
- If an entry does not fill at a sane price, move to the next ranked setup; do not repeatedly chase.
- Attach/verify the protective stop immediately after the fill.
- Persist score components, source links/filing IDs, session, entry thesis, 50%/100% labels, and rotation source.

PERSISTED CANDIDATE/POSITION FIELDS
New records should include, when known:
- signal_quality_score
- catalyst_magnitude_score
- volume_price_discovery_score
- structure_squeeze_score
- explosive_upside_score
- remaining_upside_score
- dilution_risk_score
- exhaustion_risk_score
- opportunity_score
- opportunity_class
- opportunity_score_date
- target_50_assessment
- target_100_assessment
- transformational
- continuation_confirmed
- catalyst_tier
- catalyst_summary
- primary_sources

Keep old score, score_signal_class, and score_date fields when present for historical compatibility; they are
no longer the primary ranking fields.

NO-ACTION SAVE PATH
NO_ACTION is permitted only if:
- fast-check returns actionable=false, AND
- there is no unresolved V2_POSITION_RESCORE_DUE, AND
- if deployable cash triggered idle-cash escalation, ZERO-IDLE-CASH rule 1(b) applies (hard block or no name clears best_available), AND
- no known candidate is standard, tactical or best_available eligible, AND
- no pending qualifying order/fill exists.

If those conditions are met:
- append the account_value_history point
- update last_run
- write a one-line journal entry:
  NO_ACTION | <ISO timestamp> | account_value=<$> | buying_power=<$> | positions_verified=<n>/<n> | reason=<short>
- persist per PERSISTENCE.md
- send no action email

OWNER EDIT AUTHORIZATION
Only an interactive, explicit owner request may modify these instruction/config/scoring files. When that occurs:
- edit only claude/trading-state
- state exactly what changed
- validate JSON/Python
- add/update tests for strategy logic
- never alter live trade state merely to make a test pass

STILL NEVER
- average down
- bypass broker review alerts
- claim unobserved fills
- intentionally sell a same-day lot
- act on MNPI
- skip protective-order verification
- use old score strength as a permanent blocker against a stronger current opportunity
- hard-reject a verified transformational catalyst solely because the stock is already up >80%
- call a setup "50%-100% potential" without explaining the remaining-upside case from the proposed entry
