#!/usr/bin/env python3
"""
Run-completion validator: the ONLY thing allowed to turn a run into "no action".

  python3 scripts/run_complete.py check --run run.json --config config.json

run.json (assembled by the agent from broker/tool results; see WORKFLOW.md):
  run_id, now (ISO), market_session, manifest (from startup_check),
  account {observed_at, account_value, buying_power|deployable_buying_power},
  protection {required_symbols, verified_symbols, accepted_exceptions, checked_at},
  positions {symbol: adapter output incl. lots, opportunity_* fields},
  holdings_reassessed [{symbol, assessment_run_id}],
  discovery {run_id, sources:[...]}, catalyst_window {since, until},
  research {reviewed:[candidate records], deferred:[...], budget, queued},
  rotation {evaluated, result, blocked_reason},
  block {kind: broker|strategy, reason, evidence_ref} | null,
  execution {unresolved: {...}, orders: [{symbol, side, intent_id, ...}],
             post_sale_buying_power_verified},
  claimed_outcome (optional; compared, never trusted)

Outcomes (exit 0 only for the three COMPLETED_* values):
  COMPLETED_NO_QUALIFYING_TRADE   discovery complete, nothing qualified
  COMPLETED_TRADE_BLOCKED         discovery complete, a qualified trade blocked (broker|strategy)
  COMPLETED_TRADE_EXECUTED        an order with a matching intent and evidence was placed
  INCOMPLETE_DISCOVERY            a required source is missing / not_run / invalid
  STALE_OR_FAILED_DATA            required account/protection/source data failed or is stale/unknown
  INCOMPLETE_HOLDING_REVIEW       held position score missing/stale and not reassessed or deferred
  RESEARCH_DEFERRED_BUDGET        researchable names deferred by budget (NOT "no opportunity")
  EXECUTION_PENDING_OR_AMBIGUOUS  an unresolved or ambiguous order intent exists
  PROTECTION_PROBLEM              a required protective order is missing
  INVALID_RUN_RECORD              contradictory/unsupported evidence (e.g. order without evidence)
"""
import argparse
import datetime as dt
import json
import sys

try:
    import scoring
    import discovery
except ImportError:  # pragma: no cover
    from scripts import scoring, discovery

COMPLETED = {"COMPLETED_NO_QUALIFYING_TRADE", "COMPLETED_TRADE_BLOCKED", "COMPLETED_TRADE_EXECUTED"}
SCORE_TOL = 0.06


def _age_minutes(ts, now):
    t = discovery._ts(ts)
    if t is None:
        return None
    return (discovery._ts(now) - t).total_seconds() / 60.0


def _recompute(rec, config):
    try:
        return scoring.opportunity_score(rec["score_inputs"], config)
    except Exception as exc:  # noqa: BLE001 - any failure means unsupported evidence
        return {"error": str(exc)}


