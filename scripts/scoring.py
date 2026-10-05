#!/usr/bin/env python3
"""
Deterministic scoring/decay/rotation helper for the autonomous trading agent.

The v2 strategy separates evidence quality from explosive upside and remaining
upside. The purpose is to prevent an old high insider/flow score from
mechanically outranking a fresh transformational catalyst.

This script has NO network access and does not place or read live orders. It
only evaluates JSON already gathered by the agent. Broker safety, PDT, order
review, fill verification, protective stops, and tradability remain hard rules
in AGENT.md.

Commands:
  python3 scripts/scoring.py opportunity-score --candidate candidate.json --config config.json
  python3 scripts/scoring.py decay --score 8 --class transformational --days-old 2
  python3 scripts/scoring.py rotation --candidate-opportunity-score 8.4 \
      --positions positions.json --config config.json --as-of 2026-10-05
  python3 scripts/scoring.py fast-check --positions positions.json --live live.json \
      --config config.json --as-of 2026-10-05

candidate.json shape:
  {
    "symbol": "XYZ",
    "signal_quality_score": 0-10,
    "catalyst_magnitude_score": 0-10,
    "volume_price_discovery_score": 0-10,
    "structure_squeeze_score": 0-10,
    "remaining_upside_score": 0-10,
    "dilution_risk_score": 0-10,
    "exhaustion_risk_score": 0-10,
    "primary_source_verified": true,
    "catalyst_verified": true,
    "transformational": true,
    "continuation_confirmed": true,
    "chase_pct": 75.0,
    "disqualifier": false,
    "disqualifier_reason": ""
  }

positions.json shape:
  {
    "DUOT": {
      "opportunity_score": 7.2,
      "opportunity_class": "durable",
      "opportunity_score_date": "2026-10-05",
      "entry_date": "2026-09-24",
      "same_day": false,
      "value_usd": 1850.0,

      "... historical compatibility ...": "...",
      "score": 10,
      "score_signal_class": "durable",
      "score_date": "2026-09-24"
    }
  }

Old positions without v2 opportunity fields are intentionally capped by
legacy_old_score_cap_for_opportunity from config so an old one-dimensional
score cannot permanently block a fresh explosive catalyst.

live.json may include:
  {
    "stop_orders_ok": true,
    "new_high_any_position": false,
    "position_count_changed": false,
    "scanner_new_symbols": ["KOD"],
    "scanner_acceleration_symbols": [],
    "fresh_filing_symbols": [],
    "winner_management_due": [],
    "candidate_score_inputs_changed": [],
    "drawdown_state_changed": false,
    "day_trade_count_changed": false,
    "known_candidates": {
      "XYZ": {
        "opportunity_score": 7.8,
        "opportunity_class": "transformational",
        "opportunity_score_date": "2026-10-05"
      }
    }
  }
"""
import argparse
import bisect
import json
import sys
from datetime import date, datetime, timedelta

DURABLE_ANCHORS = [(0, 1.00), (1, 0.90), (2, 0.75), (3, 0.60), (5, 0.40), (10, 0.25)]
MOMENTUM_ANCHORS = [(0, 1.00), (1, 0.50), (2, 0.0)]
TRANSFORMATIONAL_ANCHORS = [
    (0, 1.00),
    (1, 0.95),
    (2, 0.90),
    (3, 0.85),
    (5, 0.75),
    (10, 0.60),
    (20, 0.40),
]

DEFAULT_LEGACY_REPLACE_MIN_SCORE = 3
DEFAULT_LEGACY_DEFAULT_SCORE = 0
DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY = 4.0


def _parse_date(d):
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    return datetime.strptime(d, "%Y-%m-%d").date()


def _clamp(value, lo=0.0, hi=10.0):
    return max(lo, min(hi, float(value)))


def _number(mapping, key, default=0.0):
    value = mapping.get(key, default)
    if value is None:
        return float(default)
    return float(value)


