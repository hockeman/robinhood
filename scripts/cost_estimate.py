#!/usr/bin/env python3
"""
Running ESTIMATE of what it costs to run the trading routine with Claude.

This is a heuristic, not a bill: a scheduled run cannot read its own token
usage, so each run is classified (light / full / trade) and priced from the
per-run token profiles and per-MTok rates in config.json -> claude_cost_estimate.
Calibrate those numbers against the real usage page; the email says "est.".

Usage (once per run, before composing any email):
  python3 scripts/cost_estimate.py update --kind light|full|trade --run-id <ISO ts> \
      --state state.json --config config.json [--journal-dir journal]
Prints JSON incl. a ready-to-paste "line". Idempotent per run-id. The first call
backfills history from journal/ (one run per journal file).
"""
import argparse
import json
import pathlib
import re
import sys

KINDS = ("light", "full", "trade")
DEFAULTS = {
    "usd_per_mtok_input": 3.0,
    "usd_per_mtok_cache_read": 0.30,
    "usd_per_mtok_output": 15.0,
    "profiles": {
        "light": {"input_k": 40, "cache_read_k": 260, "output_k": 6},
        "full": {"input_k": 200, "cache_read_k": 1200, "output_k": 40},
        "trade": {"input_k": 260, "cache_read_k": 1600, "output_k": 55},
    },
}


def run_cost(kind, cfg):
    p = cfg["profiles"][kind]
    return (
        p["input_k"] * cfg["usd_per_mtok_input"]
        + p["cache_read_k"] * cfg["usd_per_mtok_cache_read"]
        + p["output_k"] * cfg["usd_per_mtok_output"]
    ) / 1000.0


def classify_journal(text):
    low = text.lower()
    if re.search(r"(bought|buy filled|entry filled|tactical cash deployment|rotation)", low) and "no_action" not in low[:12]:
        return "trade"
    if "deep_reviewed" in low or "idle_cash_review" in low:
        return "full"
    return "light"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["update", "record-actual"])
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--input-tokens", type=int)
    ap.add_argument("--cache-read-tokens", type=int, default=0)
    ap.add_argument("--output-tokens", type=int)
    ap.add_argument("--usage-source", help="where the token counts came from (e.g. usage page export)")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--journal-dir", default="journal")
    a = ap.parse_args()

    config = json.load(open(a.config))
    if a.cmd == "record-actual":
        # Measured usage only: caller supplies real token counts and their source. Never inferred.
        if a.input_tokens is None or a.output_tokens is None or not a.usage_source:
            ap.error("record-actual needs --input-tokens --output-tokens --usage-source")
        cfg0 = {**DEFAULTS, **(config.get("claude_cost_estimate") or {})}
        st = json.load(open(a.state))
        m = st.setdefault("claude_cost_measured", {"total_usd": 0.0, "runs": 0, "run_ids": [], "basis": "measured"})
        if a.run_id not in m["run_ids"]:
            usd = (a.input_tokens * cfg0["usd_per_mtok_input"] + a.cache_read_tokens * cfg0["usd_per_mtok_cache_read"]
                   + a.output_tokens * cfg0["usd_per_mtok_output"]) / 1e6
            m["total_usd"] = round(m["total_usd"] + usd, 4)
            m["runs"] += 1
            m["run_ids"] = (m["run_ids"] + [a.run_id])[-50:]
            m["last_source"] = a.usage_source
        json.dump(st, open(a.state, "w"), indent=2)
        print(json.dumps(m, indent=2))
        return
    if not a.kind:
        ap.error("update needs --kind")
    cfg = {**DEFAULTS, **(config.get("claude_cost_estimate") or {})}
    state = json.load(open(a.state))
    cc = state.get("claude_cost")
    if cc is None:
        cc = {"total_usd": 0.0, "by_day": {}, "runs": 0, "run_ids": [], "backfilled": False}
        jd = pathlib.Path(a.journal_dir)
        if jd.is_dir():
            for f in sorted(jd.glob("*.md")):
                day = f.name[:10]
                c = run_cost(classify_journal(f.read_text(errors="ignore")), cfg)
                cc["total_usd"] += c
                cc["by_day"][day] = cc["by_day"].get(day, 0.0) + c
                cc["runs"] += 1
        cc["backfilled"] = True
    this = run_cost(a.kind, cfg)
    if a.run_id not in cc["run_ids"]:
        day = a.run_id[:10]
        cc["total_usd"] += this
        cc["by_day"][day] = cc["by_day"].get(day, 0.0) + this
        cc["runs"] += 1
        cc["run_ids"] = (cc["run_ids"] + [a.run_id])[-50:]
    cc["total_usd"] = round(cc["total_usd"], 2)
    cc["by_day"] = {k: round(v, 2) for k, v in cc["by_day"].items()}
    cc["last_updated"] = a.run_id
    state["claude_cost"] = cc
    json.dump(state, open(a.state, "w"), indent=2)
    today = cc["by_day"].get(a.run_id[:10], 0.0)
    meas = state.get("claude_cost_measured")
    meas_txt = (f"Measured (token counts from {meas.get('last_source')}): ${meas['total_usd']:,.2f} over "
                f"{meas['runs']} run(s)." if meas and meas.get("runs") else
                "Measured spend: unavailable (scheduled runs cannot read their own token usage).")
    line = (
        f"ESTIMATED Claude cost to run this routine: ${cc['total_usd']:,.2f} total over {cc['runs']} runs "
        f"(${today:,.2f} today, ~${this:,.2f} this run) from ASSUMED per-run token profiles, not billed spend. "
        + meas_txt
    )
    print(json.dumps({"basis": "estimate_from_assumed_profiles", "total_usd": cc["total_usd"], "today_usd": today, "this_run_usd": round(this, 2),
                      "runs": cc["runs"], "line": line}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
