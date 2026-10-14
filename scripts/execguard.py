#!/usr/bin/env python3
"""
Pre-execution coordination for every brokerage-WRITING path (entries, rotation
sells, protective-stop placement/replacement/cancel).

Mechanism (smallest viable in this environment): a lease + durable order-intent
ledger in `execution_state.json` on claude/trading-state, claimed with a PLAIN
(non-force) `git push` BEFORE any broker call. The push is a server-side
compare-and-swap on the branch ref, so two fresh clones cannot both hold the lease.
A local lock file would not work across fresh clones and is not used.

What this does NOT do (documented limitation): it cannot stop a session that
calls the broker without calling this module. It is cooperative, enforced only by
the bootstrap prompt and by scripts/persist_run.py refusing to record a run whose
order activity has no matching intents. The broker itself has no lock.

Intent lifecycle:
  intended -> submitted -> filled | partially_filled | cancelled | rejected
  intended/submitted --(timeout / exception / no ack)--> ambiguous
  ambiguous --(reconcile against broker orders)--> submitted|filled|not_found
A request that may have reached the broker is NEVER blindly retried.
"""
import datetime as dt
import hashlib
import json
import os
import subprocess

STATE_FILE = "execution_state.json"
TERMINAL = {"filled", "cancelled", "rejected", "not_found", "failed_definitive"}
OPEN_STATES = {"intended", "submitted", "partially_filled", "ambiguous"}


def _now(now=None):
    if now is None:
        return dt.datetime.now(dt.timezone.utc)
    if isinstance(now, str):
        return dt.datetime.fromisoformat(now.replace("Z", "+00:00"))
    return now


def empty_state():
    return {"schema_version": 1, "lease": None, "intents": {}}


def load(path=STATE_FILE):
    if not os.path.exists(path):
        return empty_state()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(state, path=STATE_FILE):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def intent_key(run_id, symbol, side, qty, purpose):
    raw = f"{run_id}|{symbol}|{side}|{qty}|{purpose}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def lease_active(state, now):
    lease = state.get("lease")
    if not lease:
        return False
    return _now(lease["expires_at"]) > _now(now)


def acquire_lease(state, run_id, now, ttl_minutes=20):
    """Pure state transition. Returns (ok, reason). Caller must then push (CAS)."""
    now = _now(now)
    lease = state.get("lease")
    if lease and lease["run_id"] != run_id and lease_active(state, now):
        return False, f"lease held by {lease['run_id']} until {lease['expires_at']}"
    state["lease"] = {
        "run_id": run_id,
        "acquired_at": now.isoformat(),
        "expires_at": (now + dt.timedelta(minutes=ttl_minutes)).isoformat(),
    }
    return True, "acquired"


def release_lease(state, run_id):
    if state.get("lease") and state["lease"]["run_id"] == run_id:
        state["lease"] = None


def blocking_intents(state, symbol=None):
    """Unresolved intents that forbid a new submission (ambiguous always blocks all symbols)."""
    out = []
    for iid, it in state["intents"].items():
        if it["status"] == "ambiguous":
            out.append(iid)
        elif it["status"] in OPEN_STATES and (symbol is None or it["symbol"] == symbol):
            out.append(iid)
    return out


def record_intent(state, run_id, symbol, side, qty, purpose, now, limit_price=None, lot_check=None):
    """
    Create a durable intent BEFORE any broker call. Refuses duplicates and anything
    that conflicts with an unresolved intent or an ambiguous earlier attempt.
    lot_check: for sells, the lots.classify() dict; a sell above sellable_qty, or on
    unverified lots, is refused (same-day / unknown quantity protection).
    """
    if not lease_active(state, now) or state["lease"]["run_id"] != run_id:
        return None, "no active lease for this run"
    key = intent_key(run_id, symbol, side, qty, purpose)
    if key in state["intents"]:
        return None, f"duplicate intent {key} (status {state['intents'][key]['status']}); reconcile, do not resubmit"
    blockers = blocking_intents(state, symbol)
    if blockers:
        return None, f"unresolved intents block submission: {blockers}"
    if side == "sell" and purpose != "protective_stop":
        if lot_check is None:
            return None, "sell requires lot_check (unknown lots block sale)"
        if not lot_check.get("lots_verified"):
            return None, "lots not reconciled to broker acquisition data; sale blocked"
        if float(qty) > float(lot_check.get("sellable_qty", 0.0)) + 1e-9:
            return None, (f"qty {qty} exceeds sellable_qty {lot_check.get('sellable_qty')} "
                          f"(restricted {lot_check.get('restricted_qty')}, unknown {lot_check.get('unknown_qty')})")
    state["intents"][key] = {
        "intent_id": key, "run_id": run_id, "symbol": symbol, "side": side, "qty": qty,
        "purpose": purpose, "limit_price": limit_price, "status": "intended",
        "created_at": _now(now).isoformat(), "order_id": None, "history": [],
    }
    return key, "recorded"


