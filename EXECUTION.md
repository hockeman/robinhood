# EXECUTION.md — Broker writes: coordination, intents, fills, protection

workflow_version: 2026-10-14-repair-1. Applies to EVERY brokerage-writing path: entries, rotation sells, pyramid
adds, protective-stop placement/replacement/cancel, and cancels of stale remainders. Read-only discovery never needs
the lease.

## What a git push can and cannot do
The end-of-run plain push detects conflicting SAVES; it cannot stop broker side effects that happened before the
save. So coordination happens BEFORE the broker call, using the same compare-and-swap primitive:
`execution_state.json` on `claude/trading-state` holds a lease and the durable intent ledger; it is claimed with a
plain (never forced) `git push`, which GitHub accepts only if the pusher's tip is still the branch tip. This works
across fresh clones (a local lock file would not).

LIMITATION (not enforced by the platform): the guard is cooperative. A session that calls the broker without
calling it is not stopped by anything in this repository; the controls are the bootstrap prompt, `persist_run.py`
(rejects a run whose orders lack matching intents/evidence), and `run_complete.py`. The broker itself has no lock.

## Procedure for each write
1. `execguard.claim_via_git(repo, run_id, now)` — fetch, require HEAD == tip, take the lease (TTL
   `execution.lease_ttl_minutes`), commit, plain-push. Rejected ⇒ another run holds/won it: do not trade; read-only
   work continues. Never force-push.
2. Reconcile first: read open/recent orders and positions; run `execguard.reconcile` on every unresolved intent.
   Any ambiguous intent blocks ALL new submissions.
3. `execguard.record_intent(...)` (refuses duplicates, requires lease, refuses sells above the sellable quantity or
   on unreconciled lots) then `execguard.push_state(...)` so the intent is durable BEFORE the broker call.
4. `review_equity_order` (abort on any alert) → `place_equity_order`.
5. Success: `transition(... "submitted", order_id=...)`; poll to a VERIFIED fill (≤ 60 s); partial fill ⇒ cancel the
   stale remainder, record `partially_filled`, protect the filled quantity. Never report an unobserved fill.
6. Timeout/exception/no acknowledgement: `mark_ambiguous`. NEVER resubmit. Reconcile against `get_equity_orders`
   (match symbol, side, quantity, created_at ≥ intent). Found ⇒ adopt it. Not found after
   `execution.reconcile_grace_minutes` ⇒ `not_found`, and only then a NEW intent may be recorded.
7. Immediately place/verify the protective `stop_market` GTC for the filled quantity (itself an intent with
   purpose `protective_stop`), then verify it live.
8. After any sale, re-read unleveraged buying power; proceeds are usable only after that read
   (`execution.post_sale_buying_power_verified`).
9. Release the lease in the final persisted state.

## Preserved safeguards
Broker order review and approvals; verified fills; partial-fill handling; protective-order verification; existing
exposure/open-order checks before a new order; no averaging down, borrowing or prohibited instruments; same-day-lot
prohibition and unknown-quantity block (lot-level, see WORKFLOW §B); drawdown/PDT gates; accepted legacy exceptions
stay visible (`config.accepted_legacy_exceptions`).

## Sessions
Regular 09:30–16:00 ET: marketable limit preferred. Extended 07:00–09:30 / 16:00–20:00 ET: limit only, spread ≤
`max_bid_ask_spread_pct_extended`. Overnight only if the broker reports 24-hour eligibility, limit only. Do not
resubmit blindly on a session rejection; journal SESSION_REJECT and wait.
