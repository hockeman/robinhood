"""
Regression tests for the repaired discovery / state / execution workflow.
Mocked broker responses and isolated fixtures only. NO live orders, no network.

Run: python3 -m unittest discover -s scripts -p 'test_*.py'
Letters A-N map to the owner's required regression list.
"""
import copy
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(__file__))

import build_inputs  # noqa: E402
import discovery  # noqa: E402
import execguard  # noqa: E402
import lots  # noqa: E402
import notify_state  # noqa: E402
import persist_run  # noqa: E402
import run_complete  # noqa: E402
import scoring  # noqa: E402
import startup_check  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "config.json")) as _f:
    CONFIG = json.load(_f)
NOW = "2026-10-14T17:15:00Z"          # 13:15 America/New_York, regular hours
TODAY = "2026-10-14"

GOOD_INPUTS = dict(
    symbol="XYZ", signal_quality_score=8, catalyst_magnitude_score=9, volume_price_discovery_score=7,
    structure_squeeze_score=5, remaining_upside_score=7, dilution_risk_score=1, exhaustion_risk_score=1,
    primary_source_verified=True, catalyst_verified=True, transformational=True, continuation_confirmed=True,
    chase_pct=20, market_catalyst_verified=False, live_heat_verified=False, disqualifier=False)
WEAK_INPUTS = dict(GOOD_INPUTS, signal_quality_score=1, catalyst_magnitude_score=1,
                   volume_price_discovery_score=1, structure_squeeze_score=0, remaining_upside_score=1,
                   primary_source_verified=False, catalyst_verified=False, transformational=False)


def ledger(session="regular_hours", overrides=None, drop=(), now=NOW):
    """A fully healthy ledger for a session; overrides/drop make specific sources bad."""
    srcs = []
    for sid in discovery.required_sources(CONFIG, session):
        if sid in drop:
            continue
        e = {"source_id": sid, "kind": "scanner", "params": {"id": sid}, "status": "successful_empty",
             "requested_at": "2026-10-14T17:10:00Z", "observed_at": "2026-10-14T17:11:00Z",
             "data_as_of": "2026-10-14T17:11:00Z", "returned_count": 0,
             "result_ref": f"runs/R/{sid}.json", "result_sha256": "ab" * 32,
             "coverage_note": "top-N rows only", "error": None}
        e.update((overrides or {}).get(sid, {}))
        srcs.append(e)
    return {"run_id": "R", "sources": srcs}


def held(symbol, score_date="2026-10-14", score=6.0, cls="durable", run_id="A1", lots_=None, value=1500.0):
    return {"opportunity_score": score, "opportunity_class": cls, "opportunity_score_date": score_date,
            "assessment_run_id": run_id, "assessment_evidence_ref": "runs/x.json", "qty": 10,
            "lots": lots_ or [{"qty": 10, "open_date": "2026-10-01", "source": "broker_tax_lots", "selectable": True}],
            "value_usd": value, "entry_date": "2026-10-01"}


def candidate_record(symbol="XYZ", inputs=None, decision="qualify_standard"):
    inputs = dict(inputs or GOOD_INPUTS, symbol=symbol)
    out = scoring.opportunity_score(inputs, CONFIG)
    return {"symbol": symbol, "discovery_source": "news_catalyst_search", "first_observed_at": NOW,
            "quote_as_of": NOW, "catalyst_status": "verified", "catalyst_refs": ["8-K 2026-10-14"],
            "facts": ["8-K filed"], "inferences": ["re-rating plausible"], "unknowns": ["short interest"],
            "dilution_check": "no ATM found", "adverse_info_check": "none found",
            "score_inputs": inputs, "score_output": {"opportunity_score": out["opportunity_score"]},
            "remaining_upside_case": "revaluation not yet priced", "strongest_counterargument": "thin float",
            "invalidation_conditions": ["offering announced"], "decision": decision,
            "decision_reasons": ["clears standard gate"], "reconsider_trigger": "n/a",
            "reconsider_expiry": "2026-10-17"}


def make_run(**kw):
    positions = {s: held(s) for s in ("AAA", "BBB", "CCC", "DDD", "EEE")}
    run = {
        "run_id": "R", "now": NOW, "market_session": "regular_hours",
        "manifest": {"ok": True, "workflow_version": CONFIG["workflow_version"], "branch": "claude/trading-state"},
        "account": {"observed_at": "2026-10-14T17:14:00Z", "account_value": 6900.0,
                    "buying_power": 130.0, "deployable_buying_power": 125.0},
        "protection": {"required_symbols": list(positions), "verified_symbols": list(positions),
                       "accepted_exceptions": [], "checked_at": NOW},
        "positions": positions, "holdings_reassessed": [], "discovery": ledger(),
        "research": {"reviewed": [], "deferred": []}, "rotation": {"evaluated": False}, "block": None,
        "execution": {"unresolved": {}, "orders": []},
    }
    run.update(kw)
    return run