def trading_days_between(start, end):
    """Count weekday steps between start and end, exclusive of start."""
    start = _parse_date(start)
    end = _parse_date(end)
    if end <= start:
        return 0
    days = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
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
    if signal_class == "transformational":
        return _interpolate(TRANSFORMATIONAL_ANCHORS, days_old)
    return _interpolate(DURABLE_ANCHORS, days_old)


def decayed_score(base_score, signal_class, score_date, as_of):
    if base_score is None:
        return 0.0
    days_old = trading_days_between(score_date, as_of)
    return round(float(base_score) * decay_multiplier(signal_class, days_old), 3)


def classify_50_upside(explosive, remaining, opportunity):
    if explosive >= 9.0 and remaining >= 8.5 and opportunity >= 8.5:
        return "unusually_plausible"
    if explosive >= 8.0 and remaining >= 7.0 and opportunity >= 7.5:
        return "plausible"
    if explosive >= 6.0 and remaining >= 5.0 and opportunity >= 6.0:
        return "possible"
    return "implausible"


def classify_100_upside(explosive, remaining, opportunity):
    if explosive >= 9.5 and remaining >= 9.0 and opportunity >= 9.0:
        return "unusually_plausible"
    if explosive >= 9.0 and remaining >= 8.0 and opportunity >= 8.5:
        return "plausible"
    if explosive >= 7.5 and remaining >= 6.5 and opportunity >= 7.0:
        return "possible"
    return "implausible"


def opportunity_score(candidate, config):
    """
    Return v2 opportunity scoring.

    Weighting deliberately makes explosive upside + remaining upside 85% of
    the pre-penalty composite. Signal quality is still a hard gate and still
    contributes 15%, but cannot dominate the ranking by itself.
    """
    signal_quality = _clamp(_number(candidate, "signal_quality_score"))
    catalyst_magnitude = _clamp(_number(candidate, "catalyst_magnitude_score"))
    volume_price_discovery = _clamp(_number(candidate, "volume_price_discovery_score"))
    structure_squeeze = _clamp(_number(candidate, "structure_squeeze_score"))
    remaining = _clamp(_number(candidate, "remaining_upside_score"))
    dilution_risk = _clamp(_number(candidate, "dilution_risk_score"))
    exhaustion_risk = _clamp(_number(candidate, "exhaustion_risk_score"))

    explosive = _clamp(
        0.50 * catalyst_magnitude
        + 0.30 * volume_price_discovery
        + 0.20 * structure_squeeze
    )

    risk_penalty = 0.25 * dilution_risk + 0.15 * exhaustion_risk
    opportunity = _clamp(
        0.15 * signal_quality
        + 0.45 * explosive
        + 0.40 * remaining
        - risk_penalty
    )

    min_signal_quality = float(config.get("min_signal_quality_score", 4.0))
    min_explosive = float(config.get("min_explosive_upside_score", 6.0))
    min_remaining = float(config.get("min_remaining_upside_score", 5.0))
    min_opportunity = float(config.get("min_opportunity_score", 6.0))
    chase_gate = float(config.get("max_chase_pct_above_signal_price", 80))

    reasons = []
    if not candidate.get("primary_source_verified", False):
        reasons.append("primary source not verified")
    if not candidate.get("catalyst_verified", False):
        reasons.append("catalyst not verified")
    if signal_quality < min_signal_quality:
        reasons.append(f"signal_quality_score {signal_quality:.2f} < {min_signal_quality:.2f}")
    if explosive < min_explosive:
        reasons.append(f"explosive_upside_score {explosive:.2f} < {min_explosive:.2f}")
    if remaining < min_remaining:
        reasons.append(f"remaining_upside_score {remaining:.2f} < {min_remaining:.2f}")
    if opportunity < min_opportunity:
        reasons.append(f"opportunity_score {opportunity:.2f} < {min_opportunity:.2f}")

    disqualifier = bool(candidate.get("disqualifier", False))
    if disqualifier:
        reasons.append(
            "hard disqualifier"
            + (f": {candidate.get('disqualifier_reason')}" if candidate.get("disqualifier_reason") else "")
        )

    chase_pct = float(candidate.get("chase_pct", 0.0) or 0.0)
    transformational = bool(candidate.get("transformational", False))
    continuation_confirmed = bool(candidate.get("continuation_confirmed", False))
    if chase_pct > chase_gate:
        if not transformational:
            reasons.append(
                f"non-transformational chase {chase_pct:.1f}% > configured {chase_gate:.1f}% gate"
            )
        elif not continuation_confirmed:
            reasons.append(
                f"transformational chase {chase_pct:.1f}% requires continuation confirmation"
            )

    eligible = not reasons

    high = float(config.get("high_conviction_opportunity_score", 8.0))
    exceptional = float(config.get("exceptional_opportunity_score", 9.0))
    if not eligible:
        tier = "reject"
    elif opportunity >= exceptional:
        tier = "exceptional"
    elif opportunity >= high:
        tier = "high"
    else:
        tier = "qualified"

    return {
        "symbol": candidate.get("symbol"),
        "eligible": eligible,
        "signal_quality_score": round(signal_quality, 3),
        "explosive_upside_score": round(explosive, 3),
        "remaining_upside_score": round(remaining, 3),
        "opportunity_score": round(opportunity, 3),
        "risk_penalty": round(risk_penalty, 3),
        "target_50_assessment": classify_50_upside(explosive, remaining, opportunity),
        "target_100_assessment": classify_100_upside(explosive, remaining, opportunity),
        "opportunity_tier": tier,
        "transformational": transformational,
        "continuation_confirmed": continuation_confirmed,
        "chase_pct": round(chase_pct, 3),
        "reasons": reasons,
    }


