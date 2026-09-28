#!/usr/bin/env python3
"""
Deterministic scoring/decay/rotation helper for the autonomous trading agent.

Why this exists: rotation math and score decay used to be re-derived by hand,
in prose, every hourly run -- expensive in tokens and prone to drift (e.g. the
old rule silently compared every candidate against the BEST held position
instead of the weakest replaceable one). This script makes that arithmetic
exact, cheap, and testable, so an hourly run can call it once and get a
machine-readable verdict instead of re-reasoning it out.

This script has NO network access and does not place or read live orders.
It only operates on JSON already gathered by the agent this run (from the
required Step 1/Step 2 tool calls, which always run regardless of the fast
path -- see AGENT.md). It never decides safety-critical things (stop
presence, PDT counts, review-before-place) -- those stay as explicit tool
calls and hard rules in AGENT.md.

Usage:
  python3 scripts/scoring.py decay --score 8 --class durable --days-old 2
  python3 scripts/scoring.py rotation --candidate-score 6 --positions positions.json \
      --config ../config.json --as-of 2026-09-28
  python3 scripts/scoring.py fast-check --positions positions.json --live live.json \
      --config ../config.json --as-of 2026-09-28

`positions.json` shape (a dict, one entry per open position -- matches
state.json's "positions" map plus two new fields used only for decay):
  {
    "DUOT": {
      "score": 10,
      "score_signal_class": "durable",   // "durable" or "momentum"
      "score_date": "2026-09-24",        // date the score was established/last confirmed
      "entry_date": "2026-09-24",
      "same_day": false,                  // true = bought today, never sellable (PDT)
      "value_usd": 1850.0                 // current market value, used only as a tie-break
    },
    "MSTR": {"score": null, "legacy": true, "entry_date": "2026-09-18", "same_day": false, "value_usd": 3600.0}
  }

`live.json` shape for fast-check (everything the agent already pulled this run):
  {
    "account_value": 7399.99,
    "buying_power": 122.23,
    "stop_orders_ok": true,               // every open position has a verified live protective order
    "new_high_any_position": false,       // any position made a new high_since_entry (trailing-stop trigger)
    "position_count_changed": false,      // a position appeared/disappeared vs last state.json
    "scanner_new_symbols": ["KOD"],       // symbols surfaced by the saved scanners not already in candidates_seen
    "drawdown_state_changed": false,      // halted/resumed transition since last run
    "day_trade_count_changed": false
  }
"""
import argparse
import bisect
import json
import sys
from datetime import date, datetime, timedelta

DURABLE_ANCHORS = [(0, 1.00), (1, 0.90), (2, 0.75), (3, 0.60), (5, 0.40), (10, 0.25)]
MOMENTUM_ANCHORS = [(0, 1.00), (1, 0.50), (2, 0.0)]

DEFAULT_LEGACY_REPLACE_MIN_SCORE = 3
DEFAULT_LEGACY_DEFAULT_SCORE = 0


def _parse_date(d):
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    return datetime.strptime(d, "%Y-%m-%d").date()


def trading_days_between(start, end):
    """Count weekday (Mon-Fri) steps between start and end, exclusive of start.
    Does not account for market holidays -- close enough for decay purposes;
    a holiday just makes something decay one notch slower than ideal, never faster.
    """
    start = _parse_date(start)
    end = _parse_date(end)
    if end <= start:
        return 0
    days = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:  # Mon-Fri
            days += 1
    return days


def _interpolate(anchors, days_old):
    xs = [a[0] for a in anchors]
    if days_old <= xs[0]:
        return anchors[0][1]
    if days_old >= xs[-1]:
        return anchors[-1][1]
    i = bisect.bisect_right(xs, days_old) - 1
    x0, y0 = anchors[i]
    x1, y1 = anchors[i + 1]
    frac = (days_old - x0) / (x1 - x0)
    return y0 + frac * (y1 - y0)


