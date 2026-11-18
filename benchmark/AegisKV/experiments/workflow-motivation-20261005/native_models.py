"""Fresh published sparse-model forwards on three complete new review-Agent prompts.
Only model loading/observation code is reused; no previous experiment results.
"""
from pathlib import Path
import argparse, hashlib, importlib.util, json, os, sys
import numpy as np
import torch
from transformers import AutoTokenizer, LlamaConfig
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parents[1]/'experiments/native-sparse'
CAMPAIGN=BASE/'20260921-concentration-64k'
arg=argparse.ArgumentParser();arg.add_argument('--model',choices=['NOSA-8B','NSA-8B','MiniCPM4.1-8B'],required=True)
name=arg.parse_args().model
sys.path.insert(0,str(CAMPAIGN))
filename={'NOSA-8B':'capture_nosa8b.py','NSA-8B':'capture_nsa.py','MiniCPM4.1-8B':'capture_minicpm41_dual.py'}[name]
spec=importlib.util.spec_from_file_location('fresh_observer',CAMPAIGN/filename)
loader=importlib.util.module_from_spec(spec);sys.modules[spec.name]=loader;spec.loader.exec_module(loader)
OUT=ROOT/'runs'/f'native-models-{os.environ["SLURM_JOB_ID"]}'/name
OUT.mkdir(parents=True,exist_ok=False)
loader.OUT=OUT
from capture_common import device_map,gpu_snapshot
gpu=gpu_snapshot();torch.set_num_threads(8)
if name=='NOSA-8B':
    loader.CHECKPOINT=loader.ROOT/name
    cp=loader.CHECKPOINT;revision=loader.MODEL_SPECS[name]['revision']
    assert loader.digest(cp/'model.safetensors')==loader.MODEL_SPECS[name]['weight_sha256']
    code,native,kernel,padding=loader.bootstrap();code.nosa_mean_pooling=code._original_pooling
    cfg=LlamaConfig.from_pretrained(cp,local_files_only=True);cfg._attn_implementation='sdpa'
    model,loading=code.SparseLlamaForCausalLM.from_pretrained(cp,config=cfg,torch_dtype=torch.bfloat16,
        device_map=device_map(rotary=True),local_files_only=True,output_loading_info=True,attn_implementation='sdpa')
    observer=loader.Observer(code,native,model)
elif name=='NSA-8B':
    cp=loader.CHECKPOINT;revision=loader.REVISION;loader.shared.OUT=OUT
    provenance=json.loads((CAMPAIGN/'NSA-8B-checkpoint-verification.json').read_text())
    for fname,value in provenance['files'].items():assert loader.digest(cp/fname)==value['sha256']
    code,kernel=loader.bootstrap();cfg=code.LlamaConfig.from_pretrained(cp,local_files_only=True)
    model,loading=code.SparseLlamaForCausalLM.from_pretrained(cp,config=cfg,torch_dtype=torch.bfloat16,
        device_map=device_map(rotary=True),local_files_only=True,output_loading_info=True,attn_implementation='sdpa')
    observer=loader.Observer(code,model)
else:
    sys.path.insert(0,str(BASE/'20260915'))
    from prepare_minicpm41 import CHECKPOINT,REVISION,verify_checkpoint
    cp=CHECKPOINT;revision=REVISION;verify_checkpoint(cp)
    code,kernel=loader.bootstrap(cp);cfg=code.MiniCPMConfig.from_pretrained(cp,local_files_only=True)
    cfg.sparse_config=dict(loader.SPARSE_CONFIG)
    model,loading=code.MiniCPMForCausalLM.from_pretrained(cp,config=cfg,torch_dtype=torch.bfloat16,
        device_map=device_map(),local_files_only=True,output_loading_info=True,attn_implementation='flash_attention_2')
    observer=loader.Observer(code,model)
assert not any(loading.get(k) for k in ['missing_keys','unexpected_keys','mismatched_keys','error_msgs'])
model.eval();tokenizer=AutoTokenizer.from_pretrained(cp,local_files_only=True)
weights={p.name:loader.digest(p) for p in cp.glob('*.safetensors')}
rows=[]
for p in sorted((ROOT/'runs/capture-163125/calls').glob('*.json')):
    r=json.loads(p.read_text())
    if r['agent_key']!='F0/review/A':continue
    text='\n\n'.join(f"{m['role'].upper()}:\n{m['content']}" for m in r['messages'])
    ids=tokenizer(text,add_special_tokens=True)['input_ids']
    assert 8192<len(ids)<min(cfg.max_position_embeddings,32768),len(ids)
    run=OUT/f"call-{r['id']:04}";run.mkdir()
    (run/'request-text.txt').write_text(text);np.save(run/'input_ids.npy',np.asarray(ids,dtype=np.int32))
    x=torch.tensor([ids],device='cuda:0')
    def forward():
        with torch.inference_mode():
            if name=='MiniCPM4.1-8B':
                cache=code.InfLLMv2Cache(config=model.config,num_hidden_layers=32)
                result=model(input_ids=x,attention_mask=torch.ones_like(x),past_key_values=cache,
                    use_cache=True,output_attentions=False,logits_to_keep=1)
            else:
                result=model(input_ids=x,attention_mask=torch.ones_like(x),use_cache=False,
                    output_attentions=False,num_logits_to_keep=1)
            logits=result.logits.detach().float().cpu()
        return logits
    baseline=forward();observer.start(run,len(ids)-512,512);observed=forward();layers=observer.finish()
    difference=float((baseline-observed).abs().max());assert difference==0 and torch.isfinite(observed).all()
    row=dict(model=name,revision=revision,source_call_id=r['id'],workflow_id=r['workflow_id'],
        agent_key=r['agent_key'],round_index=r['round_index'],input_tokens=len(ids),history_tokens=len(ids)-512,
        query_suffix_tokens=512,observer_max_abs_logit_difference=difference,layers=layers,
        source_call_sha256=loader.digest(p),text_sha256=hashlib.sha256(text.encode()).hexdigest())
    (run/'RUN.json').write_text(json.dumps(row,indent=2)+'\n');rows.append(row)
    print('NEW_NATIVE_COMPLETE',name,r['id'],len(ids),difference,flush=True)
(OUT/'SUMMARY.json').write_text(json.dumps(dict(status='PHYSICAL_NATIVE_DEMAND_COMPLETE',model=name,
    requests=rows,gpu=gpu,weight_sha256=weights,loader_sha256=loader.digest(CAMPAIGN/filename),
    kernel_binary_sha256=loader.digest(kernel.C.__file__),
    boundary='Actual native selection on three complete newly captured review-A histories; last 512 queries; no context extension, synthetic text padding, serving speedup or application-quality claim; two-GPU layer placement, not TP.'),indent=2)+'\n')
