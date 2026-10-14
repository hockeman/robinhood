#!/usr/bin/env python3
"""
Verify what the recurring run actually loaded, before any research or trading.

  python3 scripts/startup_check.py --repo . --config config.json [--no-fetch] [--out run/manifest.json]

Checks: on branch claude/trading-state; HEAD == fetched origin tip; no uncommitted edits to
instruction/strategy/validator files; required files present; config.workflow_version ==
WORKFLOW_VERSION in this code; the completion validator is importable and REJECTS an empty run
(self-test). Emits a manifest {branch, commit, hashes, workflow_version}; run_complete.py refuses
a run record whose manifest does not match. Exit 0 only if every check passes. A failed check means
"no new trading risk" (PERSISTENCE.md).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

WORKFLOW_VERSION = "2026-10-14-repair-1"
CANONICAL_BRANCH = "claude/trading-state"
REQUIRED = ["AGENT.md", "WORKFLOW.md", "EXECUTION.md", "PERSISTENCE.md", "config.json", "state.json",
            "notification_state.json", "scripts/scoring.py", "scripts/run_complete.py",
            "scripts/persist_run.py", "scripts/lots.py", "scripts/discovery.py", "scripts/execguard.py",
            "scripts/build_inputs.py"]
PROTECTED = ["AGENT.md", "WORKFLOW.md", "EXECUTION.md", "PERSISTENCE.md", "config.json"]


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def check(repo, no_fetch=False):
    problems = []
    manifest = {"workflow_version_code": WORKFLOW_VERSION}
    if not no_fetch:
        f = _git(repo, "fetch", "origin", CANONICAL_BRANCH)
        if f.returncode:
            problems.append(f"fetch failed: {f.stderr.strip()}")
    br = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    tip = _git(repo, "rev-parse", f"origin/{CANONICAL_BRANCH}").stdout.strip()
    manifest.update(branch=br, commit=head, origin_tip=tip)
    if br != CANONICAL_BRANCH:
        problems.append(f"on branch {br!r}, not {CANONICAL_BRANCH!r}")
    if not tip or head != tip:
        problems.append(f"HEAD {head[:8]} != origin tip {tip[:8] or 'unknown'}")
    dirty = _git(repo, "status", "--porcelain", "--untracked-files=no").stdout.split("\n")
    edited = [l for l in dirty if l and any(l[3:].startswith(p) for p in PROTECTED + ["scripts/"])]
    if edited:
        problems.append(f"protected files modified in working tree: {edited}")
    missing = [p for p in REQUIRED if not os.path.exists(os.path.join(repo, p))]
    if missing:
        problems.append(f"required files missing: {missing}")
    hashes = {p: sha(os.path.join(repo, p)) for p in PROTECTED + ["scripts/scoring.py", "scripts/run_complete.py"]
              if os.path.exists(os.path.join(repo, p))}
    manifest["hashes"] = hashes
    try:
        with open(os.path.join(repo, "config.json")) as f:
            cfg = json.load(f)
        manifest["workflow_version"] = cfg.get("workflow_version")
        if cfg.get("workflow_version") != WORKFLOW_VERSION:
            problems.append(f"config workflow_version {cfg.get('workflow_version')!r} != code {WORKFLOW_VERSION!r}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"config unreadable: {exc}")
        cfg = {}
    try:
        sys.path.insert(0, os.path.join(repo, "scripts"))
        import run_complete  # noqa: E402
        probe = run_complete.validate_run({}, cfg)
        if probe["completed"]:
            problems.append("validator self-test FAILED: an empty run was accepted as complete")
        manifest["validator_selftest"] = probe["outcome"]
    except Exception as exc:  # noqa: BLE001
        problems.append(f"completion validator not importable: {exc}")
    manifest["ok"] = not problems
    manifest["problems"] = problems
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--config")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    m = check(a.repo, a.no_fetch)
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump(m, open(a.out, "w"), indent=2)
    print(json.dumps(m, indent=2))
    sys.exit(0 if m["ok"] else 5)


if __name__ == "__main__":
    main()
