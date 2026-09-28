# Owner-directed configuration change — 2026-09-28 (live session, not a scheduled hourly run)

The owner directed a rewrite of the rotation logic, legacy-position handling,
score freshness, position-size floor, and hourly research cost, in a live
chat session (not the automated scheduler). Implemented directly; no trade
was placed in this session — the next scheduled hourly run acts on the new
rules with live prices re-verified at that time.

## What changed and why

**1. Rotation logic (the core bug fix).** The old rule compared every new
candidate against the BEST held position's score (e.g. DUOT=10 meant any
candidate needed to score >=12 to displace ANYTHING, including a scoreless
legacy holding). That made the book effectively immovable — confirmed live
today: KOD (score 3, a real verified live-heat catalyst) sat rejected across
at least 4 consecutive hourly runs purely because DUOT was strong, even
though MSTR (legacy, scoreless, decayed to 0) was sitting right there.
Rotation now ranks all legally-sellable holdings weakest-to-strongest by
CURRENT DECAYED score and compares the candidate only to the weakest one.
`rotation_min_score_advantage` dropped from 2 to 1 for normally-scored
holdings; a separate `legacy_replace_min_score` (3) governs evicting a
legacy/scoreless holding. Verified against the real production state.json:
KOD's real score of 3 is now correctly rotation-eligible against MSTR.

**2. Legacy/scoreless positions.** Now default to an effective score of 0 for
ranking, full stop — no more "must be down or flat first" gate. Whether MSTR
is up or down since entry is irrelevant to whether it should keep holding
capital; only forward-looking score matters now.

**3. Score decay.** New `score_signal_class` ("durable" | "momentum") and
`score_date` fields on every position/candidate. Durable (insider/politician/
13D/earnings-beat) scores decay on a slow schedule (100% same day, 90% at 1
trading day, 75% at 2, 60% at 3, 40% at 5, 25% at 10+, linearly interpolated).
Momentum (RVOL/live-heat) scores decay fast (100% same day, 50% next day, 0%
two days out) and effectively expire, requiring re-verification. This is what
stops a stale high score from permanently blocking better opportunities, and
stops a momentum spike from being treated as durable conviction days later.

**4. Position-size floor.** `min_position_usd` 100 -> 25, `min_cash_reserve_usd`
10 -> 5. Purpose is only to stop valid entries being refused over cash
friction, not to manufacture $25 positions — AGENT.md says this explicitly.

**5. Aggressive/concentrated settings confirmed/applied:**
`max_pyramids_per_position` 2->3, `pyramid_min_unrealized_pct` 5->4. All other
requested settings (max_position_pct_of_account=100, max_open_positions=3,
max_new_positions_per_run=3, min_price=1, min_market_cap_usd=25M,
min_avg_volume_30d_shares=100k, max_bid_ask_spread_pct=4.0, min_signal_score=2,
allow_pyramid_winners=true, allow_full_reallocation=true,
allow_extended_hours_entries=true, allow_all_day_hours_entries=true,
single_name_ok=true, score_tier_mid=3, score_tier_high=5, size_pct_low=40,
size_pct_mid=70, size_pct_high=100) were already in place from the prior
EXPERIMENT MODE revision and are unchanged.

**6. Fast hourly path.** New AGENT.md "Step 0.5" and `scripts/scoring.py
fast-check`. Steps 1-2 (account snapshot, protective-order verification)
still run in full, every run, unconditionally — this was never in scope to
cut and was not touched. What's now skippable when nothing material changed:
Step 4's deep OpenInsider/EDGAR/CapitolTrades verification and WebSearch
catalyst confirmation, and the long narrative journal write-up. A quiet run
now persists a single line:
`NO_ACTION | <timestamp> | account_value=<$> | buying_power=<$> | positions_verified=<n>/<n> | reason=<short>`
instead of a multi-paragraph report. The saved scanners (cheap, ~4 calls)
still run every hour so brand-new momentum names are never missed — the
expensive verification work is what's gated, not discovery entirely.

## What was NOT changed (explicitly preserved per the owner's instruction)