def decay_multiplier(signal_class, days_old):
    if signal_class == "momentum":
        return _interpolate(MOMENTUM_ANCHORS, days_old)
    return _interpolate(DURABLE_ANCHORS, days_old)  # default: treat unknown classes as durable (conservative)


def decayed_score(base_score, signal_class, score_date, as_of):
    if base_score is None:
        return 0.0
    days_old = trading_days_between(score_date, as_of)
    return round(base_score * decay_multiplier(signal_class, days_old), 3)


def effective_score(position, as_of, legacy_default_score=DEFAULT_LEGACY_DEFAULT_SCORE):
    """A position's current, decayed score for ranking purposes.
    Legacy/scoreless positions default to legacy_default_score (0) regardless
    of how they perform in price, per the "forward-looking, not P&L-based" rule.
    """
    if position.get("legacy") or position.get("score") is None:
        return float(legacy_default_score)
    return decayed_score(
        position["score"],
        position.get("score_signal_class", "durable"),
        position.get("score_date") or position.get("entry_date"),
        as_of,
    )


def replaceable_holdings(positions, as_of):
    """Rank all non-same-day-lot holdings weakest to strongest by decayed score.
    Ties broken by largest dollar value first (unlocks more capital), then by
    oldest entry_date (clear out the stalest holding first).
    Same-day lots are excluded entirely -- PDT rule, never sell a same-day buy
    except via an automatic stop.
    """
    rows = []
    for symbol, pos in positions.items():
        if pos.get("same_day"):
            continue
        rows.append(
            {
                "symbol": symbol,
                "effective_score": effective_score(pos, as_of),
                "legacy": bool(pos.get("legacy") or pos.get("score") is None),
                "value_usd": pos.get("value_usd", 0.0),
                "entry_date": pos.get("entry_date"),
            }
        )
    rows.sort(key=lambda r: (r["effective_score"], -r["value_usd"], r["entry_date"] or ""))
    return rows


def rotation_eligible(
    candidate_score,
    positions,
    as_of,
    rotation_min_score_advantage=1,
    legacy_replace_min_score=DEFAULT_LEGACY_REPLACE_MIN_SCORE,
    min_signal_score=2,
):
    """Return a verdict dict. Never compares the candidate to the BEST holding --
    only ever to the weakest currently-replaceable one, per the corrected rule.
    """
    if candidate_score < min_signal_score:
        return {"eligible": False, "reason": f"candidate_score {candidate_score} < min_signal_score {min_signal_score}"}

    replaceable = replaceable_holdings(positions, as_of)
    if not replaceable:
        return {"eligible": False, "reason": "no replaceable holdings (all positions are same-day lots, or none held)"}

    weakest = replaceable[0]
    if weakest["legacy"]:
        threshold = max(legacy_replace_min_score, weakest["effective_score"] + rotation_min_score_advantage)
    else:
        threshold = weakest["effective_score"] + rotation_min_score_advantage

    eligible = candidate_score >= threshold
    return {
        "eligible": eligible,
        "weakest_symbol": weakest["symbol"],
        "weakest_effective_score": weakest["effective_score"],
        "weakest_is_legacy": weakest["legacy"],
        "threshold": threshold,
        "candidate_score": candidate_score,
        "full_ranking": replaceable,
        "reason": (
            f"candidate {candidate_score} >= threshold {threshold} (weakest={weakest['symbol']} "
            f"@ {weakest['effective_score']}{' [legacy]' if weakest['legacy'] else ''})"
            if eligible
            else f"candidate {candidate_score} < threshold {threshold} (weakest={weakest['symbol']} "
            f"@ {weakest['effective_score']}{' [legacy]' if weakest['legacy'] else ''})"
        ),
    }


