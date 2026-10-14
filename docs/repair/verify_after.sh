#!/usr/bin/env bash
# Same inputs as repro_baseline.sh, run against the REPAIRED code in the working tree.
set -u
cd "$(git rev-parse --show-toplevel)"; export PYTHONDONTWRITEBYTECODE=1
python3 - <<'PY'
import sys,json,subprocess;sys.path.insert(0,'scripts')
import scoring as sc
cfg=json.load(open('config.json'))
base=subprocess.run(['git','show','052ab4193c42434a3479f1aac07947a47369be5b:state.json'],capture_output=True,text=True).stdout
pos=json.loads(base)['positions']
print("== R1 (1.8% cash, no discovery evidence, protection omitted)")
live={"account_value":6910.98,"deployable_buying_power":125.29,"market_session":"regular_hours","session_allows_entries":True,"now":"2026-10-14T17:15:00Z"}
r=sc.fast_check({},live,'2026-10-14',cfg); print('actionable',r['actionable']); [print('  ',x[:150]) for x in r['reasons']]
print("== R2/R3 real state positions (no broker lots supplied => entry_date fallback = UNVERIFIED)")
print('replaceable:',[(x['symbol'],x['effective_opportunity_score'],'assessment='+x['assessment_status'],'lots_verified='+str(x['lots_verified'])) for x in sc.replaceable_holdings(pos,'2026-10-14',config=cfg)])
v=sc.rotation_eligible(6.5,pos,'2026-10-14',0.5,5.0,config=cfg); print('rotation 6.5 ->',v['status'],'eligible',v['eligible'],'executable',v['executable'],'weakest',v['weakest_symbol'])
print('needing reassessment:',sc.positions_needing_reassessment(pos,'2026-10-14',cfg))
print("== R5 boolean completion claim, no evidence")
live5={"account_value":6910.98,"deployable_buying_power":300,"market_session":"regular_hours","session_allows_entries":True,"now":"2026-10-14T17:15:00Z","idle_cash_escalation_completed":True,"independent_catalyst_sweep_complete":True,"independent_catalyst_symbols_reviewed":["AAA","BBB"],"known_candidates":{k:{"current_run_deep_reviewed":True,"opportunity_score":1.0} for k in "VWXYZ"}}
r=sc.fast_check(pos,live5,'2026-10-14',cfg); print('actionable',r['actionable']); [print('  ',x[:130]) for x in r['reasons']]
PY