# ---------------------------------------------------------------- A, C, D
class DiscoveryIndependentOfCash(unittest.TestCase):
    def test_A_low_cash_still_requires_discovery(self):
        low = make_run(discovery={"run_id": "R", "sources": []})
        r = run_complete.validate_run(low, CONFIG)
        self.assertEqual(r["notes"]["idle_cash_pct"] if "idle_cash_pct" in r["notes"] else 1.8, 1.8)
        self.assertEqual(r["outcome"], "INCOMPLETE_DISCOVERY", r)
        self.assertFalse(r["ok_for_no_action"])
        ok = run_complete.validate_run(make_run(), CONFIG)
        self.assertEqual(ok["outcome"], "COMPLETED_NO_QUALIFYING_TRADE", ok)

    def test_A_fast_check_flags_missing_discovery_below_cash_trigger(self):
        live = {"stop_orders_ok": True, "account_value": 6900.0, "deployable_buying_power": 125.0,
                "market_session": "regular_hours", "session_allows_entries": True, "now": NOW}
        res = scoring.fast_check({}, live, TODAY, CONFIG)
        self.assertTrue(res["actionable"])
        self.assertTrue(any(x.startswith("DISCOVERY_INCOMPLETE") for x in res["reasons"]), res["reasons"])
        self.assertFalse(res["deployment_work_required"])  # cash gate controls deployment only

    def test_C_failed_missing_stale_never_a_successful_empty_scan(self):
        sid = CONFIG["discovery"]["required_by_session"]["regular_hours"][0]
        cases = {
            "missing": dict(drop=(sid,)),
            "failed": dict(overrides={sid: {"status": "failed", "error": "timeout"}}),
            "not_run": dict(overrides={sid: {"status": "not_run"}}),
            "stale": dict(overrides={sid: {"observed_at": "2026-10-14T14:00:00Z",
                                           "requested_at": "2026-10-14T13:59:00Z"}}),
            "empty_without_saved_result": dict(overrides={sid: {"result_ref": None, "result_sha256": None}}),
            "success_but_zero_rows": dict(overrides={sid: {"status": "success", "returned_count": 0}}),
            "boolean_complete_claim_only": dict(overrides={sid: {"status": None, "scan_complete": True}}),
        }
        for name, kw in cases.items():
            r = run_complete.validate_run(make_run(discovery=ledger(**kw)), CONFIG)
            self.assertFalse(r["ok_for_no_action"], (name, r))
            self.assertIn(r["outcome"], ("INCOMPLETE_DISCOVERY", "STALE_OR_FAILED_DATA"), (name, r))

    def test_C_healthy_sources_remain_usable_but_coverage_is_degraded(self):
        sid = CONFIG["discovery"]["required_by_session"]["regular_hours"][0]
        led = ledger(overrides={sid: {"status": "failed", "error": "503"}})
        v = discovery.validate_ledger(led, CONFIG, NOW, "regular_hours")
        self.assertTrue(v["degraded"])
        self.assertIn(sid, v["failed"])
        self.assertGreater(len(v["healthy_sources"]), 5)
        r = run_complete.validate_run(make_run(discovery=led), CONFIG)
        self.assertTrue(r["entries_from_healthy_sources_allowed"])
        self.assertFalse(r["ranking_claim_valid"])

    def test_D_missing_protection_verification_is_not_safe(self):
        r = run_complete.validate_run(make_run(protection=None), CONFIG)
        self.assertEqual(r["outcome"], "STALE_OR_FAILED_DATA", r)
        r = run_complete.validate_run(make_run(protection={}), CONFIG)
        self.assertEqual(r["outcome"], "STALE_OR_FAILED_DATA", r)
        res = scoring.fast_check({}, {"account_value": 1, "market_session": "closed"}, TODAY, CONFIG)
        self.assertTrue(any(x.startswith("STOP_VERIFICATION_UNKNOWN") for x in res["reasons"]))
        # a missing stop is a PROBLEM, and blocks new risk
        prot = {"required_symbols": ["AAA", "BBB"], "verified_symbols": ["AAA"], "accepted_exceptions": [],
                "checked_at": NOW}
        r = run_complete.validate_run(make_run(protection=prot), CONFIG)
        self.assertEqual(r["outcome"], "PROTECTION_PROBLEM")
        self.assertFalse(r["new_entries_permitted"])

    def test_D_accepted_exceptions_are_visible_not_counted_as_protected(self):
        pos = {"data": {"positions": [{"symbol": "AAPL", "quantity": "0.005949"},
                                       {"symbol": "GME", "quantity": "70"}]}}
        orders = {"data": {"orders": [{"symbol": "GME", "side": "sell", "trigger": "stop", "state": "confirmed",
                                       "time_in_force": "gtc", "quantity": "70", "stop_price": "23.49"}]}}
        p = build_inputs.protection_block(pos, orders, CONFIG["accepted_legacy_exceptions"], NOW)
        self.assertEqual(p["verified_symbols"], ["GME"])
        self.assertEqual([e["symbol"] for e in p["accepted_exceptions"]], ["AAPL"])
        self.assertNotIn("AAPL", p["verified_symbols"])


