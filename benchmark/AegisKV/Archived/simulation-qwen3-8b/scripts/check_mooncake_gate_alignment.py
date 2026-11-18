#!/usr/bin/env python3
"""Exercise the reference's pure ordinal-finalization method without CUDA/RPC."""
import argparse,ast,hashlib,json
from pathlib import Path
from types import SimpleNamespace
from moonkvsim.aegiskv.experiment import _StudyRuntime,_ExecutionStatus,DEFAULT_PARAMETERS,core_variants
from dataclasses import replace

def main():
 p=argparse.ArgumentParser();p.add_argument('--mooncake-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 path=args.mooncake_root/'benchmarks/aegiskv/src/aegiskv/vllm/gate.py'
 tree=ast.parse(path.read_text());node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_finish_logical_chunk')
 # Extract the exact pure finalizer. Only event logging and ID formatting are
 # stubs; every reference ordinal/seal/committed-key mutation executes intact.
 module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
 ns={};exec(compile(ast.fix_missing_locations(module),str(path),'exec'),ns)
 v=core_variants(replace(DEFAULT_PARAMETERS,runtime_semantics='mooncake_prompt_v1'))[-1]
 cases=[]
 sequences=[[(False,False)],[(True,False)],[(False,True)],[(True,True)],
            [(False,False),(True,True)],[(False,False),(False,False),(False,True)]]
 for seq in sequences:
  native=SimpleNamespace(hbm_sealed=False,sealed=False,committed_keys=set(),next_ordinal=0,logical_tokens=0)
  emitted=[];receiver=SimpleNamespace(_emit=lambda **kw:emitted.append(kw),_chunk_id=lambda *a:'d')
  sim=object.__new__(_StudyRuntime);sim.parameters=v.parameters;sim.profile=v.profile
  sim.executions={'r':SimpleNamespace(route_version=0,status=_ExecutionStatus.RUNNING)}
  sim._runtime_gate_frontier={};sim._runtime_gate_outcomes={};sim._formal_blocked_request_paths=set();sim._formal_active_request_paths=set()
  sim.des=SimpleNamespace(now_ns=0);sim.formal_policy_events=[]
  def finish(span,path,*,block=False,**kw):
   if block:sim._formal_blocked_request_paths.add((span,path))
  sim._formal_finish_request_path=finish
  for h,d in seq:
   ns['_finish_logical_chunk'](receiver,state=native,context=SimpleNamespace(request_id='r',route_version=0),keys=['k'],ordinal=native.next_ordinal,logical_tokens=4096,
      hbm_result=SimpleNamespace(committed=h,status='committed' if h else 'bypassed',chunk_id='h'),dram_status='committed' if d else 'bypassed',dram_committed=d)
   ordinal=sim._runtime_gate_frontier.get(('r',0),0)
   sim._runtime_gate_resolve('r',(0,'PEER_HBM',ordinal,'h'),committed=h)
   sim._runtime_gate_resolve('r',(0,'STORE_DRAM',ordinal,'d'),committed=d)
   observed=(sim._runtime_gate_frontier.get(('r',0),0),('r','PEER_HBM') in sim._formal_blocked_request_paths,('r','STORE_DRAM') in sim._formal_blocked_request_paths)
   assert observed==(native.next_ordinal,native.hbm_sealed,native.sealed)
  cases.append({'attempts':seq,'ordinal':native.next_ordinal,'hbm_sealed':native.hbm_sealed,'dram_sealed':native.sealed})
 doc={'status':'PASS','reference_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'scope':'exact reference pure finalizer; logging and storage ID formatting stubbed; not physical transfer conformance','case_count':len(cases),'cases':cases}
 args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(doc,indent=2)+'\n');print('PASS',len(cases),'reference connector sequences')
if __name__=='__main__':main()
