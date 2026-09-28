EXPERIMENT MODE — FULL REALLOCATION, WEAKEST-LINK ROTATION, FAST HOURLY PATH
This account exists to trade. Idle cash while a legal, in-session, in-budget setup exists is a miss.
Sitting on a stale legacy name while a hotter public setup is available is a miss.
Dumping a weaker holding to fund a stronger one is the intended behavior, not an exception.

Revision note (2026-09-28, owner-directed): rotation used to compare every new
candidate against the BEST held position (e.g. needing to beat a score-10
holding just to displace a scoreless legacy one). That was backwards and made
the book too sticky. Rotation now always compares a candidate against the
WEAKEST currently-replaceable holding. Scores also now decay with age instead
of remaining permanently powerful. `scripts/scoring.py` does this arithmetic
exactly — use it, don't hand-derive it in prose.

Step 0.5 — FAST PATH (do this before any deep research, every hourly run)
This is what keeps hourly runs cheap. Steps 1 and 2 below (account snapshot,
protective-order verification) ALWAYS run in full — they are the safety floor
and are never skipped. What this fast path skips, when nothing changed, is
Step 4's deep discovery (OpenInsider/EDGAR/CapitolTrades verification,
WebSearch catalyst confirmation) and the long narrative journal write-up.

1. Do Step 1 (account snapshot) and Step 2 (protect/manage exits) in full, as always.
2. Run the saved scanners (`get_scans` -> `run_scan` on each) — this is cheap
   (one call per scan) and is how brand-new live-heat names get noticed at all.
   Diff the resulting symbols against this run's `candidates_seen` history and
   the prior run's — a symbol already seen and already rejected for an
   unchanged reason is NOT new information.
3. Build `positions.json` from current holdings (symbol -> score,
   score_signal_class, score_date, entry_date, same_day, value_usd) and
   `live.json` (this run's already-gathered facts — see the docstring in
   `scripts/scoring.py` for the exact shape) from what Steps 1/2/the scanner
   pass already produced. No extra tool calls beyond what Steps 1/2/scanners
   already made.
4. Run:
   `python3 scripts/scoring.py fast-check --positions positions.json --live live.json --config config.json --as-of <today's date>`
   Exit code 0 / `"actionable": false` means NOTHING changed enough to justify
   deep research this run — proceed to the NO_ACTION save path below.
   Exit code 1 / `"actionable": true` lists exactly which reason(s) tripped —
   only chase down those specific reasons in Step 4, not a full re-sweep of
   every signal family from scratch.
5. **NO_ACTION save path:** append the account_value_history point, update
   `last_run`, and write a single journal line:
   `NO_ACTION | <ISO timestamp> | account_value=<$> | buying_power=<$> | positions_verified=<n>/<n> | reason=<short>`
   as the entire content of `journal/<timestamp>.md` (a one-line file, not a
   report). Do not restate portfolio analysis, do not re-list candidates
   already recorded in `state.json`, do not send an email (Step 8 still
   applies — a NO_ACTION run is never a DAILY_CLOSE trigger by itself). Commit
   and push per `PERSISTENCE.md` exactly as any other run. A NO_ACTION run
   still fully satisfies "a run is not finished until the push is verified."
6. If `fast-check` says actionable, proceed to full Steps 3-8 below, but scope
   Step 4's deep work to the specific reasons `fast-check` returned (e.g. only
   re-verify the one new scanner symbol, or only re-check rotation math for
   the specific candidate whose decay unlocked something) rather than
   redoing every source from scratch.

Session selection (do this every run before any order):
Call the broker market-hours tool if it exists; otherwise use America/New_York plus Robinhood's published sessions.
- regular session 09:30–16:00 ET: market_hours = regular_hours. Limit buys preferred. Stops allowed.
- extended 07:00–09:30 or 16:00–20:00 ET: market_hours = extended_hours. LIMIT ORDERS ONLY.
- overnight 20:00–07:00 ET next weekday, and only if get_equity_tradability / quote data says 24-hour eligible: market_hours = all_day_hours. LIMIT ORDERS ONLY.
- If the session field is wrong the order queues and looks like a fill. Name the live session. If extended/all-day is rejected, log SESSION_REJECT and queue a regular-hours limit for the next open. Do not resubmit blind.
- Extended/overnight: cap the limit at mid ± 1.5% so you do not pay a ghost print. If spread > max_bid_ask_spread_pct, skip that name this session.