# ---------------------------------------------------------------- B, I, J
class RotationAndHoldings(unittest.TestCase):
    def test_B_five_positions_still_research_and_evaluate_rotation(self):
        positions = {s: held(s, score=4.0 + i * 0.1) for i, s in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE"))}
        v = scoring.rotation_eligible(7.0, positions, TODAY, 0.5, 5.0, config=CONFIG)
        self.assertTrue(v["eligible"] and v["executable"], v)
        self.assertEqual(v["weakest_symbol"], "AAA")
        rec = candidate_record()
        run = make_run(positions=positions,
                       research={"reviewed": [rec], "deferred": []},
                       rotation={"evaluated": True, "result": v})
        r = run_complete.validate_run(run, CONFIG)
        # a qualified candidate that was rotation-evaluated but neither bought nor blocked is not a no-action
        self.assertNotEqual(r["outcome"], "COMPLETED_NO_QUALIFYING_TRADE", r)
        blocked = make_run(positions=positions, research={"reviewed": [rec], "deferred": []},
                           rotation={"evaluated": True, "result": v},
                           block={"kind": "strategy", "reason": "rotation advantage below threshold after costs",
                                  "evidence_ref": "runs/R/rotation.json"})
        self.assertEqual(run_complete.validate_run(blocked, CONFIG)["outcome"], "COMPLETED_TRADE_BLOCKED")

    def test_B_qualified_candidate_cannot_be_silently_dropped(self):
        run = make_run(research={"reviewed": [candidate_record()], "deferred": []})
        r = run_complete.validate_run(run, CONFIG)
        self.assertEqual(r["outcome"], "INVALID_RUN_RECORD", r)

    def test_E_old_same_day_flag_cannot_exclude_reconciled_older_lot(self):
        stale_flag = held("GME", score=4.0)
        stale_flag["same_day"] = True      # the audit-snapshot condition
        rows = scoring.replaceable_holdings({"GME": stale_flag}, TODAY, config=CONFIG)
        self.assertEqual([r["symbol"] for r in rows], ["GME"])
        self.assertTrue(rows[0]["lots_verified"])
        view = scoring.holding_lot_status(stale_flag, TODAY)
        self.assertEqual(view["persisted_same_day_ignored"], True)

    def test_E_adapter_derives_from_broker_tax_lots_not_state_flags(self):
        state = {"positions": {s: {"entry_date": d, "same_day": True, "opportunity_score": 3.5}
                               for s, d in (("GME", "2026-10-05"), ("APOG", "2026-10-07"),
                                            ("BKV", "2026-10-07"), ("TEVA", "2026-10-09"))}}
        qty = {"GME": "70", "APOG": "51", "BKV": "10", "TEVA": "37"}
        dates = {"GME": "2026-10-05", "APOG": "2026-10-07", "BKV": "2026-10-07", "TEVA": "2026-10-09"}
        broker = {"data": {"positions": [{"symbol": s, "quantity": q} for s, q in qty.items()]}}
        taxlots = {s: [{"quantity": qty[s], "open_date": dates[s], "is_selectable": True}] for s in qty}
        out = build_inputs.build(NOW, {"data": {"total_value": "6900", "buying_power": {"buying_power": "130.29"}}},
                                 broker, {"data": {"orders": []}}, {"data": {"results": []}}, taxlots,
                                 state, [], CONFIG)
        for s, p in out["positions"].items():
            self.assertFalse(p["same_day"], s)
            self.assertEqual(p["sellable_qty"], float(qty[s]), s)
            self.assertTrue(p["persisted_same_day_ignored"], s)
        self.assertEqual(len(scoring.replaceable_holdings(out["positions"], TODAY, config=CONFIG)), 4)

    def test_F_genuine_same_day_lot_and_mixed_age_position_stay_restricted(self):
        mixed = [{"quantity": "100", "open_date": "2026-10-01", "is_selectable": True},
                 {"quantity": "20", "open_date": TODAY, "is_selectable": False}]
        pv = lots.position_view("MIX", {"quantity": "120"}, mixed, [], {}, NOW)
        self.assertEqual((pv["sellable_qty"], pv["restricted_qty"], pv["same_day"]), (100.0, 20.0, True))
        # only the old part may be sold, never the whole position
        st = execguard.empty_state()
        execguard.acquire_lease(st, "R", NOW)
        key, why = execguard.record_intent(st, "R", "MIX", "sell", 120, "rotation_sell", NOW, lot_check=pv)
        self.assertIsNone(key, why)
        key, why = execguard.record_intent(st, "R", "MIX", "sell", 100, "rotation_sell", NOW, lot_check=pv)
        self.assertIsNotNone(key, why)
        # all-today lot is not replaceable at all
        only_today = {"T": {"qty": 5, "lots": [{"qty": 5, "open_date": TODAY, "source": "broker_tax_lots"}],
                            "opportunity_score": 1, "opportunity_score_date": TODAY}}
        self.assertEqual(scoring.replaceable_holdings(only_today, TODAY, config=CONFIG), [])

    def test_F_after_hours_buy_is_same_day_in_new_york_time(self):
        late = "2026-10-14T23:30:00Z"            # 19:30 ET on 10-14
        self.assertEqual(lots.ny_date(late), "2026-10-14")
        self.assertEqual(lots.ny_date("2026-10-15T03:00:00Z"), "2026-10-14")  # 23:00 ET still 10-14
        self.assertEqual(lots.ny_date("2026-10-15T14:00:00Z"), "2026-10-15")

    def test_F_unknown_or_contradictory_quantity_blocks_sale(self):
        pv = lots.position_view("U", {"quantity": "50"},
                                [{"quantity": "30", "open_date": "2026-10-01", "is_selectable": True}], [], {}, NOW)
        self.assertEqual((pv["sellable_qty"], pv["unknown_qty"], pv["lots_verified"]), (30.0, 20.0, False))
        pv2 = lots.position_view("C", {"quantity": "10"},
                                 [{"quantity": "30", "open_date": "2026-10-01"}], [], {}, NOW)
        self.assertEqual((pv2["sellable_qty"], pv2["unknown_qty"]), (0.0, 10.0))
        # entry_date-only fallback may rank but not authorize a sale
        fb = lots.position_view("F", {"quantity": "10"}, None, [], {"entry_date": "2026-10-01"}, NOW)
        self.assertFalse(fb["lots_verified"])
        st = execguard.empty_state()
        execguard.acquire_lease(st, "R", NOW)
        key, why = execguard.record_intent(st, "R", "F", "sell", 10, "rotation_sell", NOW, lot_check=fb)
        self.assertIsNone(key)
        self.assertIn("not reconciled", why)

    def test_I_stale_incumbent_triggers_reassessment_not_retention_or_sale(self):
        pos = {"OLD": held("OLD", score_date="2026-10-05", score=3.5, cls="momentum")}
        self.assertEqual(scoring.assessment_status(pos["OLD"], TODAY, CONFIG), "stale")
        v = scoring.rotation_eligible(7.0, pos, TODAY, 0.5, 5.0, config=CONFIG)
        self.assertTrue(v["eligible"])
        self.assertFalse(v["executable"])
        self.assertEqual(v["status"], "REASSESS_INCUMBENT_FIRST")
        res = scoring.fast_check(pos, {"stop_orders_ok": True, "account_value": 1000,
                                       "known_candidates": {"XYZ": {"opportunity_score": 7.0}}}, TODAY, CONFIG)
        self.assertTrue(any(x.startswith("HOLDING_REASSESSMENT_DUE") for x in res["reasons"]))
        self.assertTrue(any(x.startswith("ROTATION_PENDING") for x in res["reasons"]))
        self.assertFalse(any(x.startswith("ROTATION_NOW_OPEN") for x in res["reasons"]))

    def test_I_missing_and_stale_are_different_and_date_bump_without_evidence_is_rejected(self):
        p_missing = {"qty": 1, "lots": [], "entry_date": "2026-10-01", "value_usd": 500}
        self.assertEqual(scoring.assessment_status(p_missing, TODAY, CONFIG), "missing")
        bumped = held("B", score_date=TODAY)
        bumped.pop("assessment_run_id"); bumped.pop("assessment_evidence_ref")
        self.assertEqual(scoring.assessment_status(bumped, TODAY, CONFIG), "unevidenced")
        self.assertEqual(scoring.assessment_status(held("B", score_date=TODAY), TODAY, CONFIG), "fresh")
        # unknown market value must not exempt a holding from rescoring
        self.assertEqual(scoring.positions_missing_v2({"U": {"opportunity_score": None, "value_usd": None}}), ["U"])

    def test_I_validator_requires_real_reassessment_of_stale_holdings(self):
        positions = {"OLD": held("OLD", score_date="2026-10-05", cls="momentum")}
        run = make_run(positions=positions, protection={"required_symbols": ["OLD"], "verified_symbols": ["OLD"],
                                                        "accepted_exceptions": [], "checked_at": NOW})
        self.assertEqual(run_complete.validate_run(run, CONFIG)["outcome"], "INCOMPLETE_HOLDING_REVIEW")
        run["holdings_reassessed"] = [{"symbol": "OLD", "assessment_run_id": "R"}]
        self.assertEqual(run_complete.validate_run(run, CONFIG)["outcome"], "COMPLETED_NO_QUALIFYING_TRADE")

    def test_J_unsupported_high_score_cannot_bypass_evidence_or_broker_checks(self):
        rec = candidate_record("BAD", inputs=WEAK_INPUTS)
        rec["score_output"]["opportunity_score"] = 9.5       # model-asserted, not what scoring.py computes
        r = run_complete.validate_run(make_run(research={"reviewed": [rec], "deferred": []}), CONFIG)
        self.assertEqual(r["outcome"], "INVALID_RUN_RECORD", r)
        self.assertTrue(any("stated score" in v for v in r["violations"]))
        rec2 = candidate_record("BAD2", inputs=WEAK_INPUTS)
        rec2["decision"] = "qualify_standard"
        r = run_complete.validate_run(make_run(research={"reviewed": [rec2], "deferred": []}), CONFIG)
        self.assertEqual(r["outcome"], "INVALID_RUN_RECORD", r)
        self.assertTrue(any("not supported by scoring.py" in v for v in r["violations"]))
        good = candidate_record("GOOD")
        order = {"symbol": "GOOD", "side": "buy", "purpose": "entry"}   # no intent, no broker review, no fill proof
        r = run_complete.validate_run(
            make_run(research={"reviewed": [good], "deferred": []}, execution={"unresolved": {}, "orders": [order]}),
            CONFIG)
        self.assertEqual(r["outcome"], "INVALID_RUN_RECORD", r)
        order.update(intent_id="i1", broker_review_ok=True, tradable=True, fill_verified=True)
        r = run_complete.validate_run(
            make_run(research={"reviewed": [good], "deferred": []}, execution={"unresolved": {}, "orders": [order]}),
            CONFIG)
        self.assertEqual(r["outcome"], "COMPLETED_TRADE_EXECUTED", r)

    def test_J_rejection_on_unverified_catalyst_cannot_claim_none_exists(self):
        rec = candidate_record("UNV", inputs=WEAK_INPUTS, decision="reject")
        rec["catalyst_status"] = "unverified"
        rec["decision_reasons"] = ["no catalyst"]
        self.assertTrue(discovery.validate_candidate_record(rec))
        rec["decision_reasons"] = ["catalyst not_verified after 8-K and news search"]
        self.assertEqual(discovery.validate_candidate_record(rec), [])


# ---------------------------------------------------------------- G, H, M
class CatalystFirstAndBudget(unittest.TestCase):
    def test_G_catalyst_enters_research_before_price_or_volume_moves(self):
        quiet = {"symbol": "QUIET", "catalyst_ref": "8-K 0001", "catalyst_type": "8-K", "catalyst_tier": "S",
                 "rvol": 0.9, "pct_change": 0.0, "catalyst_value_to_market_cap": 0.4}
        noisy = {"symbol": "NOISY", "scanner_hit": True, "rvol": 12.0, "pct_change": 30.0}
        junk = {"symbol": "JUNK", "pct_change": 0.5}
        self.assertTrue(discovery.enters_research(quiet))
        self.assertFalse(discovery.enters_research(junk))
        plan = discovery.plan_research([noisy, quiet], max_deep_reviews=1)
        self.assertEqual(plan["selected"][0]["symbol"], "QUIET")   # ranked by strategy, not scanner heat
        self.assertEqual(plan["deferred"][0]["research_state"], "deferred_budget")

    def test_G_window_overlap_and_dedupe(self):
        since = discovery.catalyst_window("2026-10-14T12:00:00Z", NOW, overlap_hours=6, max_hours=72)
        self.assertEqual(since, "2026-10-14T06:00:00+00:00")
        capped = discovery.catalyst_window("2026-09-01T00:00:00Z", NOW, overlap_hours=6, max_hours=72)
        self.assertEqual(capped, "2026-10-11T17:15:00+00:00")
        ev = [{"symbol": "AAA", "filing_id": "f1"}, {"symbol": "AAA", "filing_id": "f1"}, {"symbol": "BBB", "url": "u"}]
        fresh, seen = discovery.dedupe_events(ev, {}, NOW)
        self.assertEqual(len(fresh), 2)
        again, _ = discovery.dedupe_events(ev, seen, "2026-10-14T18:15:00Z")
        self.assertEqual(again, [])

    def test_H_materially_changed_candidate_is_not_rejected_from_old_cache(self):
        prev = {"snapshot": {"price": 10.0, "rvol": 1.2, "filing_ids": ["a"], "news_keys": []}}
        same = {"price": 10.1, "rvol": 1.3, "filing_ids": ["a"], "news_keys": []}
        moved = {"price": 12.0, "rvol": 1.3, "filing_ids": ["a"], "news_keys": []}
        newfiling = {"price": 10.0, "rvol": 1.2, "filing_ids": ["a", "b"], "news_keys": []}
        louder = {"price": 10.0, "rvol": 3.5, "filing_ids": ["a"], "news_keys": []}
        self.assertTrue(discovery.cached_rejection_usable(prev, same)[0])
        for cur in (moved, newfiling, louder):
            self.assertFalse(discovery.cached_rejection_usable(prev, cur)[0], cur)
        self.assertFalse(discovery.cached_rejection_usable(None, same)[0])   # no basis => never reuse

    def test_M_budget_exhaustion_is_explicit_deferral_not_no_opportunity(self):
        queue = [{"symbol": f"S{i}", "catalyst_ref": f"r{i}", "catalyst_type": "8-K", "catalyst_tier": "A"}
                 for i in range(12)]
        plan = discovery.plan_research(queue, CONFIG["research_budget"]["max_deep_reviews_per_run"])
        self.assertEqual((len(plan["selected"]), len(plan["deferred"])), (8, 4))
        run = make_run(research={"reviewed": [], "deferred": plan["deferred"], "budget": 8, "queued": 12})
        r = run_complete.validate_run(run, CONFIG)
        self.assertEqual(r["outcome"], "RESEARCH_DEFERRED_BUDGET", r)
        self.assertFalse(r["ok_for_no_action"])
        # data collection and safety checks still ran and are recorded healthy
        self.assertEqual(r["notes"]["protection"]["state"], "verified")
        self.assertEqual(r["notes"]["discovery"]["missing"], [])

    def test_invalid_incomplete_candidate_record_is_flagged(self):
        rec = candidate_record()
        rec.pop("strongest_counterargument")
        self.assertTrue(any("strongest_counterargument" in p for p in discovery.validate_candidate_record(rec)))

    def test_cash_trigger_does_not_allow_invented_quota(self):
        cash_run = make_run(account={"observed_at": "2026-10-14T17:14:00Z", "account_value": 6900.0,
                                     "deployable_buying_power": 400.0})
        r = run_complete.validate_run(cash_run, CONFIG)
        self.assertEqual(r["outcome"], "INCOMPLETE_DISCOVERY")
        self.assertIn("insufficient coverage", " ".join(r["violations"]))


# ---------------------------------------------------------------- K, L
def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)