def _base_opportunity_score(position, legacy_default_score, legacy_old_score_cap):
    if position.get("opportunity_score") is not None:
        return float(position["opportunity_score"]), False
    if position.get("legacy") or position.get("score") is None:
        return float(legacy_default_score), True
    return min(float(position["score"]), float(legacy_old_score_cap)), True


def effective_opportunity_score(
    position,
    as_of,
    legacy_default_score=DEFAULT_LEGACY_DEFAULT_SCORE,
    legacy_old_score_cap=DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY,
):
    base, _legacy_v2 = _base_opportunity_score(position, legacy_default_score, legacy_old_score_cap)
    score_date = (
        position.get("opportunity_score_date")
        or position.get("score_date")
        or position.get("entry_date")
        or as_of
    )
    score_class = (
        position.get("opportunity_class")
        or position.get("score_signal_class")
        or ("momentum" if position.get("legacy") else "durable")
    )
    return decayed_score(base, score_class, score_date, as_of)


def effective_score(position, as_of, legacy_default_score=DEFAULT_LEGACY_DEFAULT_SCORE):
    """Historical compatibility wrapper. v2 callers should use effective_opportunity_score."""
    return effective_opportunity_score(
        position,
        as_of,
        legacy_default_score=legacy_default_score,
        legacy_old_score_cap=DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY,
    )


def replaceable_holdings(
    positions,
    as_of,
    legacy_default_score=DEFAULT_LEGACY_DEFAULT_SCORE,
    legacy_old_score_cap=DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY,
):
    """Rank non-same-day holdings weakest to strongest by decayed v2 opportunity."""
    rows = []
    for symbol, pos in positions.items():
        if pos.get("same_day"):
            continue
        base, legacy_v2 = _base_opportunity_score(pos, legacy_default_score, legacy_old_score_cap)
        eff = effective_opportunity_score(
            pos,
            as_of,
            legacy_default_score=legacy_default_score,
            legacy_old_score_cap=legacy_old_score_cap,
        )
        rows.append(
            {
                "symbol": symbol,
                "base_opportunity_score": round(base, 3),
                "effective_opportunity_score": eff,
                "effective_score": eff,
                "legacy_v2": legacy_v2,
                "legacy": bool(pos.get("legacy") or pos.get("score") is None),
                "value_usd": pos.get("value_usd", 0.0),
                "entry_date": pos.get("entry_date"),
            }
        )
    rows.sort(
        key=lambda r: (
            r["effective_opportunity_score"],
            -float(r["value_usd"] or 0.0),
            r["entry_date"] or "",
        )
    )
    return rows


