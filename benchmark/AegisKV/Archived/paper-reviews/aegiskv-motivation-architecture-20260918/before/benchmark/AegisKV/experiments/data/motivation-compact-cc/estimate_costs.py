"""Query exact compact-example prefixes with the unchanged Figure 2 cost model.

CPU-only AIConfigurator static estimates; no GPU experiment. The Figure 2
matrix, script and output assets remain unchanged.
"""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'reuse-aiconfigurator-a100'
SOURCE=BASE/'estimate_reuse.py'
spec=importlib.util.spec_from_file_location('reuse_cost',SOURCE)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
sha=module.sha


def main():
    reference=json.loads((BASE/'estimates.json').read_text())
    for p,h in reference['source_sha256'].items():assert sha(p)==h,p
    rows=list(csv.DictReader((HERE/'compact-example-failure-position.csv').open()))
    costs=[]
    for r in rows:
        e=module.estimate('Qwen3-14B',int(r['prefix_tokens']),0)
        assert e['warning'] is None
        costs.append(dict(branch_index=int(r['branch_index']),prefix_tokens=int(r['prefix_tokens']),
                          recompute_s=e['latency_ms']/1000,details=e))
    out=dict(evidence='static estimate; not physical measurement',model='Qwen3-14B',
             tool=reference['tool'],tail_tokens=64,workflow_costs=costs,
             source_sha256={str(p):sha(p) for p in [Path(__file__),SOURCE,BASE/'estimates.json',
                            HERE/'SELECTION.json',HERE/'compact-example-failure-position.csv']})
    (HERE/'recovery-costs.json').write_text(json.dumps(out,indent=2,default=float)+'\n')
    for r,c in zip(rows,costs):
        print(f"A{int(r['branch_index'])+1}: T={c['recompute_s']:.3f} s, "
              f"Slack={float(r['slack_s']):.3f} s, loss={max(0,c['recompute_s']-float(r['slack_s'])):.3f} s")


if __name__=='__main__':main()