def transition(state, intent_id, status, now, order_id=None, note=""):
    it = state["intents"][intent_id]
    it["history"].append({"from": it["status"], "to": status, "at": _now(now).isoformat(), "note": note})
    it["status"] = status
    if order_id:
        it["order_id"] = order_id
    return it


def mark_ambiguous(state, intent_id, now, note="timeout/exception after possible broker acceptance"):
    return transition(state, intent_id, "ambiguous", now, note=note)


def reconcile(state, intent_id, broker_orders, now, grace_minutes=5):
    """
    Resolve an ambiguous/open intent against get_equity_orders output.
    A matching order (same symbol/side, qty within tolerance, created at/after the
    intent) means the request WAS accepted. No match inside the grace window keeps
    it ambiguous; after the window it becomes `not_found`, which frees a NEW intent.
    """
    it = state["intents"][intent_id]
    created = _now(it["created_at"])
    for o in broker_orders or []:
        if o.get("symbol") != it["symbol"] or o.get("side") != it["side"]:
            continue
        if abs(float(o.get("quantity") or 0) - float(it["qty"])) > 1e-6:
            continue
        o_ts = o.get("created_at")
        if o_ts and _now(o_ts) < created - dt.timedelta(seconds=1):
            continue
        st = o.get("state")
        mapped = {"filled": "filled", "partially_filled": "partially_filled",
                  "cancelled": "cancelled", "rejected": "rejected", "failed": "rejected"}.get(st, "submitted")
        transition(state, intent_id, mapped, now, order_id=o.get("id"), note="matched broker order")
        return mapped
    if _now(now) - created > dt.timedelta(minutes=grace_minutes):
        transition(state, intent_id, "not_found", now, note="no matching broker order after grace window")
        return "not_found"
    return it["status"]


def unresolved_summary(state):
    return {iid: it["status"] for iid, it in state["intents"].items() if it["status"] in OPEN_STATES}


# ---- git compare-and-swap claim -------------------------------------------

def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def claim_via_git(repo, run_id, now, branch="claude/trading-state", remote="origin", ttl_minutes=20):
    """
    Fetch the tip, require it equals local HEAD, take the lease, commit and PLAIN-push.
    Returns (ok, reason). If another run's push landed first the push is rejected
    (non-fast-forward) and we report not-acquired; never force-push.
    """
    f = _git(["fetch", remote, branch], repo)
    if f.returncode:
        return False, f"fetch failed: {f.stderr.strip()}"
    tip = _git(["rev-parse", f"{remote}/{branch}"], repo).stdout.strip()
    head = _git(["rev-parse", "HEAD"], repo).stdout.strip()
    if tip != head:
        return False, f"local HEAD {head[:8]} is not the branch tip {tip[:8]}; re-sync before claiming"
    path = os.path.join(repo, STATE_FILE)
    state = load(path)
    ok, reason = acquire_lease(state, run_id, now, ttl_minutes)
    if not ok:
        return False, reason
    save(state, path)
    _git(["add", STATE_FILE], repo)
    c = _git(["commit", "-m", f"exec lease {run_id}"], repo)
    if c.returncode:
        return False, f"commit failed: {c.stderr.strip() or c.stdout.strip()}"
    p = _git(["push", remote, f"HEAD:{branch}"], repo)
    if p.returncode:
        _git(["reset", "--hard", head], repo)
        return False, f"push rejected (another run claimed first): {p.stderr.strip()[-200:]}"
    return True, "lease claimed and pushed"


def push_state(repo, message, branch="claude/trading-state", remote="origin"):
    """Commit execution_state.json and plain-push it. Call after record_intent and
    BEFORE the broker call so the intent is durable and visible to other runs."""
    _git(["add", STATE_FILE], repo)
    c = _git(["commit", "-m", message], repo)
    if c.returncode:
        return False, f"commit failed: {c.stderr.strip() or c.stdout.strip()}"
    p = _git(["push", remote, f"HEAD:{branch}"], repo)
    if p.returncode:
        return False, f"push rejected: {p.stderr.strip()[-200:]}"
    return True, "pushed"
