#!/usr/bin/env python3
"""
Lot-level sellability and same-day derivation (no network access).

Replaces the persisted `same_day` boolean. Same-day status is DERIVED each run
from acquisition records (broker tax lots preferred) and the current
America/New_York trading date. Nothing here guesses: a quantity whose
acquisition date cannot be reconciled is `unknown` and is not sellable.

Lot record:
  {"qty": float, "open_date": "YYYY-MM-DD" | None, "source": str, "selectable": bool | None}

Sources, best to worst:
  broker_tax_lots   get_equity_tax_lots rows (authoritative acquisition date)
  trade_ledger      trades.jsonl fills (used only if the sum matches broker qty)
  entry_date_fallback  single persisted entry_date; flagged unreconciled, so it
                    may RANK a holding but may never authorize a SALE.
"""
import datetime as dt
import json
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
QTY_TOL = 1e-4


def ny_date(now):
    """now: aware datetime or ISO string. Returns the America/New_York date string."""
    if isinstance(now, str):
        now = dt.datetime.fromisoformat(now.replace("Z", "+00:00"))
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    return now.astimezone(NY).date().isoformat()


def lots_from_tax_lots(tax_lot_rows):
    """Broker get_equity_tax_lots `tax_lots` -> lot records."""
    lots = []
    for r in tax_lot_rows or []:
        qty = float(r.get("quantity") or 0.0)
        if qty <= 0:
            continue
        lots.append(
            {
                "qty": qty,
                "open_date": r.get("open_date"),
                "source": "broker_tax_lots",
                "selectable": r.get("is_selectable"),
            }
        )
    return lots


def lots_from_trade_ledger(symbol, trades):
    """
    Net remaining buy lots from a trades.jsonl-style list, FIFO against sells.
    Tolerates both historical schemas (price|fill_price, ts|exit_date).
    Returns [] if the ledger holds no buys for the symbol.
    """
    buys, sells = [], []
    for t in trades or []:
        if t.get("symbol") != symbol:
            continue
        side = t.get("side")
        ts = t.get("ts") or t.get("entry_date") or t.get("exit_date")
        if side == "buy":
            buys.append({"qty": float(t["qty"]), "ts": ts})
        elif side == "sell":
            sells.append(float(t["qty"]))
    buys.sort(key=lambda b: b["ts"] or "")
    remaining = sum(sells)
    out = []
    for b in buys:
        take = min(b["qty"], remaining)
        remaining -= take
        left = b["qty"] - take
        if left > QTY_TOL:
            out.append(
                {"qty": left, "open_date": ny_date(b["ts"]) if b["ts"] else None,
                 "source": "trade_ledger", "selectable": None}
            )
    return out


def reconcile_lots(broker_qty, candidate_lots, fallback_entry_date=None):
    """
    Make lot quantities add up to the broker quantity. Any shortfall becomes an
    explicit `unknown` lot (open_date None). Excess (lots > broker qty) means the
    lot data is contradictory: the whole position is marked unknown.
    """
    broker_qty = float(broker_qty)
    lots = [dict(l) for l in (candidate_lots or [])]
    total = sum(l["qty"] for l in lots)
    if not lots and fallback_entry_date:
        return [
            {"qty": broker_qty, "open_date": fallback_entry_date,
             "source": "entry_date_fallback", "selectable": None}
        ]
    if total > broker_qty + QTY_TOL:
        return [{"qty": broker_qty, "open_date": None, "source": "contradictory_lots", "selectable": None}]
    if broker_qty - total > QTY_TOL:
        lots.append({"qty": broker_qty - total, "open_date": None,
                     "source": "unreconciled_remainder", "selectable": None})
    return lots


def classify(lots, today):
    """
    today: NY date string. Returns the sellability breakdown.
      sellable_qty      acquired before today, date known
      restricted_qty    acquired today (same-day; never intentionally sold)
      unknown_qty       acquisition date unknown (sale blocked until reconciled)
      verified          True only if every lot came from broker_tax_lots / trade_ledger
    """
    sellable = restricted = unknown = 0.0
    verified = True
    for l in lots:
        d = l.get("open_date")
        if l.get("source") in ("entry_date_fallback", "contradictory_lots", "unreconciled_remainder"):
            verified = False
        if d is None:
            unknown += l["qty"]
        elif d >= today:
            restricted += l["qty"]
        elif l.get("selectable") is False:
            # broker says still syncing; treat as not yet sellable, not as guessable
            restricted += l["qty"]
        else:
            sellable += l["qty"]
    return {
        "sellable_qty": round(sellable, 6),
        "restricted_qty": round(restricted, 6),
        "unknown_qty": round(unknown, 6),
        "same_day": restricted > QTY_TOL,
        "lots_verified": verified and unknown <= QTY_TOL,
    }


def position_view(symbol, broker_pos, tax_lot_rows, trades, state_pos, now):
    """One position's derived lot view. broker_pos is a get_equity_positions row."""
    today = ny_date(now)
    qty = float(broker_pos["quantity"])
    if tax_lot_rows is not None:
        cand = lots_from_tax_lots(tax_lot_rows)
    else:
        cand = lots_from_trade_ledger(symbol, trades)
        total = sum(l["qty"] for l in cand)
        if abs(total - qty) > QTY_TOL:
            cand = []  # ledger does not explain the broker quantity: do not trust it
    lots = reconcile_lots(qty, cand, fallback_entry_date=(state_pos or {}).get("entry_date"))
    view = classify(lots, today)
    view.update({"lots": lots, "qty": qty, "as_of_date": today})
    persisted = (state_pos or {}).get("same_day")
    if persisted is not None and bool(persisted) != view["same_day"]:
        view["persisted_same_day_ignored"] = bool(persisted)
    return view


if __name__ == "__main__":
    print(json.dumps({"today_ny": ny_date(dt.datetime.now(dt.timezone.utc))}))