def fast_check(positions, live, as_of, config):
    """Decide whether an hourly run needs to do deep research at all.
    Returns {"actionable": bool, "reasons": [...]} -- reasons is empty only
    when actionable is False (a clean NO_ACTION run).
    """
    reasons = []

    if not live.get("stop_orders_ok", True):
        reasons.append("STOP_ORDER_PROBLEM: a required protective order is missing or unconfirmed")
    if live.get("new_high_any_position"):
        reasons.append("TRAILING_STOP_DUE: a position made a new high since entry, stop may need to trail up")
    if live.get("position_count_changed"):
        reasons.append("POSITION_CHANGE: a position appeared or disappeared since last run (fill/stop-out)")
    if live.get("drawdown_state_changed"):
        reasons.append("DRAWDOWN_STATE_CHANGED: halt/resume threshold crossed")
    if live.get("day_trade_count_changed"):
        reasons.append("DAY_TRADE_COUNT_CHANGED: PDT counter moved, re-verify gate")

    new_symbols = live.get("scanner_new_symbols") or []
    if new_symbols:
        reasons.append(f"NEW_SCANNER_HIT: {', '.join(new_symbols)} not previously seen, needs verification")

    # Recompute decay on every known position/candidate: did anything cross a
    # rotation threshold purely because a held score decayed, with no price/news change at all?
    replaceable = replaceable_holdings(positions, as_of)
    for cand_symbol, cand in (live.get("known_candidates") or {}).items():
        verdict = rotation_eligible(
            cand.get("score", 0),
            positions,
            as_of,
            rotation_min_score_advantage=config.get("rotation_min_score_advantage", 1),
            legacy_replace_min_score=config.get("legacy_replace_min_score", DEFAULT_LEGACY_REPLACE_MIN_SCORE),
            min_signal_score=config.get("min_signal_score", 2),
        )
        if verdict["eligible"]:
            reasons.append(
                f"ROTATION_NOW_OPEN: {cand_symbol} (score {cand.get('score')}) newly clears the bar "
                f"against {verdict['weakest_symbol']} (decayed to {verdict['weakest_effective_score']}) "
                "purely from score decay/rank change -- verify and consider entry"
            )

    return {"actionable": bool(reasons), "reasons": reasons, "current_ranking": replaceable}


def _load(path):
    with open(path) as f:
        return json.load(f)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decay", help="Compute a single decayed score")
    d.add_argument("--score", type=float, required=True)
    d.add_argument("--class", dest="signal_class", choices=["durable", "momentum"], required=True)
    d.add_argument("--days-old", type=int, required=True)

    r = sub.add_parser("rotation", help="Check whether a candidate can rotate into the book")
    r.add_argument("--candidate-score", type=float, required=True)
    r.add_argument("--positions", required=True, help="path to positions.json")
    r.add_argument("--config", required=True, help="path to config.json")
    r.add_argument("--as-of", required=True, help="YYYY-MM-DD")

    fc = sub.add_parser("fast-check", help="Decide whether an hourly run needs deep research")
    fc.add_argument("--positions", required=True)
    fc.add_argument("--live", required=True, help="path to live.json (this run's already-gathered facts)")
    fc.add_argument("--config", required=True)
    fc.add_argument("--as-of", required=True)

    args = p.parse_args()

    if args.cmd == "decay":
        print(json.dumps({"decayed_score": round(args.score * decay_multiplier(args.signal_class, args.days_old), 3)}))
        return

    if args.cmd == "rotation":
        positions = _load(args.positions)
        config = _load(args.config)
        verdict = rotation_eligible(
            args.candidate_score,
            positions,
            args.as_of,
            rotation_min_score_advantage=config.get("rotation_min_score_advantage", 1),
            legacy_replace_min_score=config.get("legacy_replace_min_score", DEFAULT_LEGACY_REPLACE_MIN_SCORE),
            min_signal_score=config.get("min_signal_score", 2),
        )
        print(json.dumps(verdict, indent=2))
        return

    if args.cmd == "fast-check":
        positions = _load(args.positions)
        live = _load(args.live)
        config = _load(args.config)
        result = fast_check(positions, live, args.as_of, config)
        print(json.dumps(result, indent=2))
        sys.exit(0 if not result["actionable"] else 1)  # exit code doubles as a shell-friendly flag


if __name__ == "__main__":
    main()