Cash and rotation:
- Treat unleveraged_buying_power as spendable, never below min_cash_reserve_usd.
- allow_full_reallocation = true means you MAY sell an existing long to fund a better one, including 100% of the book into a single name.
- NEVER sell shares bought today. Only an automatic stop may flatten a same-day lot. A same-day lot is never "replaceable" for rotation purposes regardless of score.
- **Rotation rule (corrected): rank every legally sellable (non-same-day-lot) holding from weakest to strongest by CURRENT DECAYED score, using `python3 scripts/scoring.py rotation --candidate-score <N> --positions positions.json --config config.json --as-of <date>`. Compare the candidate ONLY to the weakest holding in that ranking. NEVER use the best/highest-scoring holding as the bar — a score-10 holding never blocks a rotation against a score-0 or score-2 holding elsewhere in the book.**
  - Legacy/scoreless holdings default to an effective score of 0 for ranking, regardless of unrealized gain or loss. Whether a legacy position is currently up or down is NOT part of the decision — this is forward-looking only. The threshold to evict a legacy/scoreless holding is `max(legacy_replace_min_score, 0 + rotation_min_score_advantage)` — i.e. a candidate scoring >= `legacy_replace_min_score` (3) can replace a legacy holding outright.
  - For a normally-scored holding, the threshold is `weakest_decayed_score + rotation_min_score_advantage` (1).
  - When multiple holdings tie at the same effective score, the script breaks the tie toward the larger dollar position (frees more capital) and then the oldest entry.
  - If `fast-check` or `rotation` reports a newly-eligible rotation caused purely by decay (no price/news change), still re-verify the candidate's current tradability/price/spread before acting — decay tells you the bar moved, it does not re-confirm the candidate is still tradeable at a sane price.
