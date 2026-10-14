#!/usr/bin/env python3
"""
Save a raw discovery result and emit its ledger entry (status derived, never asserted).

  python3 scripts/evidence.py record --run-id R --source-id "Agentic Nuclear Volume v2" \
      --kind scanner --params '{"scan_id":"..."}' --requested-at ISO --observed-at ISO \
      --raw raw_result.json --coverage "top-N rows only" [--data-as-of ISO] [--error msg] \
      --runs-dir runs --ledger runs/R/ledger.json [--row-path data.rows]

Status rule: --error => failed; raw file missing/unparseable => failed; count 0 => successful_empty;
else success. The raw result is copied under runs/<run>/ and hashed, so an empty scan has a
saved empty response rather than an absent one.
"""
import argparse
import json
import os
import shutil
import sys

try:
    import discovery
except ImportError:  # pragma: no cover
    from scripts import discovery


def _count(obj, row_path):
    """Number of rows in a raw tool result; None if no row list can be located."""
    def walk(cur, path):
        for part in filter(None, (path or "").split(".")):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur
    if row_path:
        node = walk(obj, row_path)
        return len(node) if isinstance(node, list) else None
    if isinstance(obj, list):
        return len(obj)
    for root in (obj, obj.get("data") if isinstance(obj, dict) else None):
        if isinstance(root, dict):
            for key in ("results", "rows", "instruments", "filings", "orders", "items", "earnings", "articles"):
                if isinstance(root.get(key), list):
                    return len(root[key])
    return None


def make_entry(run_id, source_id, kind, params, requested_at, observed_at, raw_path, coverage,
               runs_dir="runs", data_as_of=None, error=None, row_path=None, count=None):
    entry = {"source_id": source_id, "kind": kind, "params": params or {},
             "requested_at": requested_at, "observed_at": observed_at, "data_as_of": data_as_of,
             "coverage_note": coverage, "error": error}
    if error:
        entry.update(status="failed", returned_count=None, result_ref=None, result_sha256=None)
        return entry
    try:
        raw = json.load(open(raw_path, encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        entry.update(status="failed", error=f"raw result unreadable: {exc}", returned_count=None,
                     result_ref=None, result_sha256=None)
        return entry
    n = count if count is not None else _count(raw, row_path)
    if n is None:
        entry.update(status="failed", error="could not determine returned_count from raw result",
                     returned_count=None, result_ref=None, result_sha256=None)
        return entry
    safe = "".join(ch if ch.isalnum() else "_" for ch in source_id)[:60]
    dest_dir = os.path.join(runs_dir, run_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{safe}.json")
    shutil.copyfile(raw_path, dest)
    entry.update(status="success" if n > 0 else "successful_empty", returned_count=n,
                 result_ref=dest, result_sha256=discovery.sha256_of(raw))
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record"])
    for a in ("run-id", "source-id", "kind", "requested-at", "observed-at", "coverage", "ledger"):
        ap.add_argument(f"--{a}", required=True)
    for a in ("params", "raw", "data-as-of", "error", "runs-dir", "row-path"):
        ap.add_argument(f"--{a}")
    a = ap.parse_args()
    e = make_entry(a.run_id, a.source_id, a.kind, json.loads(a.params or "{}"), a.requested_at,
                   a.observed_at, a.raw, a.coverage, a.runs_dir or "runs", a.data_as_of, a.error, a.row_path)
    ledger = {"run_id": a.run_id, "sources": []}
    if os.path.exists(a.ledger):
        ledger = json.load(open(a.ledger))
    ledger["sources"] = [s for s in ledger["sources"] if s["source_id"] != a.source_id] + [e]
    os.makedirs(os.path.dirname(a.ledger) or ".", exist_ok=True)
    json.dump(ledger, open(a.ledger, "w"), indent=2)
    print(json.dumps({k: e[k] for k in ("source_id", "status", "returned_count", "result_ref")}))


if __name__ == "__main__":
    sys.exit(main())
