#!/usr/bin/env python3
"""
The single sanctioned completion path. Validates the run record, then writes state,
evidence and the journal, then (optionally) commits and plain-pushes to claude/trading-state.

  python3 scripts/persist_run.py --run run/run.json --config config.json --state state.json \
      [--journal-dir journal] [--runs-dir runs] [--git .] [--note "short text"]

* The journal's first token is the VALIDATOR's outcome. "NO_ACTION" is written only for
  COMPLETED_NO_QUALIFYING_TRADE; a run that failed validation is journaled under its real outcome
  (INCOMPLETE_DISCOVERY, STALE_OR_FAILED_DATA, ...) and carries no "no action" claim.
* Held-position score refreshes are persisted only when they carry an assessment_run_id AND an
  evidence_ref that exists on disk (a date bump without a review is rejected).
* The persisted `same_day` flag is removed from every position (it is derived each run).
* Exit 0: completed outcome persisted. Exit 3: incomplete-but-honestly-persisted. Exit 4: git push
  rejected/failed (state NOT durable; see PERSISTENCE.md). Exit 5: validator/manifest unusable.
"""
import argparse
import json
import os
import subprocess
import sys

try:
    import run_complete
except ImportError:  # pragma: no cover
    from scripts import run_complete

CANDIDATE_CAP = 60


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def apply_to_state(state, run, result, runs_dir):
    ts = run["now"]
    acct = run.get("account") or {}
    if acct.get("account_value") is not None and result["outcome"] != "STALE_OR_FAILED_DATA":
        state.setdefault("account_value_history", []).append(
            {"ts": ts, "value": float(acct["account_value"]), "observed_at": acct.get("observed_at")})
        state["peak_account_value"] = max(float(state.get("peak_account_value") or 0), float(acct["account_value"]))
    state["last_run"] = ts
    disc = run.get("discovery") or {}
    state["last_discovery"] = {
        "run_id": run.get("run_id"), "outcome": result["outcome"], "at": ts,
        "window": run.get("catalyst_window"),
        "sources": {s["source_id"]: {"status": s.get("status"), "count": s.get("returned_count"),
                                     "ref": s.get("result_ref")} for s in disc.get("sources", [])},
        "scope": "see config.discovery.scope_statement",
    }
    if run.get("catalyst_seen") is not None:
        state["catalyst_seen"] = run["catalyst_seen"]
    recs = state.setdefault("candidate_records", {})
    for rec in (run.get("research") or {}).get("reviewed", []):
        recs[rec["symbol"]] = rec
    if len(recs) > CANDIDATE_CAP:  # drop oldest by first_observed_at, never the unexpired near-misses
        for sym in sorted(recs, key=lambda k: recs[k].get("first_observed_at") or "")[: len(recs) - CANDIDATE_CAP]:
            recs.pop(sym)
    state["deferred_research"] = (run.get("research") or {}).get("deferred", [])
    for h in run.get("holdings_reassessed") or []:
        pos = (state.get("positions") or {}).get(h["symbol"])
        ref = h.get("evidence_ref")
        if not pos or not h.get("assessment_run_id") or not ref or not os.path.exists(ref):
            result.setdefault("rejected_refreshes", []).append(h.get("symbol"))
            continue
        for k in ("opportunity_score", "opportunity_class", "explosive_upside_score",
                  "remaining_upside_score", "signal_quality_score"):
            if h.get(k) is not None:
                pos[k] = h[k]
        pos["opportunity_score_date"] = h.get("assessed_on") or ts[:10]
        pos["assessment_run_id"] = h["assessment_run_id"]
        pos["assessment_evidence_ref"] = ref
        pos.pop("material_development_since_assessment", None)
    for pos in (state.get("positions") or {}).values():
        pos.pop("same_day", None)
    return state


def journal_text(run, result, note):
    label = "NO_ACTION" if result["outcome"] == "COMPLETED_NO_QUALIFYING_TRADE" else result["outcome"]
    acct = run.get("account") or {}
    srcs = (run.get("discovery") or {}).get("sources", [])
    ok = sum(1 for s in srcs if s.get("status") in ("success", "successful_empty"))
    rv = (run.get("research") or {}).get("reviewed", [])
    lines = [
        f"{label} | {run['now']} | account_value={acct.get('account_value')} | "
        f"deployable={round(acct['deployable_buying_power'], 2) if acct.get('deployable_buying_power') is not None else None} | discovery={ok}/{len(srcs)} sources ok | "
        f"reviewed={len(rv)} deferred={len((run.get('research') or {}).get('deferred', []))} | "
        f"rotation_evaluated={(run.get('rotation') or {}).get('evaluated')}",
    ]
    for v in result["violations"]:
        lines.append(f"VIOLATION: {v}")
    if result.get("claim_rejected"):
        lines.append(f"CLAIM_REJECTED: {result['claim_rejected']}")
    for rec in rv:
        lines.append(f"CANDIDATE {rec['symbol']}: {rec.get('decision')} | {'; '.join(map(str, rec.get('decision_reasons') or []))}")
    if note:
        lines.append(note)
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--journal-dir", default="journal")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--git")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    run = json.load(open(a.run))
    config = json.load(open(a.config))
    try:
        result = run_complete.validate_run(run, config)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"validator failed: {exc}"}))
        sys.exit(5)
    state = json.load(open(a.state))
    apply_to_state(state, run, result, a.runs_dir)
    os.makedirs(a.runs_dir, exist_ok=True)
    rd = os.path.join(a.runs_dir, run["run_id"])
    os.makedirs(rd, exist_ok=True)
    json.dump({"run": run, "validator": result}, open(os.path.join(rd, "run.json"), "w"), indent=2)
    json.dump(state, open(a.state, "w"), indent=2)
    os.makedirs(a.journal_dir, exist_ok=True)
    jname = run["now"][:10] + "-" + run["now"][11:13] + run["now"][14:16] + ".md"
    jpath = os.path.join(a.journal_dir, jname)
    open(jpath, "w").write(journal_text(run, result, a.note))
    out = {"outcome": result["outcome"], "journal": jpath, "violations": result["violations"]}
    if a.git:
        _git(a.git, "add", "-A", a.state, a.journal_dir, a.runs_dir)
        c = _git(a.git, "commit", "-m", f"Run {run['run_id']}: {result['outcome']}")
        p = _git(a.git, "push", "origin", "HEAD:claude/trading-state")
        if p.returncode:
            out["push_error"] = p.stderr.strip()[-300:]
            print(json.dumps(out, indent=2))
            sys.exit(4)
        tip = _git(a.git, "ls-remote", "origin", "claude/trading-state").stdout.split()[0]
        out["observed_tip"] = tip
    print(json.dumps(out, indent=2))
    sys.exit(0 if result["completed"] else 3)


if __name__ == "__main__":
    main()
