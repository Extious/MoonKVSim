"""Diagnostic only: check native cached-tail support before timing recovery."""
import argparse, copy, json, os, sys, traceback
from pathlib import Path
import torch

ROOT = Path('/home/comp/zhanzhao/MoonKVSim')
sys.path.insert(0, str(ROOT/'benchmark/AegisKV/experiments/native-sparse/20260915'))
import measure_prefill as mp

p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
result=dict(model=args.model,diagnostic_only=True,job=os.environ.get('SLURM_JOB_ID'),status='loading')
try:
    torch.set_num_threads(4)
    result['gpu']=mp.gpu_snapshot()
    forward,meta,mod=mp.load_minicpm4() if args.model=='minicpm4-8b' else mp.load_nosa(args.model)
    model=next(c.cell_contents for c in forward.__closure__ if isinstance(c.cell_contents,torch.nn.Module))
    result['meta']=meta
    length,tail=8192,64
    ids=torch.randint(100,meta['vocab']-100,(1,length+tail+1),generator=torch.Generator().manual_seed(20260918)).cuda()
    with torch.inference_mode():
        history=forward(ids[:,:length]);torch.cuda.synchronize()
        c=history.past_key_values
        result['cache_class']=type(c).__name__
        result['cache_attributes']={k:type(v).__name__ for k,v in vars(c).items()}
        result['layer_attributes']={k:(list(v.shape) if isinstance(v,torch.Tensor) else type(v).__name__) for k,v in vars(c.layers[0]).items()}
        key='logits_to_keep' if args.model=='minicpm4-8b' else 'num_logits_to_keep'
        mask=torch.ones((1,length+tail),dtype=torch.long,device='cuda')
        result['status']='cached_tail'
        out=model(input_ids=ids[:,length:length+tail],attention_mask=mask,position_ids=torch.arange(length,length+tail,device='cuda')[None,:],past_key_values=copy.deepcopy(c),use_cache=True,**{key:1})
        torch.cuda.synchronize()
        result['tail_finite']=bool(torch.isfinite(out.logits).all())
        result['cache_lengths']=[out.past_key_values.get_seq_length(i) for i in range(meta['layers'])]
        result['status']='reference'
        reference=forward(ids[:,:length+tail]);torch.cuda.synchronize()
        actual,expected=out.logits.float(),reference.logits.float()
        result['full_prefill_comparison']=dict(max_abs=float((actual-expected).abs().max()),relative_l2=float((actual-expected).norm()/expected.norm()),argmax_equal=bool((actual.argmax(-1)==expected.argmax(-1)).all()))
        result['status']='complete'
except Exception as exc:
    result.update(status='failed',error=repr(exc),traceback=traceback.format_exc())
finally:
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('meta','gpu','traceback')},indent=2),flush=True)
