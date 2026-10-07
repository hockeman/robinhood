#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("scoring", HERE / "scoring.py")
scoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scoring)


class ScoringV2Tests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "min_signal_quality_score": 4.0,
            "min_explosive_upside_score": 6.0,
            "min_remaining_upside_score": 5.0,
            "min_opportunity_score": 6.0,
            "high_conviction_opportunity_score": 8.0,
            "exceptional_opportunity_score": 9.0,
            "max_chase_pct_above_signal_price": 80,
            "rotation_min_opportunity_advantage": 0.75,
            "legacy_default_score": 0,
            "legacy_old_score_cap_for_opportunity": 4.0,
            "min_cash_reserve_usd": 5.0,
            "idle_cash_escalation_pct_of_account": 2.5,
            "idle_cash_critical_pct_of_account": 6.0,
            "idle_cash_target_pct_of_account": 1.5,
            "idle_cash_min_candidates_deep_reviewed": 2,
            "idle_cash_min_independent_catalyst_checks": 1,
            "tactical_cash_min_signal_quality_score": 3.0,
            "tactical_cash_min_explosive_upside_score": 3.5,
            "tactical_cash_min_remaining_upside_score": 3.0,
            "tactical_cash_min_opportunity_score": 3.5,
            "tactical_cash_max_risk_penalty": 3.0,
            "tactical_cash_position_max_pct_of_account": 50,
            "tactical_cash_initial_stop_loss_pct": 15,
            "require_v2_rescore_before_no_action": True,
            "v2_rescore_min_position_usd": 100.0,
        }

    def test_kod_like_transformational_runner_not_rejected_only_for_chase(self):
        candidate = {
            "symbol": "KODLIKE",
            "signal_quality_score": 9,
            "catalyst_magnitude_score": 10,
            "volume_price_discovery_score": 10,
            "structure_squeeze_score": 6,
            "remaining_upside_score": 8,
            "dilution_risk_score": 0,
            "exhaustion_risk_score": 0,
            "primary_source_verified": True,
            "catalyst_verified": True,
            "transformational": True,
            "continuation_confirmed": True,
            "chase_pct": 139,
            "disqualifier": False,
        }
        result = scoring.opportunity_score(candidate, self.config)
        self.assertTrue(result["eligible"], result)
        self.assertGreaterEqual(result["opportunity_score"], 8.5)
        self.assertEqual(result["target_50_assessment"], "plausible")
        self.assertIn(result["target_100_assessment"], {"possible", "plausible", "unusually_plausible"})

    def test_transformational_chase_requires_continuation(self):
        candidate = {
            "signal_quality_score": 9,
            "catalyst_magnitude_score": 10,
            "volume_price_discovery_score": 9,
            "structure_squeeze_score": 7,
            "remaining_upside_score": 8,
            "primary_source_verified": True,
            "catalyst_verified": True,
            "transformational": True,
            "continuation_confirmed": False,
            "chase_pct": 110,
        }
        result = scoring.opportunity_score(candidate, self.config)
        self.assertFalse(result["eligible"])
        self.assertTrue(any("continuation" in r for r in result["reasons"]))

    def test_non_transformational_large_chase_is_rejected(self):
        candidate = {
            "signal_quality_score": 8,
            "catalyst_magnitude_score": 8,
            "volume_price_discovery_score": 9,
            "structure_squeeze_score": 8,
            "remaining_upside_score": 8,
            "primary_source_verified": True,
            "catalyst_verified": True,
            "transformational": False,
            "continuation_confirmed": True,
            "chase_pct": 100,
        }
        result = scoring.opportunity_score(candidate, self.config)
        self.assertFalse(result["eligible"])
        self.assertTrue(any("non-transformational chase" in r for r in result["reasons"]))

    def test_unsupported_pump_rejected_even_with_volume(self):
        candidate = {
            "signal_quality_score": 2,
            "catalyst_magnitude_score": 1,
            "volume_price_discovery_score": 10,
            "structure_squeeze_score": 9,
            "remaining_upside_score": 4,
            "primary_source_verified": False,
            "catalyst_verified": False,
            "transformational": False,
            "continuation_confirmed": False,
            "chase_pct": 20,
        }
        result = scoring.opportunity_score(candidate, self.config)
        self.assertFalse(result["eligible"])
        self.assertIn("primary source not verified", result["reasons"])
        self.assertIn("catalyst not verified", result["reasons"])

    def test_tactical_cash_candidate_can_qualify_below_standard_gate(self):
        candidate = {
            "symbol": "TACT",
            "signal_quality_score": 6,
            "catalyst_magnitude_score": 6,
            "volume_price_discovery_score": 6,
            "structure_squeeze_score": 4,
            "remaining_upside_score": 4.5,
            "dilution_risk_score": 1,
            "exhaustion_risk_score": 2,
            "primary_source_verified": True,
            "catalyst_verified": True,
            "transformational": False,
            "continuation_confirmed": True,
            "chase_pct": 20,
            "disqualifier": False,
        }
        result = scoring.opportunity_score(candidate, self.config)
        self.assertFalse(result["eligible"], result)
        self.assertTrue(result["cash_deployment_eligible"], result)

    def test_tactical_cash_can_use_verified_sector_catalyst_plus_live_heat(self):
        candidate = {
            "symbol": "SECTOR",
            "signal_quality_score": 6,
            "catalyst_magnitude_score": 5,
            "volume_price_discovery_score": 8,
            "structure_squeeze_score": 5,
            "remaining_upside_score": 5,
            "dilution_risk_score": 1,
            "exhaustion_risk_score": 2,
            "primary_source_verified": False,
            "catalyst_verified": False,
            "market_catalyst_verified": True,
            "live_heat_verified": True,
            "transformational": False,
            "continuation_confirmed": True,
            "chase_pct": 15,
            "disqualifier": False,
        }
        result = scoring.opportunity_score(candidate, self.config)
        self.assertTrue(result["cash_deployment_eligible"], result)

    def test_tactical_cash_candidate_still_rejects_unverified_hype(self):
        candidate = {
            "symbol": "HYPE",
            "signal_quality_score": 6,
            "catalyst_magnitude_score": 6,
            "volume_price_discovery_score": 7,
            "structure_squeeze_score": 6,
            "remaining_upside_score": 5,
            "dilution_risk_score": 0,
            "exhaustion_risk_score": 1,
            "primary_source_verified": False,
            "catalyst_verified": False,
            "transformational": False,
            "continuation_confirmed": True,
            "chase_pct": 10,
            "disqualifier": False,
        }
        result = scoring.opportunity_score(candidate, self.config)
        self.assertFalse(result["cash_deployment_eligible"], result)

    def test_old_score_ten_is_capped_for_v2_rotation(self):
        positions = {
            "OLD": {
                "score": 10,
                "score_signal_class": "durable",
                "score_date": "2026-10-05",
                "entry_date": "2026-10-01",
                "same_day": False,
                "value_usd": 3000,
            }
        }
        result = scoring.rotation_eligible(
            7.0,
            positions,
            "2026-10-05",
            rotation_min_opportunity_advantage=0.75,
            min_opportunity_score=6.0,
            legacy_old_score_cap=4.0,
        )
        self.assertTrue(result["eligible"], result)
        self.assertEqual(result["weakest_effective_opportunity_score"], 4.0)

    def test_transformational_decay_is_slower_than_durable(self):
        t = scoring.decay_multiplier("transformational", 10)
        d = scoring.decay_multiplier("durable", 10)
        self.assertGreater(t, d)
        self.assertEqual(t, 0.60)
        self.assertEqual(d, 0.25)

    def test_meaningful_old_position_forces_v2_rescore(self):
        positions = {
            "OLD": {
                "score": 10,
                "value_usd": 1800,
                "entry_date": "2026-09-24",
                "same_day": False,
            }
        }
        live = {
            "stop_orders_ok": True,
            "account_value": 7500,
            "deployable_buying_power": 50,
            "session_allows_entries": True,
        }
        result = scoring.fast_check(positions, live, "2026-10-05", self.config)
        self.assertTrue(result["actionable"])
        self.assertTrue(any("V2_POSITION_RESCORE_DUE" in r for r in result["reasons"]))

    def test_fractional_dust_does_not_force_v2_rescore(self):
        positions = {
            "DUST": {
                "score": 4,
                "value_usd": 21,
                "entry_date": "2026-09-23",
                "same_day": False,
            }
        }
        live = {
            "stop_orders_ok": True,
            "account_value": 7500,
            "deployable_buying_power": 50,
            "session_allows_entries": True,
        }
        result = scoring.fast_check(positions, live, "2026-10-05", self.config)
        self.assertFalse(any("V2_POSITION_RESCORE_DUE" in r for r in result["reasons"]))

    def test_explicit_deployable_buying_power_is_not_reserve_adjusted_twice(self):
        live = {
            "account_value": 7512.55,
            "deployable_buying_power": 1501.41,
            "session_allows_entries": True,
        }
        status = scoring.idle_cash_status(live, self.config)
        self.assertEqual(status["deployable_buying_power"], 1501.41)

    def test_idle_cash_above_ten_percent_forces_deep_search(self):
        live = {
            "stop_orders_ok": True,
            "account_value": 7512.55,
            "deployable_buying_power": 1501.41,
            "session_allows_entries": True,
            "idle_cash_escalation_completed": False,
        }
        result = scoring.fast_check({}, live, "2026-10-05", self.config)
        self.assertTrue(result["actionable"])
        self.assertTrue(any("IDLE_CASH_" in r for r in result["reasons"]))

    def test_idle_cash_completion_claim_without_quota_stays_actionable(self):
        live = {
            "stop_orders_ok": True,
            "account_value": 7512.55,
            "deployable_buying_power": 1501.41,
            "session_allows_entries": True,
            "idle_cash_escalation_completed": True,
            "known_candidates": {},
            "independent_catalyst_sweep_complete": False,
            "independent_catalyst_symbols_reviewed": [],
        }
        result = scoring.fast_check({}, live, "2026-10-05", self.config)
        self.assertTrue(any("IDLE_CASH_REVIEW_INCOMPLETE" in r for r in result["reasons"]))

    def test_idle_cash_completed_can_finish_after_quota_if_no_tactical_candidate(self):
        live = {
            "stop_orders_ok": True,
            "account_value": 7512.55,
            "deployable_buying_power": 1501.41,
            "session_allows_entries": True,
            "idle_cash_escalation_completed": True,
            "known_candidates": {
                "AAA": {"current_run_deep_reviewed": True, "cash_deployment_eligible": False},
                "BBB": {"current_run_deep_reviewed": True, "cash_deployment_eligible": False},
            },
            "independent_catalyst_sweep_complete": True,
            "independent_catalyst_symbols_reviewed": ["CCC"],
        }
        result = scoring.fast_check({}, live, "2026-10-05", self.config)
        self.assertFalse(any("IDLE_CASH_" in r for r in result["reasons"]))

    def test_tactical_candidate_keeps_run_actionable_until_deployed(self):
        live = {
            "stop_orders_ok": True,
            "account_value": 7512.55,
            "deployable_buying_power": 1501.41,
            "session_allows_entries": True,
            "idle_cash_escalation_completed": True,
            "known_candidates": {
                "AAA": {
                    "current_run_deep_reviewed": True,
                    "cash_deployment_eligible": True,
                    "position_opened_this_run": False,
                },
                "BBB": {"current_run_deep_reviewed": True, "cash_deployment_eligible": False},
            },
            "independent_catalyst_sweep_complete": True,
            "independent_catalyst_symbols_reviewed": ["CCC"],
        }
        result = scoring.fast_check({}, live, "2026-10-05", self.config)
        self.assertTrue(any("CASH_DEPLOYMENT_DUE" in r for r in result["reasons"]))

    def test_critical_idle_cash_uses_critical_reason(self):
        live = {
            "stop_orders_ok": True,
            "account_value": 7500,
            "deployable_buying_power": 2000,
            "session_allows_entries": True,
        }
        result = scoring.fast_check({}, live, "2026-10-05", self.config)
        self.assertTrue(any("IDLE_CASH_CRITICAL" in r for r in result["reasons"]))

    def test_fast_check_trips_on_acceleration_and_filing(self):
        live = {
            "stop_orders_ok": True,
            "scanner_acceleration_symbols": ["AAA"],
            "fresh_filing_symbols": ["BBB"],
        }
        result = scoring.fast_check({}, live, "2026-10-05", self.config)
        self.assertTrue(result["actionable"])
        self.assertTrue(any("SCANNER_ACCELERATION" in r for r in result["reasons"]))
        self.assertTrue(any("FRESH_PRIMARY_SOURCE" in r for r in result["reasons"]))

    def test_oct6_apog_near_miss_now_deploys(self):
        """Regression: 2026-10-06 APOG (verified 8-K beat/raise) was rejected by 0.25
        against the old 4.5 tactical bar while $2.3k sat idle all session."""
        cand = {
            "symbol": "APOG", "signal_quality_score": 9, "catalyst_magnitude_score": 4.5,
            "volume_price_discovery_score": 5, "structure_squeeze_score": 3,
            "remaining_upside_score": 3.5, "dilution_risk_score": 1, "exhaustion_risk_score": 3,
            "primary_source_verified": True, "catalyst_verified": True,
        }
        r = scoring.opportunity_score(cand, self.config)
        self.assertTrue(r["cash_deployment_eligible"], r["cash_deployment_reasons"])
        self.assertIn(r["deployment_tier"], ("standard", "tactical"))

    def test_best_available_needs_some_reason_and_no_disqualifier(self):
        base = {
            "symbol": "MOM", "signal_quality_score": 3, "catalyst_magnitude_score": 3,
            "volume_price_discovery_score": 6, "structure_squeeze_score": 2,
            "remaining_upside_score": 4, "dilution_risk_score": 1, "exhaustion_risk_score": 2,
            "primary_source_verified": False, "catalyst_verified": False,
        }
        self.assertFalse(scoring.opportunity_score(base, self.config)["best_available_eligible"])
        base["momentum_verified"] = True
        r = scoring.opportunity_score(base, self.config)
        self.assertTrue(r["best_available_eligible"], r["best_available_reasons"])
        base["disqualifier"] = True
        self.assertFalse(scoring.opportunity_score(base, self.config)["best_available_eligible"])

    def test_completion_claim_cannot_override_deployable_candidate(self):
        live = {
            "stop_orders_ok": True, "account_value": 7100, "deployable_buying_power": 2357,
            "session_allows_entries": True, "idle_cash_escalation_completed": True,
            "known_candidates": {
                "AAA": {"current_run_deep_reviewed": True, "best_available_eligible": True},
                "BBB": {"current_run_deep_reviewed": True}, "CCC": {"current_run_deep_reviewed": True},
                "DDD": {"current_run_deep_reviewed": True}, "EEE": {"current_run_deep_reviewed": True},
            },
            "independent_catalyst_sweep_complete": True,
            "independent_catalyst_symbols_reviewed": ["X", "Y"],
        }
        result = scoring.fast_check({}, live, "2026-10-07", self.config)
        self.assertTrue(any("CASH_DEPLOYMENT_DUE" in r for r in result["reasons"]))

    def test_small_idle_cash_is_actionable(self):
        live = {"stop_orders_ok": True, "account_value": 7000, "deployable_buying_power": 200,
                "session_allows_entries": True}
        result = scoring.fast_check({}, live, "2026-10-07", self.config)
        self.assertTrue(any("IDLE_CASH_" in r for r in result["reasons"]))

    def test_deploy_plan_ranks_tiers_and_sizes_to_target(self):
        live = {"account_value": 7117, "deployable_buying_power": 2357, "session_allows_entries": True}
        results = [
            {"symbol": "BEST", "deployment_tier": "best_available", "opportunity_score": 3.9,
             "explosive_upside_score": 4, "remaining_upside_score": 4},
            {"symbol": "TACT", "deployment_tier": "tactical", "opportunity_score": 3.6,
             "explosive_upside_score": 4, "remaining_upside_score": 3.5},
            {"symbol": "JUNK", "deployment_tier": "reject", "opportunity_score": 9,
             "explosive_upside_score": 9, "remaining_upside_score": 9},
        ]
        plan = scoring.deploy_plan(results, live, self.config)
        self.assertEqual(plan["pick"]["symbol"], "TACT")
        self.assertAlmostEqual(plan["pick"]["spend_usd"], 2357 - 7117 * 0.015, places=1)
        self.assertIsNone(scoring.deploy_plan([results[2]], live, self.config)["pick"])


if __name__ == "__main__":
    unittest.main()
