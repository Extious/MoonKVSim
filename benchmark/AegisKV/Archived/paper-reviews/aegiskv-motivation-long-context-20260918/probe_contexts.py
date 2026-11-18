"""Probe longer shapes using frozen Figure 2 configurations; do not mutate the paper matrix."""
from pathlib import Path
import importlib.util,json,hashlib,csv
from datetime import datetime,timezone

ROOT=Path('/home/comp/zhanzhao/MoonKVSim')
OUT=Path(__file__).resolve().parent
SOURCE=ROOT/'benchmark/AegisKV/experiments/data/reuse-aiconfigurator-architecture-h100/estimate_reuse.py'
spec=importlib.util.spec_from_file_location('fixed_recovery',SOURCE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
reference=json.loads((SOURCE.parent/'estimates.json').read_text())
for p,h in reference['source_sha256'].items():assert m.sha(p)==h,p
rows=[]
for name,model in reference['models'].items():
 for history in [262144,524288,1048576]:
  bpt=model['layout']['bytes_per_token_per_rank'];state=bpt*history
  estimates={}; errors={}
  for path,prefix in [('hbm',history),('recompute',0)]:
   try: estimates[path]=m.estimate(name,history,prefix)
   except Exception as error:errors[path]=f'{type(error).__name__}: {error}'
  status={path:('query_error' if path in errors else 'capacity_warning' if estimates[path]['warning'] else 'fits_static_memory_model') for path in ('hbm','recompute')}
  status['dram']=status['hbm']
  row=dict(model=name,history_tokens=history,tail_tokens=64,tp=model['tp'],ep=model['ep'],
    config_context_limit=model['config']['max_position_embeddings'],
    exceeds_config_context=history+64>model['config']['max_position_embeddings'],
    historical_state_gib_per_rank=state/2**30,h2d_ms=state/64e9*1000,
    bandwidth='64 GB/s per rank assumed; no shared host bottleneck',path_status=status,
    raw_estimates=estimates,errors=errors)
  rows.append(row)
  print(name,history,'stateGiB',round(state/2**30,3),'HBMtotal',round(estimates.get('hbm',{}).get('memory',{}).get('total',float('nan')),3),
    'Recomputetotal',round(estimates.get('recompute',{}).get('memory',{}).get('total',float('nan')),3),'status',status,flush=True)
  (OUT/'probe-results.json').write_text(json.dumps(dict(evidence='CPU-only static model probes; no hardware execution',created_at=datetime.now(timezone.utc).isoformat(),
     reference=str(SOURCE.parent/'estimates.json'),reference_sha256=m.sha(SOURCE.parent/'estimates.json'),script_sha256=m.sha(__file__),
     no_paper_changes=True,rows=rows),indent=2)+'\n')