def rotation_eligible(
    candidate_opportunity_score,
    positions,
    as_of,
    rotation_min_opportunity_advantage=0.75,
    min_opportunity_score=6.0,
    legacy_default_score=DEFAULT_LEGACY_DEFAULT_SCORE,
    legacy_old_score_cap=DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY,
):
    candidate_opportunity_score = float(candidate_opportunity_score)
    if candidate_opportunity_score < min_opportunity_score:
        return {
            "eligible": False,
            "reason": (
                f"candidate_opportunity_score {candidate_opportunity_score} "
                f"< min_opportunity_score {min_opportunity_score}"
            ),
        }

    replaceable = replaceable_holdings(
        positions,
        as_of,
        legacy_default_score=legacy_default_score,
        legacy_old_score_cap=legacy_old_score_cap,
    )
    if not replaceable:
        return {
            "eligible": False,
            "reason": "no replaceable holdings (all positions are same-day lots, or none held)",
        }

    weakest = replaceable[0]
    threshold = max(
        min_opportunity_score,
        weakest["effective_opportunity_score"] + rotation_min_opportunity_advantage,
    )
    eligible = candidate_opportunity_score >= threshold
    return {
        "eligible": eligible,
        "weakest_symbol": weakest["symbol"],
        "weakest_effective_opportunity_score": weakest["effective_opportunity_score"],
        "weakest_legacy_v2": weakest["legacy_v2"],
        "threshold": round(threshold, 3),
        "candidate_opportunity_score": round(candidate_opportunity_score, 3),
        "full_ranking": replaceable,
        "reason": (
            f"candidate {candidate_opportunity_score:.3f} >= threshold {threshold:.3f} "
            f"(weakest={weakest['symbol']} @ {weakest['effective_opportunity_score']:.3f})"
            if eligible
            else f"candidate {candidate_opportunity_score:.3f} < threshold {threshold:.3f} "
            f"(weakest={weakest['symbol']} @ {weakest['effective_opportunity_score']:.3f})"
        ),
    }


def positions_missing_v2(positions, min_value_usd=100.0):
    """Return meaningful positions that still lack v2 opportunity fields."""
    missing = []
    for symbol, pos in positions.items():
        value = float(pos.get("value_usd") or 0.0)
        if value < float(min_value_usd):
            continue
        if pos.get("opportunity_score") is None:
            missing.append(symbol)
    return sorted(missing)


def idle_cash_status(live, config):
    """Compute whether deployable idle cash requires a deeper search this run."""
    account_value = float(live.get("account_value") or 0.0)
    raw_bp = live.get("deployable_buying_power")
    if raw_bp is None:
        raw_bp = live.get("buying_power")
    buying_power = float(raw_bp or 0.0)
    reserve = float(config.get("min_cash_reserve_usd", 0.0))
    deployable = max(0.0, buying_power - reserve)

    session_allows = live.get("session_allows_entries")
    if session_allows is None:
        session_allows = live.get("market_session") in {
            "regular_hours",
            "extended_hours",
            "all_day_hours",
        }

    entry_blocked = bool(live.get("entry_blocked", False))
    completed = bool(live.get("idle_cash_escalation_completed", False))
    pct = (deployable / account_value * 100.0) if account_value > 0 else 0.0
    escalation = float(config.get("idle_cash_escalation_pct_of_account", 10.0))
    critical = float(config.get("idle_cash_critical_pct_of_account", 20.0))

    return {
        "account_value": round(account_value, 2),
        "deployable_buying_power": round(deployable, 2),
        "idle_cash_pct": round(pct, 3),
        "session_allows_entries": bool(session_allows),
        "entry_blocked": entry_blocked,
        "entry_blocked_reason": live.get("entry_blocked_reason") or "",
        "idle_cash_escalation_completed": completed,
        "escalation_threshold_pct": escalation,
        "critical_threshold_pct": critical,
        "requires_escalation": (
            bool(session_allows)
            and not entry_blocked
            and not completed
            and pct >= escalation
        ),
        "critical": (
            bool(session_allows)
            and not entry_blocked
            and not completed
            and pct >= critical
        ),
    }