def validate_run(run, config):
    now = run.get("now")
    session = run.get("market_session") or "unknown"
    viol, notes = [], {}
    positions = run.get("positions") or {}

    def result(outcome, extra=None):
        out = {"outcome": outcome, "completed": outcome in COMPLETED,
               "ok_for_no_action": outcome == "COMPLETED_NO_QUALIFYING_TRADE",
               "violations": viol, "notes": notes, "session": session}
        out.update(extra or {})
        claimed = run.get("claimed_outcome")
        if claimed == "NO_ACTION" and outcome != "COMPLETED_NO_QUALIFYING_TRADE":
            out["claim_rejected"] = f"claimed NO_ACTION but validator outcome is {outcome}"
        return out

    # -1. the run must prove what it loaded (N): matching workflow version + a passing manifest
    man = run.get("manifest") or {}
    if not man.get("ok") or man.get("workflow_version") != config.get("workflow_version") \
            or man.get("branch") != "claude/trading-state":
        viol.append(f"startup manifest missing/failed/mismatched: {{ok:{man.get('ok')}, "
                    f"version:{man.get('workflow_version')}, branch:{man.get('branch')}}}")
        return result("INVALID_RUN_RECORD", {"new_entries_permitted": False})

    # 0. execution ambiguity outranks everything: never add risk, reconcile first
    unresolved = (run.get("execution") or {}).get("unresolved") or {}
    if unresolved:
        viol.append(f"unresolved intents: {unresolved}")
        return result("EXECUTION_PENDING_OR_AMBIGUOUS", {"new_entries_permitted": False})

    # 1. account freshness / required safety fields (missing => unknown, not favorable)
    acct = run.get("account") or {}
    max_age = (config.get("market_data_max_age_minutes") or {}).get("account", 10)
    missing = [k for k in ("observed_at", "account_value") if acct.get(k) in (None, "")]
    if acct.get("deployable_buying_power") is None and acct.get("buying_power") is None:
        missing.append("buying_power")
    if missing:
        viol.append(f"account fields missing: {missing}")
        return result("STALE_OR_FAILED_DATA", {"new_entries_permitted": False})
    age = _age_minutes(acct["observed_at"], now)
    if age is None or age > max_age:
        viol.append(f"account snapshot age {age} min > {max_age}")
        return result("STALE_OR_FAILED_DATA", {"new_entries_permitted": False})

    # 2. protection: unknown is not safe; missing stop blocks new risk
    live = {"protection": run.get("protection")}
    p_state, p_detail = scoring.protection_status(live)
    notes["protection"] = {"state": p_state, "detail": p_detail}
    if p_state == "unknown":
        viol.append("protection verification missing/unchecked")
        return result("STALE_OR_FAILED_DATA", {"new_entries_permitted": False})
    if p_state == "problem":
        viol.append(f"protective order missing: {p_detail}")
        return result("PROTECTION_PROBLEM", {"new_entries_permitted": False})

    # 3. discovery ledger
    disc = discovery.validate_ledger(run.get("discovery"), config, now, session)
    notes["discovery"] = {k: disc[k] for k in ("required", "missing", "failed", "stale", "invalid", "healthy_sources")}
    if disc["failed"] or disc["stale"]:
        viol.append(f"failed/stale sources: {disc['failed'] + disc['stale']}")
    if disc["missing"] or disc["invalid"]:
        viol.append(f"missing/invalid sources: {disc['missing'] + disc['invalid']}")
    not_run = [s for s, v in disc["per_source"].items() if v["status"] in ("not_run", "missing", "invalid")]

    # 4. candidate records + score recomputation (J: unsupported scores cannot bypass evidence)
    research = run.get("research") or {}
    reviewed = research.get("reviewed") or []
    qualified = []
    for rec in reviewed:
        probs = discovery.validate_candidate_record(rec)
        if probs:
            viol.append(f"candidate {rec.get('symbol')} record invalid: {probs}")
        out = _recompute(rec, config) if rec.get("score_inputs") else {"error": "no score_inputs"}
        if "error" in out:
            viol.append(f"candidate {rec.get('symbol')} score not recomputable: {out['error']}")
        else:
            stated = (rec.get("score_output") or {}).get("opportunity_score")
            if stated is None or abs(float(stated) - float(out["opportunity_score"])) > SCORE_TOL:
                viol.append(f"candidate {rec.get('symbol')} stated score {stated} != recomputed "
                            f"{out['opportunity_score']}")
            decision = rec.get("decision", "")
            tier_ok = {"qualify_standard": out.get("eligible"),
                       "qualify_tactical": out.get("cash_deployment_eligible"),
                       "qualify_best_available": out.get("best_available_eligible")}
            if decision in tier_ok and not tier_ok[decision]:
                viol.append(f"candidate {rec.get('symbol')} decision {decision} not supported by scoring.py")
        if str(rec.get("decision", "")).startswith("qualify"):
            qualified.append(rec)
    record_bad = any("record invalid" in v or "score" in v for v in viol)

    # 5. execution evidence (order requires intent + qualified, verified record + broker checks)
    ex = run.get("execution") or {}
    orders = ex.get("orders") or []
    by_sym = {r.get("symbol"): r for r in reviewed}
    for o in orders:
        if o.get("side") == "buy" and o.get("purpose") != "protective_stop":
            rec = by_sym.get(o.get("symbol"))
            if not o.get("intent_id"):
                viol.append(f"order {o.get('symbol')} placed without durable intent")
            if rec is None or not str(rec.get("decision", "")).startswith("qualify"):
                viol.append(f"order {o.get('symbol')} has no qualifying evidence record")
            if not (o.get("broker_review_ok") and o.get("tradable") is True):
                viol.append(f"order {o.get('symbol')} missing broker review/tradability evidence")
            if o.get("fill_verified") is not True:
                viol.append(f"order {o.get('symbol')} fill not verified by polling")
        if o.get("side") == "sell" and o.get("purpose") != "protective_stop":
            if not o.get("intent_id"):
                viol.append(f"sell {o.get('symbol')} without durable intent")
            if ex.get("post_sale_buying_power_verified") is not True and o.get("funds_followup_buy"):
                viol.append("proceeds used before unleveraged buying power was re-verified")
    if any("without durable intent" in v or "no qualifying evidence" in v or "missing broker review" in v
           or "not verified" in v or "before unleveraged" in v for v in viol):
        return result("INVALID_RUN_RECORD", {"new_entries_permitted": False})
    if record_bad:
        return result("INVALID_RUN_RECORD", {"new_entries_permitted": False})

    # 6. incomplete / failed discovery blocks ordinary no-action; healthy sources stay usable
    if not_run:
        return result("INCOMPLETE_DISCOVERY", {"entries_from_healthy_sources_allowed": True,
                                               "ranking_claim_valid": False, "new_entries_permitted": False})
    if disc["failed"] or disc["stale"]:
        return result("STALE_OR_FAILED_DATA", {"entries_from_healthy_sources_allowed": True,
                                               "ranking_claim_valid": False, "new_entries_permitted": False})

    # 7. holdings assessment freshness (missing vs stale are separate conditions)
    import lots as _lots  # local import keeps module import order simple
    ny_today = _lots.ny_date(now)
    need = scoring.positions_needing_reassessment(
        positions, ny_today, config,
        min_value_usd=config.get("v2_rescore_min_position_usd", 100.0))
    done = {h.get("symbol") for h in (run.get("holdings_reassessed") or []) if h.get("assessment_run_id")}
    deferred_syms = {d.get("symbol") for d in (research.get("deferred") or [])}
    pending = sorted((set(need["missing"]) | set(need["stale"]) | set(need["unevidenced"])) - done)
    notes["holdings_needing_review"] = need
    if [s for s in pending if s not in deferred_syms]:
        viol.append(f"holdings not reassessed this run and not budget-deferred: "
                    f"{[s for s in pending if s not in deferred_syms]}")
        return result("INCOMPLETE_HOLDING_REVIEW", {"new_entries_permitted": True})

    # 8. budget deferral is never a conclusion that no opportunity exists
    if research.get("deferred"):
        viol.append(f"{len(research['deferred'])} researchable item(s) deferred by budget")
        return result("RESEARCH_DEFERRED_BUDGET",
                      {"deferred": [d.get("symbol") for d in research["deferred"]]})

    # 9. cash-deployment quota (cash threshold gates DEPLOYMENT work, not discovery)
    lv = {"account_value": acct["account_value"], "deployable_buying_power": acct.get("deployable_buying_power"),
          "buying_power": acct.get("buying_power"), "market_session": session,
          "session_allows_entries": session in ("regular_hours", "extended_hours", "all_day_hours")}
    cash = scoring.idle_cash_status(lv, config)
    notes["idle_cash_pct"] = cash["idle_cash_pct"]
    blocked = run.get("block")
    placed_buy = any(o.get("side") == "buy" and o.get("purpose") != "protective_stop" for o in orders)
    if cash["requires_escalation"] and not blocked and not placed_buy:
        if len(reviewed) < cash["required_deep_review_count"]:
            viol.append(f"cash trigger active: {len(reviewed)}/{cash['required_deep_review_count']} deep reviews; "
                        "insufficient coverage must be recorded as such, not as no-opportunity")
            return result("INCOMPLETE_DISCOVERY", {"new_entries_permitted": True})

    # 10. a qualified candidate must be acted on, rotated into, or explicitly blocked
    if qualified and not placed_buy:
        rot = run.get("rotation") or {}
        if not blocked and not rot.get("evaluated"):
            viol.append("qualified candidate neither bought, rotation-evaluated, nor blocked")
            return result("INVALID_RUN_RECORD", {"new_entries_permitted": True})
    if placed_buy:
        return result("COMPLETED_TRADE_EXECUTED")
    if blocked:
        if blocked.get("kind") not in ("broker", "strategy") or not blocked.get("reason"):
            viol.append("block requires kind in {broker,strategy} and a reason")
            return result("INVALID_RUN_RECORD")
        return result("COMPLETED_TRADE_BLOCKED", {"block": blocked})
    if qualified:
        viol.append("qualified candidate with no order and no recorded block")
        return result("INVALID_RUN_RECORD")
    # full portfolio / low cash still owes a rotation evaluation when a candidate was strong
    return result("COMPLETED_NO_QUALIFYING_TRADE")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--config", required=True)
    a = ap.parse_args()
    run = json.load(open(a.run))
    config = json.load(open(a.config))
    res = validate_run(run, config)
    print(json.dumps(res, indent=2))
    sys.exit(0 if res["completed"] else 3)


if __name__ == "__main__":
    main()
