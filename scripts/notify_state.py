#!/usr/bin/env python3
"""
Notification-state normalization and audit (no network access, no sending).

Delivery states (derived from recorded evidence only; an HTML file on disk is NOT evidence):
  pending            prepared/needed, no send attempt recorded
  failed             a send attempt recorded an error
  delivery_unknown   provider accepted/sent but no mailbox verification recorded
  delivered_verified provider message id AND a verification timestamp recorded
Event states: pending (in no outbox entry) | reported (in an entry) with the entry's delivery state.

  python3 scripts/notify_state.py audit --notification notification_state.json \
      [--sessions 2026-10-05,2026-10-06,...]
  python3 scripts/notify_state.py migrate --notification notification_state.json --out migrated.json

`migrate` is non-destructive: it ADDS derived fields (delivery_state, event_state, aggregate
pending) and never deletes or rewrites historical records. It is applied to production state
only by the first run after promotion (so it cannot clobber concurrent saves).
"""
import argparse
import copy
import json
import sys

ACCEPTED_ONLY = {"accepted", "sent", "provider_accepted"}


def delivery_state(entry):
    st = entry.get("status")
    if entry.get("error") or st in ("failed", "error"):
        return "failed"
    if st in ("pending", "prepared", None) and not entry.get("provider_message_id"):
        return "pending"
    if entry.get("provider_message_id") and (st == "verified_sent" or entry.get("verified_in_mailbox_at")):
        return "delivered_verified"
    if entry.get("provider_message_id") or st in ACCEPTED_ONLY:
        return "delivery_unknown"
    return "pending"


def daily_delivery(ns, d):
    """A daily_summaries row is judged by its own evidence, else by the outbox entry its report_id names."""
    box = (ns.get("outbox") or {}).get(d.get("report_id"))
    if d.get("status") or d.get("provider_message_id"):
        own = delivery_state(d)
        if own != "pending" or not box:
            return own
    if box:
        return delivery_state(box)
    return "pending_no_record"


def audit(ns, sessions=None):
    out, obs = {}, ns.get("observed_events") or {}
    outbox = ns.get("outbox") or {}
    included = set()
    for e in outbox.values():
        included |= set(e.get("included_event_ids") or [])
    reported = set(ns.get("reported_event_ids") or [])
    out["outbox_delivery_states"] = {}
    for rid, e in outbox.items():
        out["outbox_delivery_states"].setdefault(delivery_state(e), []).append(rid)
    out["observed_never_included"] = sorted(k for k in obs if k not in included)
    out["reported_ids_without_observed_record"] = sorted(k for k in reported if k not in obs)
    out["reported_ids_not_in_any_outbox_entry"] = sorted(k for k in reported if k not in included)
    ds = ns.get("daily_summaries") or {}
    out["daily_close_delivery"] = {k: daily_delivery(ns, v) for k, v in ds.items()}
    if sessions:
        have = {k.split(":")[-1] for k in ds}
        out["sessions_without_any_daily_close_record"] = [s for s in sessions if s not in have]
    out["last_successful_reconciliation_at"] = ns.get("last_successful_reconciliation_at")
    return out


def migrate(ns):
    new = copy.deepcopy(ns)
    included = {}
    for rid, e in (new.get("outbox") or {}).items():
        e["delivery_state"] = delivery_state(e)
        for ev in e.get("included_event_ids") or []:
            included.setdefault(ev, []).append(rid)
    for k, ev in (new.get("observed_events") or {}).items():
        ev["event_state"] = "reported" if k in included else "pending"
        ev["reported_in"] = included.get(k, [])
    for k, d in (new.get("daily_summaries") or {}).items():
        d["delivery_state"] = daily_delivery(new, d)
    new["pending_event_ids"] = sorted(k for k, ev in (new.get("observed_events") or {}).items()
                                      if ev["event_state"] == "pending")
    new["schema_version"] = max(2, int(new.get("schema_version") or 1))
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["audit", "migrate"])
    ap.add_argument("--notification", required=True)
    ap.add_argument("--sessions")
    ap.add_argument("--out")
    a = ap.parse_args()
    ns = json.load(open(a.notification))
    if a.cmd == "audit":
        print(json.dumps(audit(ns, a.sessions.split(",") if a.sessions else None), indent=2))
    else:
        json.dump(migrate(ns), open(a.out, "w"), indent=2)
        print(f"wrote {a.out}")


if __name__ == "__main__":
    sys.exit(main())
