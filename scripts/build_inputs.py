#!/usr/bin/env python3
"""
Adapter: raw broker tool results + persisted state -> the JSON that scoring.py and
run_complete.py consume. This is the code that used to be a model's hand-edit of
state.json (the source of the stale `same_day` flags).

  python3 scripts/build_inputs.py --now 2026-10-14T17:15:00Z \
     --portfolio portfolio.json --positions broker_positions.json --orders open_orders.json \
     --quotes quotes.json --taxlots-dir taxlots/ --state state.json --trades trades.jsonl \
     --config config.json --out-dir run/

Each broker file is the raw tool result (with or without the {"data": ...} wrapper).
taxlots-dir holds <SYMBOL>.json from get_equity_tax_lots. A symbol without a tax-lot file
falls back to the trade ledger only if it reconciles to the broker quantity, else to an
UNVERIFIED entry_date fallback that cannot authorize a sale.
"""
import argparse
import json
import os
import sys

try:
    import lots as L
except ImportError:  # pragma: no cover
    from scripts import lots as L

CARRY = ("opportunity_score", "opportunity_class", "opportunity_score_date", "assessment_run_id",
         "assessment_evidence_ref", "explosive_upside_score", "remaining_upside_score",
         "signal_quality_score", "score", "score_signal_class", "score_date", "legacy",
         "entry_date", "high_since_entry", "stop_price", "material_development_since_assessment")


def _data(obj):
    return obj.get("data", obj) if isinstance(obj, dict) else obj


def _load(path, default=None):
    if not path or not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def quote_map(quotes):
    out = {}
    for r in (_data(quotes) or {}).get("results", []):
        q = r.get("quote", {})
        px = q.get("last_trade_price") or q.get("last_non_reg_trade_price")
        out[q.get("symbol")] = {
            "price": float(px) if px else None,
            "as_of": q.get("venue_last_trade_time"),
            "bid": q.get("bid_price"), "ask": q.get("ask_price"),
        }
    return out


def protection_block(positions_raw, orders_raw, exceptions, now):
    """Per-symbol: a live GTC sell stop whose quantity covers the shares held for sells."""
    stops = {}
    for o in (_data(orders_raw) or {}).get("orders", []):
        if (o.get("side") == "sell" and o.get("trigger") == "stop"
                and o.get("state") in ("confirmed", "queued", "new", "unconfirmed", "partially_filled")
                and o.get("time_in_force") == "gtc"):
            stops.setdefault(o["symbol"], []).append(o)
    exc_syms = {e["symbol"] for e in exceptions}
    required, verified, details = [], [], {}
    for p in (_data(positions_raw) or {}).get("positions", []):
        sym = p["symbol"]
        qty = float(p["quantity"])
        if sym in exc_syms:
            continue
        required.append(sym)
        covered = sum(float(o.get("quantity") or 0) for o in stops.get(sym, []))
        details[sym] = {"stop_qty": covered, "position_qty": qty,
                        "stop_prices": [o.get("stop_price") for o in stops.get(sym, [])]}
        if covered + 1e-6 >= qty:
            verified.append(sym)
    held_exc = [e for e in exceptions
                if e["symbol"] in {p["symbol"] for p in (_data(positions_raw) or {}).get("positions", [])}]
    return {"required_symbols": sorted(required), "verified_symbols": sorted(verified),
            "accepted_exceptions": held_exc, "details": details, "checked_at": now}


def build(now, portfolio, positions_raw, orders_raw, quotes, taxlots, state, trades, config, observed_at=None):
    today = L.ny_date(now)
    qm = quote_map(quotes)
    pf = _data(portfolio) or {}
    bp = pf.get("buying_power") or {}
    unlev = bp.get("unleveraged_buying_power") or bp.get("buying_power")
    reserve = float(config.get("min_cash_reserve_usd", 0.0))
    positions, problems = {}, []
    for p in (_data(positions_raw) or {}).get("positions", []):
        sym = p["symbol"]
        sp = (state.get("positions") or {}).get(sym, {})
        view = L.position_view(sym, p, taxlots.get(sym), trades, sp, now)
        pos = {k: sp[k] for k in CARRY if k in sp}
        pos.update({"qty": view["qty"], "lots": view["lots"], "sellable_qty": view["sellable_qty"],
                    "restricted_qty": view["restricted_qty"], "unknown_qty": view["unknown_qty"],
                    "lots_verified": view["lots_verified"], "same_day": view["same_day"],
                    "average_buy_price": p.get("average_buy_price")})
        if "persisted_same_day_ignored" in view:
            pos["persisted_same_day_ignored"] = view["persisted_same_day_ignored"]
        q = qm.get(sym)
        if q and q["price"] is not None:
            pos["last_price"], pos["quote_as_of"] = q["price"], q["as_of"]
            pos["value_usd"] = round(q["price"] * view["qty"], 2)
        else:
            pos["value_usd"] = None  # unknown stays unknown (fail toward review, not exemption)
            problems.append(f"no quote for {sym}")
        positions[sym] = pos
    prot = protection_block(positions_raw, orders_raw, config.get("accepted_legacy_exceptions") or [], now)
    live = {
        "now": now, "ny_date": today,
        "account_value": float(pf["total_value"]) if pf.get("total_value") else None,
        "buying_power": float(bp["buying_power"]) if bp.get("buying_power") else None,
        "deployable_buying_power": max(0.0, float(unlev) - reserve) if unlev else None,
        "account_observed_at": observed_at or now,
        "protection": prot,
    }
    return {"positions": positions, "live": live, "problems": problems, "today_ny": today}


def main():
    ap = argparse.ArgumentParser()
    for a in ("now", "portfolio", "positions", "orders", "quotes", "taxlots-dir", "state", "trades",
              "config", "out-dir"):
        ap.add_argument(f"--{a}", required=a in ("now", "portfolio", "positions", "orders", "quotes",
                                                  "state", "config", "out-dir"))
    ap.add_argument("--observed-at")
    a = ap.parse_args()
    tl = {}
    if a.taxlots_dir and os.path.isdir(a.taxlots_dir):
        for fn in os.listdir(a.taxlots_dir):
            if fn.endswith(".json"):
                tl[fn[:-5]] = (_data(_load(os.path.join(a.taxlots_dir, fn))) or {}).get("tax_lots")
    trades = []
    if a.trades and os.path.exists(a.trades):
        trades = [json.loads(l) for l in open(a.trades) if l.strip()]
    out = build(a.now, _load(a.portfolio), _load(a.positions), _load(a.orders), _load(a.quotes), tl,
                _load(a.state), trades, _load(a.config), a.observed_at)
    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(out["positions"], open(os.path.join(a.out_dir, "positions.json"), "w"), indent=2)
    json.dump(out["live"], open(os.path.join(a.out_dir, "live.json"), "w"), indent=2)
    print(json.dumps({"today_ny": out["today_ny"], "problems": out["problems"],
                      "protection": {k: out["live"]["protection"][k] for k in
                                     ("required_symbols", "verified_symbols")}}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