- One account only, equities-only, no options/crypto/shorts/margin beyond
  what the Agentic account already permits.
- Every open position must have a live, verified protective stop at all
  times — Step 2 is unconditional and is never part of the fast-path skip.
- Review-before-place and abort-on-any-alert for every order.
- PDT: same-day lots are still never sellable except via automatic stop; day
  trade counting and the 2-per-5-business-days limit are unchanged; a
  same-day lot is explicitly excluded from the rotation ranking in
  `scripts/scoring.py` (`same_day: true` positions are filtered out before
  ranking).
- The kill switch (`STOP` file) is unchanged.
- State persistence protocol (`PERSISTENCE.md`'s fetch/checkout/commit/push/
  verify sequence) is unchanged; this change was itself committed through
  that exact protocol.
- The owner's own instruction to never edit `config.json`/`AGENT.md`/`STOP`
  autonomously is preserved — this edit was made because the owner explicitly
  directed it in this session, not autonomously.

## Files changed
- `config.json`: `min_position_usd`, `min_cash_reserve_usd`,
  `rotation_min_score_advantage`, `max_pyramids_per_position`,
  `pyramid_min_unrealized_pct`; added `legacy_default_score`,
  `legacy_replace_min_score`, `durable_score_decay`, `momentum_score_decay`.
- `AGENT.md`: rewrote the rotation section (weakest-holding comparison,
  legacy default-score-0, decay-aware thresholds), added the decay section,
  added Step 0.5 fast path, updated sizing/entry notes to reference decayed
  scores and `scripts/scoring.py`.
- `scripts/scoring.py` (new): deterministic decay/rotation/fast-check helper.
  No network access; operates only on JSON already gathered by the agent each
  run. Unit-tested against the owner's own worked example (candidate score 6
  vs DUOT=10/SBLK=5/MSTR=legacy) and against the real production
  state.json/config.json (KOD's real score of 3 is now correctly
  rotation-eligible against MSTR).
- `state.json`: backfilled `score_signal_class`, `score_date`, `legacy`,
  `same_day` on existing positions (MSTR, SBLK, DUOT, ANGX) so the very next
  hourly run can use the new script without re-deriving these facts from
  history. No position, order, or score value itself was changed — this is
  metadata backfill only.

## Tests/checks run
- `python3 -m py_compile scripts/scoring.py` — clean.
- `json.load()` on `config.json`, `state.json`, `notification_state.json`
  after edits — all parse cleanly.
- Unit checks: durable decay at 0/2/10 trading days (100%/75%/25% — matches
  spec); momentum decay at 0/1/2 trading days (100%/50%/0% — matches spec).
- Rotation checks: owner's worked example (candidate 6 vs
  DUOT=10/SBLK=5/MSTR=legacy) correctly resolves eligible against MSTR;
  a sub-floor candidate (score 2) correctly rejected; real production data
  (KOD=3 vs the actual current book) correctly resolves eligible against
  MSTR, with SBLK/DUOT correctly ranked above it by decayed score.
- `fast-check` dry run against synthetic "nothing changed" input returns
  `actionable: false` / exit 0; against input with known higher-scoring
  candidates still on file, correctly flags `ROTATION_NOW_OPEN` for KOD/GME
  now that decay has moved the weakest-holding bar — i.e. the next real
  hourly run should surface this as actionable, not silently skip it.

## Note for the next scheduled hourly run
Under the new rules, KOD (last real score 3, momentum class, needs a fresh
`score_date`/price/tradability re-check since time has passed) is already
rotation-eligible against MSTR (legacy, effective score 0) per
`scripts/scoring.py`. The next run should re-verify KOD's current price,
spread, and that the catalyst facts are unchanged, recompute sizing off the
current decayed score, and — if it still clears the universe/chase/technical
gates — execute the rotation (sell MSTR via marketable limit, verify fill,
buy KOD sized to the appropriate conviction tier, attach a protective stop
immediately). This is not an instruction to skip verification — only the
rotation-bar math has changed; every execution safeguard in AGENT.md
(review-before-place, poll-to-fill, immediate stop attachment, PDT same-day
check) still applies in full.