def fast_check(positions, live, as_of, config):
    """Decide whether an hourly run needs deep research."""
    reasons = []

    if not live.get("stop_orders_ok", True):
        reasons.append("STOP_ORDER_PROBLEM: a required protective order is missing or unconfirmed")
    if live.get("new_high_any_position"):
        reasons.append("TRAILING_STOP_DUE: a position made a new high since entry")
    if live.get("position_count_changed"):
        reasons.append("POSITION_CHANGE: a position appeared or disappeared since last run")
    if live.get("drawdown_state_changed"):
        reasons.append("DRAWDOWN_STATE_CHANGED: halt/resume threshold crossed")
    if live.get("day_trade_count_changed"):
        reasons.append("DAY_TRADE_COUNT_CHANGED: PDT counter moved")

    if config.get("require_v2_rescore_before_no_action", True):
        missing_v2 = positions_missing_v2(
            positions,
            min_value_usd=config.get(
                "v2_rescore_min_position_usd",
                config.get("strategic_position_min_usd", 100.0),
            ),
        )
        if missing_v2:
            reasons.append(
                "V2_POSITION_RESCORE_DUE: "
                + ", ".join(missing_v2)
                + " are meaningful holdings without opportunity_score"
            )

    cash = idle_cash_status(live, config)
    if cash["requires_escalation"]:
        label = "IDLE_CASH_CRITICAL" if cash["critical"] else "IDLE_CASH_ESCALATION"
        reasons.append(
            f"{label}: {cash['idle_cash_pct']:.2f}% of account is deployable "
            f"(USD {cash['deployable_buying_power']:.2f}); complete expanded discovery before NO_ACTION"
        )

    for key, label in [
        ("scanner_new_symbols", "NEW_SCANNER_HIT"),
        ("scanner_acceleration_symbols", "SCANNER_ACCELERATION"),
        ("fresh_filing_symbols", "FRESH_PRIMARY_SOURCE"),
        ("winner_management_due", "WINNER_MANAGEMENT_DUE"),
        ("candidate_score_inputs_changed", "CANDIDATE_INPUT_CHANGED"),
    ]:
        values = live.get(key) or []
        if values:
            reasons.append(f"{label}: {', '.join(map(str, values))}")

    for cand_symbol, cand in (live.get("known_candidates") or {}).items():
        candidate_opp = cand.get("opportunity_score")
        if candidate_opp is None:
            old = cand.get("score")
            if old is None:
                continue
            candidate_opp = min(
                float(old),
                float(config.get(
                    "legacy_old_score_cap_for_opportunity",
                    DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY,
                )),
            )
        verdict = rotation_eligible(
            candidate_opp,
            positions,
            as_of,
            rotation_min_opportunity_advantage=config.get(
                "rotation_min_opportunity_advantage",
                config.get("rotation_min_score_advantage", 0.75),
            ),
            min_opportunity_score=config.get("min_opportunity_score", 6.0),
            legacy_default_score=config.get("legacy_default_score", DEFAULT_LEGACY_DEFAULT_SCORE),
            legacy_old_score_cap=config.get(
                "legacy_old_score_cap_for_opportunity",
                DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY,
            ),
        )
        if verdict["eligible"]:
            reasons.append(
                f"ROTATION_NOW_OPEN: {cand_symbol} opportunity {float(candidate_opp):.3f} "
                f"clears {verdict['weakest_symbol']} "
                f"@ {verdict['weakest_effective_opportunity_score']:.3f}"
            )

    ranking = replaceable_holdings(
        positions,
        as_of,
        legacy_default_score=config.get("legacy_default_score", DEFAULT_LEGACY_DEFAULT_SCORE),
        legacy_old_score_cap=config.get(
            "legacy_old_score_cap_for_opportunity",
            DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY,
        ),
    )
    return {
        "actionable": bool(reasons),
        "reasons": reasons,
        "current_ranking": ranking,
        "idle_cash": cash,
    }


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    oscore = sub.add_parser("opportunity-score", help="Compute v2 explosive opportunity score")
    oscore.add_argument("--candidate", required=True, help="path to candidate.json")
    oscore.add_argument("--config", required=True, help="path to config.json")

    d = sub.add_parser("decay", help="Compute a single decayed score")
    d.add_argument("--score", type=float, required=True)
    d.add_argument(
        "--class",
        dest="signal_class",
        choices=["transformational", "durable", "momentum"],
        required=True,
    )
    d.add_argument("--days-old", type=int, required=True)

    r = sub.add_parser("rotation", help="Check whether a candidate can rotate into the book")
    r.add_argument("--candidate-opportunity-score", type=float)
    r.add_argument(
        "--candidate-score",
        type=float,
        help="deprecated alias; treated as candidate opportunity score for compatibility",
    )
    r.add_argument("--positions", required=True, help="path to positions.json")
    r.add_argument("--config", required=True, help="path to config.json")
    r.add_argument("--as-of", required=True, help="YYYY-MM-DD")

    fc = sub.add_parser("fast-check", help="Decide whether an hourly run needs deep research")
    fc.add_argument("--positions", required=True)
    fc.add_argument("--live", required=True, help="path to live.json")
    fc.add_argument("--config", required=True)
    fc.add_argument("--as-of", required=True)

    args = p.parse_args()

    if args.cmd == "opportunity-score":
        candidate = _load(args.candidate)
        config = _load(args.config)
        print(json.dumps(opportunity_score(candidate, config), indent=2))
        return

    if args.cmd == "decay":
        print(
            json.dumps(
                {"decayed_score": round(args.score * decay_multiplier(args.signal_class, args.days_old), 3)}
            )
        )
        return

    if args.cmd == "rotation":
        candidate_score = (
            args.candidate_opportunity_score
            if args.candidate_opportunity_score is not None
            else args.candidate_score
        )
        if candidate_score is None:
            p.error("rotation requires --candidate-opportunity-score (or deprecated --candidate-score)")
        positions = _load(args.positions)
        config = _load(args.config)
        verdict = rotation_eligible(
            candidate_score,
            positions,
            args.as_of,
            rotation_min_opportunity_advantage=config.get(
                "rotation_min_opportunity_advantage",
                config.get("rotation_min_score_advantage", 0.75),
            ),
            min_opportunity_score=config.get("min_opportunity_score", 6.0),
            legacy_default_score=config.get("legacy_default_score", DEFAULT_LEGACY_DEFAULT_SCORE),
            legacy_old_score_cap=config.get(
                "legacy_old_score_cap_for_opportunity",
                DEFAULT_LEGACY_OLD_SCORE_CAP_FOR_OPPORTUNITY,
            ),
        )
        print(json.dumps(verdict, indent=2))
        return

    if args.cmd == "fast-check":
        positions = _load(args.positions)
        live = _load(args.live)
        config = _load(args.config)
        result = fast_check(positions, live, args.as_of, config)
        print(json.dumps(result, indent=2))
        sys.exit(0 if not result["actionable"] else 1)


if __name__ == "__main__":
    main()