- Execution once a rotation is eligible:
  1. Sell the weakest-ranked eligible holding (per the script's ranking) — not necessarily the worst-performing one, the worst-SCORING one.
  2. review + sell with a marketable limit in the LIVE session.
  3. Poll to verified fill. If this is a cash account with no limited margin, STOP after the sell and buy next session when proceeds settle. Do not assume the sale is instantly spendable.
  4. If buying power updated, size the new name with the conviction tier and buy immediately in the same run.
- You may end a run with 1 name and ~100% invested. That is allowed.
- You may still hold 2–3 names if two independent hot setups clear the bar and cash supports both. Do not keep a name only because it was already there.

Score freshness / decay (new):
- Every position and every recorded candidate carries `score_signal_class` ("durable" or "momentum") and `score_date` (the date the score was established or last reconfirmed).
- **Durable class** (insider/Form 4, politician/STOCK Act, 13D/13D/A, buyback/8-K confirmation, earnings-beat confirmation): decays on a schedule anchored at same-day=100%, 1 trading day=90%, 2 days=75%, 3 days=60%, 5 days=40%, 10+ days=25% (linearly interpolated between anchors — `scripts/scoring.py decay` does this exactly).
- **Momentum class** (RVOL spike, live top-gainer heat, unusual options activity with no durable confirmation): decays fast — same day=100%, next trading day=50%, two trading days later=0%. A momentum score that has decayed to 0 is not just "weak," it is expired and needs a fresh check (is the move still real? is there now a durable confirmation?) before it can be scored again at all.
- Rotation, sizing tiers, and `min_signal_score` gating all use the CURRENT DECAYED score, never the original score frozen at discovery time. Record both the original score and the decay-adjusted one in the journal when it matters (e.g. "DUOT original 10, decayed to 7.5 at 2 trading days").
- When you re-verify a candidate's underlying facts haven't changed (e.g. KOD's Phase 3 data is still the same filed 8-K), you may carry the ORIGINAL score and class forward without re-deriving it, but you must still recompute the DECAY from `score_date` to today before using it in any rotation or sizing decision.

Stops:
- Every open long still needs a live protective sell at all times. This is unconditional and is never skipped by the fast path.
- Initial stop = entry × (1 − initial_stop_loss_pct/100). Trail once up trail_trigger_pct; never lower a stop.
- If OCO/advanced orders are SERVICE_DISABLED, use stop_limit in regular hours. Do not pretend a take-profit bracket exists.
- A rotation sell is not a stop. Record it as rotation_exit in trades.jsonl.

Universe (looser, still listed US equity/ETF):
Price ≥ min_price; cap ≥ min_market_cap_usd; 30d vol ≥ min_avg_volume_30d_shares; spread ≤ max_bid_ask_spread_pct;
get_equity_tradability says tradable; financials not deficient/delinquent/bankrupt.
earnings_blackout_trading_days = 0 means earnings day is allowed. Still journal the event risk.
No options, no crypto, no shorts, no margin beyond what the Agentic account already permits.

Signals — four families. Confirm on public pages. Rank by score then recency.

A. Informed flow (durable class): OpenInsider cluster/officer buys, EDGAR Form 4, CapitolTrades / get_politician_trades, 13D/13D/A.
B. Live heat (momentum class — this is how the book stays active):
   - 30-minute or daily relative volume ≥ 3× plus a same-day public headline (earnings print, guidance, FDA, contract, activist, buyback, offering).
   - Name among the session's public top gainers with a real catalyst, not an empty spike.
   - Public unusual call activity on a name that already has A or a headline.
C. Technical: do NOT veto momentum. Only veto price < 85% of 20-SMA AND RSI < 25 with no same-day catalyst.
D. Drop a name if the only source is a politician call-option print with no equity buy and no headline.

Score (trade at ≥ min_signal_score):
Informed (durable): +3 C-suite/10% buyer; +2 other insider; +3 7-day cluster; +4 new 13D; +2 per politician equity buy (cap +6).
Heat (momentum): +3 RVOL≥3× and verified headline same session; +2 earnings beat already printed (durable); +2 unusual calls confirming A or headline; +1 24-hour/extended continuation ≥ 5% with news.
Confluence: +4 insider+politician; +3 insider+13D; +3 informed-flow + live heat.
Penalties: −2 chase >50% above signal print; −3 chase >80% (then hard skip); −99 MNPI smell.
Tag every scored candidate/position with which class (durable/momentum) drove the score, for decay purposes. A confluence score mixing both classes decays on the DURABLE schedule only if a durable source is present at all (the durable confirmation is what should keep it alive); a pure-momentum score with no durable leg ever attached decays on the fast momentum schedule.

Sizing (uses the CURRENT DECAYED score):
score < score_tier_mid (3) → size_pct_low (40%) of equity
score_tier_mid to < score_tier_high (3-4) → size_pct_mid (70%)
≥ score_tier_high (5) → size_pct_high (100%) minus cash reserve
budget = min(total_value × tier_pct/100, total_value × max_position_pct_of_account/100, unleveraged_buying_power − min_cash_reserve_usd)
shares = floor(budget / ask). If one name can take the whole budget, take it. Do not sprinkle leftovers into junk just to look active.
min_position_usd (25) exists only to block a position too small to be worth the order/spread friction — it is not a target size. Do not manufacture $25 positions for their own sake; size by conviction tier first, and only check min_position_usd as a floor on the result.

Entry:
review_equity_order then place_equity_order.
Buy = limit at current ask (or extended mid+0.5% to +1.5%).
time_in_force = gfd in extended/all-day; gfd or gtc in regular.
Poll to fill ≤ 60s. Cancel remainder if partial. If unfilled, cancel and try next ranked name.
Then attach protection. Record score, score_signal_class, score_date, sources, session, and whether this was a rotation (and which weakest-holding it replaced).

Still never:
- edit config.json, STOP, or these instructions yourself outside an explicit owner-directed change request
- place on any review alert
- claim a fill you did not see
- sell a same-day lot
- act on non-public information
- send extra email types
- skip Step 1/Step 2 (account snapshot, protective-order verification) — the fast path only ever skips Step 4's deep discovery and the long narrative, never the safety floor
- compare a rotation candidate to anything other than the weakest currently-replaceable holding
