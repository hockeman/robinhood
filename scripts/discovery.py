#!/usr/bin/env python3
"""
Discovery evidence ledger, catalyst-first intake, materiality, ranking and budget.
No network access: it validates and orders evidence the agent gathered with tools.

A discovery source entry (one per scanner / catalyst source per run):
  {
    "source_id": "Agentic Nuclear Volume v2",
    "kind": "scanner" | "earnings_lookback" | "news_search" | "filings_watch" | ...,
    "params": {...},                      # scan id / query / window actually used
    "status": "success" | "successful_empty" | "failed" | "not_run" | "stale",
    "requested_at": ISO, "observed_at": ISO, "data_as_of": ISO | null,
    "returned_count": int, "result_ref": "runs/<run>/<file>.json", "result_sha256": hex,
    "coverage_note": "e.g. scanner returns top-N only / per-symbol only / not market-wide",
    "error": str | null
  }
A boolean "scan complete" is never accepted. successful_empty requires a result_ref
(the raw empty response was saved) so absence of data cannot masquerade as an empty scan.
"""
import datetime as dt
import hashlib
import json

STATUSES = {"success", "successful_empty", "failed", "not_run", "stale"}


def _ts(v):
    if not v:
        return None
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def sha256_of(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def validate_source(entry, now, max_age_minutes, max_data_age_minutes=None):
    """Return (effective_status, problems). effective_status never defaults to success."""
    problems = []
    status = entry.get("status")
    if status not in STATUSES:
        return "invalid", [f"status {status!r} not one of {sorted(STATUSES)}"]
    if status in ("failed", "not_run", "stale"):
        return status, ([entry.get("error")] if entry.get("error") else [])
    now = _ts(now)
    observed = _ts(entry.get("observed_at"))
    requested = _ts(entry.get("requested_at"))
    if requested is None or observed is None:
        problems.append("missing requested_at/observed_at")
    count = entry.get("returned_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        problems.append("returned_count missing or not a non-negative integer")
    if not entry.get("result_ref") or not entry.get("result_sha256"):
        problems.append("missing result_ref/result_sha256 (no saved result to inspect)")
    if status == "successful_empty" and isinstance(count, int) and count != 0:
        problems.append("successful_empty but returned_count != 0")
    if status == "success" and count == 0:
        problems.append("success with returned_count == 0 (must be successful_empty)")
    if not entry.get("coverage_note"):
        problems.append("missing coverage_note (state what the source does not cover)")
    if problems:
        return "invalid", problems
    if now and (now - observed).total_seconds() > max_age_minutes * 60:
        return "stale", [f"observed_at older than {max_age_minutes} min"]
    if requested > observed:
        return "invalid", ["requested_at after observed_at"]
    data_as_of = _ts(entry.get("data_as_of"))
    if max_data_age_minutes is not None and data_as_of and now and \
            (now - data_as_of).total_seconds() > max_data_age_minutes * 60:
        return "stale", [f"data_as_of older than {max_data_age_minutes} min"]
    return status, []


def required_sources(config, session):
    d = config.get("discovery", {})
    return list((d.get("required_by_session", {}) or {}).get(session, []))


def validate_ledger(ledger, config, now, session):
    """
    ledger: {"run_id": str, "sources": [entry, ...]} or None.
    Returns {"complete": bool, "per_source": {...}, "missing": [...], "failed": [...],
             "stale": [...], "invalid": [...], "degraded": bool}
    Missing ledger / missing required source => incomplete. Healthy sources stay usable.
    """
    d = config.get("discovery", {})
    max_age = d.get("max_source_age_minutes", 45)
    max_data_age = d.get("max_data_age_minutes", None)
    need = required_sources(config, session)
    by_id = {}
    for e in (ledger or {}).get("sources", []) or []:
        by_id[e.get("source_id")] = e
    per, missing, failed, stale, invalid = {}, [], [], [], []
    for sid in need:
        e = by_id.get(sid)
        if e is None:
            per[sid] = {"status": "missing", "problems": ["no ledger entry"]}
            missing.append(sid)
            continue
        status, problems = validate_source(e, now, max_age, max_data_age)
        per[sid] = {"status": status, "problems": problems, "returned_count": e.get("returned_count")}
        if status in ("failed", "not_run"):
            failed.append(sid)
        elif status == "stale":
            stale.append(sid)
        elif status == "invalid":
            invalid.append(sid)
    bad = missing + failed + stale + invalid
    healthy = [s for s in need if s not in bad]
    return {
        "complete": bool(need) is False or not bad,
        "required": need,
        "per_source": per,
        "missing": missing, "failed": failed, "stale": stale, "invalid": invalid,
        "healthy_sources": healthy,
        "degraded": bool(bad),
        "no_requirements_for_session": not need,
    }


# ---- catalyst-first intake -------------------------------------------------

def catalyst_window(last_success_ts, now, overlap_hours=6.0, max_hours=72.0):
    """Start of the look-back window: last successful check minus overlap, capped."""
    now_t = _ts(now)
    floor = now_t - dt.timedelta(hours=max_hours)
    last = _ts(last_success_ts)
    start = (last - dt.timedelta(hours=overlap_hours)) if last else floor
    return max(start, floor).isoformat()


def event_key(ev):
    """Stable dedupe key: prefer filing id / url; else symbol+type+headline hash."""
    for k in ("filing_id", "url", "event_id"):
        if ev.get(k):
            return f"{k}:{ev[k]}"
    basis = f"{ev.get('symbol')}|{ev.get('event_type')}|{(ev.get('headline') or '').strip().lower()}"
    return "h:" + hashlib.sha256(basis.encode()).hexdigest()[:20]


def dedupe_events(events, seen, now, ttl_hours=96.0):
    """Return (new_events, updated_seen). seen: {key: first_seen_iso}. Expired keys drop."""
    now_t = _ts(now)
    live = {k: v for k, v in (seen or {}).items()
            if (now_t - _ts(v)).total_seconds() <= ttl_hours * 3600}
    fresh = []
    for ev in events:
        k = event_key(ev)
        if k in live:
            continue
        live[k] = now_t.isoformat()
        fresh.append({**ev, "event_key": k})
    return fresh, live


TIER_WEIGHT = {"S": 3.0, "A": 2.0, "B": 1.0}
PRIMARY_TYPES = {"8-K", "6-K", "13D", "13D/A", "Form 4", "FDA", "IR_PRESS_RELEASE", "COURT", "EXCHANGE"}


def enters_research(item):
    """
    A credible catalyst enters research WITHOUT needing a price or volume move.
    Requires a concrete reference (filing/url) and a catalyst type; scanner-only
    heat also qualifies (volume-led discovery) but is ranked below catalysts.
    """
    if item.get("catalyst_ref") and item.get("catalyst_type"):
        return True
    return bool(item.get("scanner_hit"))


def priority(item):
    """
    Strategy-based ranking. Deliberately ignores scanner display order and nominal
    share price. Higher is researched first.
    """
    score = 0.0
    if item.get("catalyst_ref"):
        score += 4.0
        score += TIER_WEIGHT.get(item.get("catalyst_tier"), 0.5)
        if item.get("catalyst_type") in PRIMARY_TYPES:
            score += 1.5
    rel = item.get("catalyst_value_to_market_cap")  # optional; unknown stays unknown
    if isinstance(rel, (int, float)):
        score += min(3.0, rel * 6.0)
    rvol = item.get("rvol")
    if isinstance(rvol, (int, float)):
        score += min(2.0, rvol / 5.0)
    if item.get("held"):
        score += 1.0
    if item.get("materially_changed"):
        score += 1.0
    return round(score, 3)


def material_change(prev, cur, cfg=None):
    """
    prev/cur: {"price","rvol","filing_ids":[...],"news_keys":[...]}.
    True when price, volume or evidence changed enough that a cached rejection is void.
    Missing prior snapshot => materially changed (never reuse a note with no basis).
    """
    cfg = cfg or {}
    if not prev:
        return True, ["no prior snapshot"]
    reasons = []
    p0, p1 = prev.get("price"), cur.get("price")
    if p0 and p1 and abs(p1 / p0 - 1) * 100 >= cfg.get("material_price_move_pct", 5.0):
        reasons.append(f"price {p0}->{p1}")
    r0, r1 = prev.get("rvol"), cur.get("rvol")
    if r0 is not None and r1 is not None and r1 - r0 >= cfg.get("material_rvol_increase", 1.0):
        reasons.append(f"rvol {r0}->{r1}")
    if set(cur.get("filing_ids") or []) - set(prev.get("filing_ids") or []):
        reasons.append("new filing")
    if set(cur.get("news_keys") or []) - set(prev.get("news_keys") or []):
        reasons.append("new news item")
    return bool(reasons), reasons


def cached_rejection_usable(prev_record, cur_snapshot, cfg=None):
    """A prior rejection may be carried forward only if nothing material changed."""
    changed, reasons = material_change((prev_record or {}).get("snapshot"), cur_snapshot, cfg)
    return (not changed), reasons


def plan_research(queue, max_deep_reviews):
    """
    queue: items already filtered by enters_research. Returns selected + deferred.
    Deferred items are NOT rejected; they carry an explicit budget_deferred state.
    """
    ranked = sorted(queue, key=lambda i: (-priority(i), str(i.get("symbol"))))
    selected = ranked[:max_deep_reviews]
    deferred = [
        {**i, "research_state": "deferred_budget", "priority": priority(i)}
        for i in ranked[max_deep_reviews:]
    ]
    return {"selected": selected, "deferred": deferred,
            "budget": max_deep_reviews, "queued": len(ranked)}


CANDIDATE_REQUIRED = [
    "symbol", "discovery_source", "first_observed_at", "quote_as_of",
    "catalyst_status",            # verified | unverified | none_found_after_search
    "catalyst_refs", "facts", "inferences", "unknowns",
    "dilution_check", "adverse_info_check",
    "score_inputs", "score_output",
    "remaining_upside_case", "strongest_counterargument", "invalidation_conditions",
    "decision",                  # qualify_standard | qualify_tactical | qualify_best_available | reject | defer
    "decision_reasons", "reconsider_trigger", "reconsider_expiry",
]
CATALYST_STATUS = {"verified", "unverified", "none_found_after_search"}


def validate_candidate_record(rec):
    """Return list of problems; empty means the record is auditable."""
    problems = [f"missing {k}" for k in CANDIDATE_REQUIRED if rec.get(k) in (None, "", [], {})
                and k not in ("unknowns",)]
    if "unknowns" not in rec:
        problems.append("missing unknowns")
    cs = rec.get("catalyst_status")
    if cs is not None and cs not in CATALYST_STATUS:
        problems.append(f"catalyst_status {cs!r} invalid")
    if rec.get("decision") == "reject" and cs == "unverified" and \
            "not_verified" not in " ".join(map(str, rec.get("decision_reasons") or [])):
        problems.append("rejection on an unverified catalyst must say 'not_verified' not 'no catalyst'")
    if str(rec.get("decision", "")).startswith("qualify") and cs != "verified" \
            and rec.get("decision") != "qualify_best_available":
        problems.append("qualifying decision requires catalyst_status=verified (except best_available momentum)")
    return problems