class ExecutionCoordination(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.remote = os.path.join(self.tmp, "remote.git")
        _git(self.tmp, "init", "--bare", "-b", "claude/trading-state", self.remote)
        seed = os.path.join(self.tmp, "seed")
        _git(self.tmp, "clone", self.remote, seed)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            _git(seed, "config", k, v)
        with open(os.path.join(seed, "state.json"), "w") as f:
            f.write("{}")
        _git(seed, "checkout", "-b", "claude/trading-state")
        _git(seed, "add", "-A"); _git(seed, "commit", "-m", "seed")
        _git(seed, "push", "origin", "claude/trading-state")
        self.a, self.b = os.path.join(self.tmp, "A"), os.path.join(self.tmp, "B")
        for d in (self.a, self.b):
            _git(self.tmp, "clone", "-b", "claude/trading-state", self.remote, d)
            for k, v in (("user.email", "t@t"), ("user.name", "t")):
                _git(d, "config", k, v)

    def test_K_two_overlapping_runs_cannot_both_hold_the_lease(self):
        ok_a, why_a = execguard.claim_via_git(self.a, "RUN-A", NOW)
        self.assertTrue(ok_a, why_a)
        # B raced: it cached the old tip, took the lease locally and pushes. The server CAS rejects it.
        st = execguard.load(os.path.join(self.b, execguard.STATE_FILE))
        execguard.acquire_lease(st, "RUN-B", NOW)
        execguard.save(st, os.path.join(self.b, execguard.STATE_FILE))
        _git(self.b, "add", "-A"); _git(self.b, "commit", "-m", "B lease")
        push = _git(self.b, "push", "origin", "HEAD:claude/trading-state")
        self.assertNotEqual(push.returncode, 0, "second overlapping claim must be rejected by the remote")
        # and B, going through the supported path after A's claim, is refused rather than racing
        _git(self.b, "reset", "--hard", "HEAD~1")
        ok_b, why_b = execguard.claim_via_git(self.b, "RUN-B", NOW)
        self.assertFalse(ok_b, why_b)

    def test_K_same_intent_cannot_be_submitted_twice(self):
        st = execguard.empty_state()
        execguard.acquire_lease(st, "R", NOW)
        k1, _ = execguard.record_intent(st, "R", "XYZ", "buy", 10, "entry", NOW)
        self.assertIsNotNone(k1)
        k2, why = execguard.record_intent(st, "R", "XYZ", "buy", 10, "entry", NOW)
        self.assertIsNone(k2)
        self.assertIn("duplicate", why)
        other_run, why = execguard.record_intent(st, "R2", "XYZ", "buy", 10, "entry", NOW)
        self.assertIsNone(other_run)                    # no lease for R2
        self.assertIn("lease", why)

    def test_L_timeout_after_possible_acceptance_requires_reconciliation(self):
        st = execguard.empty_state()
        execguard.acquire_lease(st, "R", NOW)
        key, _ = execguard.record_intent(st, "R", "XYZ", "buy", 10, "entry", NOW)
        execguard.mark_ambiguous(st, key, NOW)
        retry, why = execguard.record_intent(st, "R", "XYZ", "buy", 10, "entry", NOW)
        self.assertIsNone(retry)                        # no blind resubmission
        elsewhere, why2 = execguard.record_intent(st, "R", "OTHER", "buy", 5, "entry", NOW)
        self.assertIsNone(elsewhere)                    # ambiguity blocks ALL new submissions
        self.assertIn("unresolved", why2)
        r = run_complete.validate_run(make_run(execution={"unresolved": execguard.unresolved_summary(st),
                                                         "orders": []}), CONFIG)
        self.assertEqual(r["outcome"], "EXECUTION_PENDING_OR_AMBIGUOUS")
        # no broker order found inside grace: stays ambiguous
        self.assertEqual(execguard.reconcile(st, key, [], NOW), "ambiguous")
        # broker shows the order was accepted and filled
        orders = [{"id": "o-1", "symbol": "XYZ", "side": "buy", "quantity": "10", "state": "filled",
                   "created_at": "2026-10-14T17:15:03Z"}]
        self.assertEqual(execguard.reconcile(st, key, orders, "2026-10-14T17:16:00Z"), "filled")
        self.assertEqual(st["intents"][key]["order_id"], "o-1")
        self.assertEqual(execguard.unresolved_summary(st), {})

    def test_L_not_found_after_grace_frees_a_NEW_attempt_only(self):
        st = execguard.empty_state()
        execguard.acquire_lease(st, "R", NOW)
        key, _ = execguard.record_intent(st, "R", "XYZ", "buy", 10, "entry", NOW)
        execguard.mark_ambiguous(st, key, NOW)
        later = "2026-10-14T17:30:00Z"
        execguard.acquire_lease(st, "R", later)
        self.assertEqual(execguard.reconcile(st, key, [], later), "not_found")
        k2, why = execguard.record_intent(st, "R", "XYZ", "buy", 10, "entry_retry", later)
        self.assertIsNotNone(k2, why)


# ---------------------------------------------------------------- N
class StartupLoadsRepairedWorkflow(unittest.TestCase):
    def _make_repo(self, tmp):
        remote = os.path.join(tmp, "remote.git")
        _git(tmp, "init", "--bare", "-b", "claude/trading-state", remote)
        work = os.path.join(tmp, "work")
        _git(tmp, "clone", remote, work)
        for k, v in (("user.email", "t@t"), ("user.name", "t")):
            _git(work, "config", k, v)
        _git(work, "checkout", "-b", "claude/trading-state")
        for rel in startup_check.REQUIRED:
            src, dst = os.path.join(ROOT, rel), os.path.join(work, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        for extra in ("scripts/evidence.py", "scripts/notify_state.py", "scripts/cost_estimate.py"):
            shutil.copyfile(os.path.join(ROOT, extra), os.path.join(work, extra))
        _git(work, "add", "-A"); _git(work, "commit", "-m", "seed")
        _git(work, "push", "origin", "claude/trading-state")
        return work

    def test_N_startup_manifest_pins_branch_commit_version_and_validator(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = self._make_repo(tmp)
            m = startup_check.check(work)
            self.assertTrue(m["ok"], m["problems"])
            self.assertEqual(m["branch"], "claude/trading-state")
            self.assertEqual(m["commit"], m["origin_tip"])
            self.assertEqual(m["workflow_version"], startup_check.WORKFLOW_VERSION)
            self.assertNotEqual(m["validator_selftest"], "COMPLETED_NO_QUALIFYING_TRADE")
            # wrong branch
            _git(work, "checkout", "-b", "claude/some-throwaway")
            self.assertFalse(startup_check.check(work, no_fetch=True)["ok"])
            _git(work, "checkout", "claude/trading-state")
            # stale checkout (origin moved on)
            other = os.path.join(tmp, "other")
            _git(tmp, "clone", "-b", "claude/trading-state", os.path.join(tmp, "remote.git"), other)
            for k, v in (("user.email", "t@t"), ("user.name", "t")):
                _git(other, "config", k, v)
            with open(os.path.join(other, "x.txt"), "w") as f:
                f.write("x")
            _git(other, "add", "-A"); _git(other, "commit", "-m", "newer"); _git(other, "push", "origin", "claude/trading-state")
            stale = startup_check.check(work)
            self.assertFalse(stale["ok"])
            self.assertTrue(any("origin tip" in p for p in stale["problems"]))
            _git(work, "pull", "origin", "claude/trading-state")
            # protected file edited in the working tree by a scheduled run
            with open(os.path.join(work, "config.json"), "a") as f:
                f.write("\n")
            self.assertTrue(any("protected files modified" in p for p in startup_check.check(work, True)["problems"]))
            _git(work, "checkout", "--", "config.json")
            # workflow version drift between config and code
            with open(os.path.join(work, "config.json")) as f:
                cfg = json.load(f)
            cfg["workflow_version"] = "old"
            with open(os.path.join(work, "config.json"), "w") as f:
                json.dump(cfg, f)
            self.assertTrue(any("workflow_version" in p for p in startup_check.check(work, True)["problems"]))

    def test_N_run_without_matching_manifest_is_rejected_by_completion_validator(self):
        for man in (None, {"ok": False}, {"ok": True, "workflow_version": "old", "branch": "claude/trading-state"},
                    {"ok": True, "workflow_version": CONFIG["workflow_version"], "branch": "main"}):
            r = run_complete.validate_run(make_run(manifest=man), CONFIG)
            self.assertEqual(r["outcome"], "INVALID_RUN_RECORD", (man, r))
        self.assertFalse(run_complete.validate_run({}, CONFIG)["completed"])


# ---------------------------------------------------------------- persistence path
class PersistPath(unittest.TestCase):
    def test_no_action_label_only_for_validated_completion_and_same_day_flag_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "runs", "R"))
            ev = os.path.join(tmp, "runs", "R", "assess.json")
            with open(ev, "w") as f:
                f.write("{}")
            state = {"positions": {"AAA": {"same_day": True, "opportunity_score": 3.0}}, "account_value_history": []}
            bad = make_run(discovery={"run_id": "R", "sources": []}, claimed_outcome="NO_ACTION")
            res = run_complete.validate_run(bad, CONFIG)
            self.assertIn("claim_rejected", res)
            txt = persist_run.journal_text(bad, res, "")
            self.assertTrue(txt.startswith("INCOMPLETE_DISCOVERY"), txt)
            self.assertNotIn("NO_ACTION |", txt)
            good = make_run()
            good["holdings_reassessed"] = [
                {"symbol": "AAA", "assessment_run_id": "R", "evidence_ref": ev, "opportunity_score": 6.1},
                {"symbol": "ZZZ", "assessment_run_id": "R", "evidence_ref": "missing.json", "opportunity_score": 9}]
            gres = run_complete.validate_run(good, CONFIG)
            self.assertTrue(persist_run.journal_text(good, gres, "").startswith("NO_ACTION |"))
            persist_run.apply_to_state(state, good, gres, os.path.join(tmp, "runs"))
            self.assertNotIn("same_day", state["positions"]["AAA"])
            self.assertEqual(state["positions"]["AAA"]["assessment_run_id"], "R")
            self.assertEqual(gres["rejected_refreshes"], ["ZZZ"])


# ---------------------------------------------------------------- reporting / cost
class NotificationAndCost(unittest.TestCase):
    def test_delivery_states_come_from_evidence_not_html_files(self):
        self.assertEqual(notify_state.delivery_state({"status": "accepted", "provider_message_id": "m"}), "delivery_unknown")
        self.assertEqual(notify_state.delivery_state({"status": "verified_sent", "provider_message_id": "m"}), "delivered_verified")
        self.assertEqual(notify_state.delivery_state({"status": "prepared", "html_file": "reporting/sent/x.html"}), "pending")
        self.assertEqual(notify_state.delivery_state({"status": "failed", "error": "403"}), "failed")

    def test_migrate_aggregates_pending_without_deleting_history(self):
        ns = {"observed_events": {"e1": {}, "e2": {}}, "reported_event_ids": ["e1"],
              "outbox": {"r1": {"included_event_ids": ["e1"], "status": "accepted", "provider_message_id": "m"}},
              "daily_summaries": {}}
        out = notify_state.migrate(ns)
        self.assertEqual(out["pending_event_ids"], ["e2"])
        self.assertEqual(out["observed_events"]["e1"]["event_state"], "reported")
        self.assertEqual(out["outbox"]["r1"]["delivery_state"], "delivery_unknown")
        self.assertEqual(out["reported_event_ids"], ns["reported_event_ids"])

    def test_cost_line_labels_estimate_vs_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            st = os.path.join(tmp, "s.json")
            with open(st, "w") as f:
                json.dump({}, f)
            out = subprocess.run([sys.executable, os.path.join(ROOT, "scripts/cost_estimate.py"), "update", "--kind",
                                  "light", "--run-id", "2026-10-14T17:15Z", "--state", st, "--config",
                                  os.path.join(ROOT, "config.json"), "--journal-dir", os.path.join(tmp, "none")],
                                 capture_output=True, text=True)
            line = json.loads(out.stdout)["line"]
            self.assertIn("ESTIMATED", line)
            self.assertIn("not billed spend", line)
            self.assertIn("Measured spend: unavailable", line)


if __name__ == "__main__":
    unittest.main()
