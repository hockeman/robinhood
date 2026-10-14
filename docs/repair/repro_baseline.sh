#!/usr/bin/env bash
# Reproduce the audited defects against the UNMODIFIED baseline code (commit 052ab41).
# Usage: bash docs/repair/repro_baseline.sh   (run from a checkout that contains commit 052ab41)
set -u
BASE=${BASE:-052ab4193c42434a3479f1aac07947a47369be5b}
T=$(mktemp -d); mkdir -p "$T/base/scripts"
git show $BASE:scripts/scoring.py > "$T/base/scripts/scoring.py"
git show $BASE:config.json > "$T/config.json"
git show $BASE:state.json  > "$T/state.json"
cd "$T"; export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import json
s=json.load(open('state.json')); json.dump(s['positions'],open('positions_state.json','w'))
json.dump({"account_value":6910.98,"deployable_buying_power":125.29,"market_session":"regular_hours","session_allows_entries":True},open('live_r1.json','w'))
json.dump({"account_value":6910.98,"deployable_buying_power":300,"market_session":"regular_hours","session_allows_entries":True,
 "idle_cash_escalation_completed":True,"independent_catalyst_sweep_complete":True,"independent_catalyst_symbols_reviewed":["AAA","BBB"],
 "known_candidates":{k:{"current_run_deep_reviewed":True,"opportunity_score":1.0} for k in "VWXYZ"}},open('live_r5.json','w'))
PY
echo "== R1: ~1.8% cash, no scanner/discovery evidence, protection flag omitted -> baseline says nothing is needed"
python3 base/scripts/scoring.py fast-check --positions positions_state.json --live live_r1.json --config config.json --as-of 2026-10-14 | python3 -c "import sys,json;d=json.load(sys.stdin);print('actionable',d['actionable'],d['reasons'])"
echo "== R2/R3: replaceable ranking and v2-missing on the REAL state positions"
python3 - <<'PY'
import sys,json;sys.path.insert(0,'base/scripts');import scoring as sc
p=json.load(open('positions_state.json'))
print('replaceable:',[(r['symbol'],r['effective_opportunity_score']) for r in sc.replaceable_holdings(p,'2026-10-14')])
print('excluded because persisted same_day=true:',[k for k,v in p.items() if v.get('same_day')])
print('rotation 6.5 ->',sc.rotation_eligible(6.5,p,'2026-10-14',0.5,5.0)['reason'])
print('positions_missing_v2:',sc.positions_missing_v2(p),'| positions with no value_usd:',[k for k,v in p.items() if v.get('value_usd') is None])
for k,v in p.items(): print(' ',k,'score',v.get('opportunity_score'),v.get('opportunity_score_date'),'-> effective',sc.effective_opportunity_score(v,'2026-10-14'))
PY
echo "== R5: boolean completion claims with no evidence"
python3 base/scripts/scoring.py fast-check --positions positions_state.json --live live_r5.json --config config.json --as-of 2026-10-14 | python3 -c "import sys,json;d=json.load(sys.stdin);print('actionable',d['actionable'],'| completed',d['idle_cash']['idle_cash_escalation_completed'],'| reasons',d['reasons'])"
