"""New native NOSA demand observation on exact newly captured request text.

Reuse only the validated model loader/observer code. No old result/trace files
are read. Published pooling/config remain unchanged; contexts stay below 32K.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys

import numpy as np
import torch
from transformers import AutoTokenizer, LlamaConfig

ROOT=Path(__file__).resolve().parent
AEGIS=ROOT.parents[1]
SOURCE=AEGIS/'experiments/native-sparse/20260921-concentration-64k/capture_nosa8b.py'
spec=importlib.util.spec_from_file_location('new_workflow_nosa_observer',SOURCE)
mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
OUT=ROOT/'runs'/f'native-{os.environ["SLURM_JOB_ID"]}';OUT.mkdir(exist_ok=True)
mod.CHECKPOINT=mod.ROOT/'NOSA-8B';mod.REVISION=mod.MODEL_SPECS['NOSA-8B']['revision'];mod.OUT=OUT
weights=mod.CHECKPOINT/'model.safetensors'
assert weights.stat().st_size==mod.MODEL_SPECS['NOSA-8B']['weight_bytes']
assert mod.digest(weights)==mod.MODEL_SPECS['NOSA-8B']['weight_sha256']
gpu=mod.gpu_snapshot()
torch.set_num_threads(8)
modelcode,native,kernel,padding=mod.bootstrap()
modelcode.nosa_mean_pooling=modelcode._original_pooling
config=LlamaConfig.from_pretrained(mod.CHECKPOINT,local_files_only=True);config._attn_implementation='sdpa'
model,loading=modelcode.SparseLlamaForCausalLM.from_pretrained(mod.CHECKPOINT,config=config,
    torch_dtype=torch.bfloat16,device_map=mod.device_map(rotary=True),local_files_only=True,
    output_loading_info=True,attn_implementation='sdpa')
assert not any(loading.get(k) for k in ['missing_keys','unexpected_keys','mismatched_keys','error_msgs'])
model.eval()
tokenizer=AutoTokenizer.from_pretrained(mod.CHECKPOINT,local_files_only=True)
observer=mod.Observer(modelcode,native,model)
calls=[]
for p in (ROOT/'runs/capture-163125/calls').glob('*.json'):
    r=json.loads(p.read_text())
    if r['run_id']=='F0':calls.append(r)
selected=[]
for app,letter in [('research','A'),('review','A'),('review','B')]:
    selected.append(max((r for r in calls if r['agent_key']==f'F0/{app}/{letter}'),key=lambda r:r['input_tokens']))
results=[]
for r in selected:
    # Re-tokenize the full original text with this model's own tokenizer.
    # No artificial repetition, padding, or exchange of cross-model token IDs.
    text='\n\n'.join(f"{m['role'].upper()}:\n{m['content']}" for m in r['messages'])
    ids=tokenizer(text,add_special_tokens=True)['input_ids']
    assert 256<len(ids)<32768,len(ids)
    run=OUT/f"call-{r['id']:04}";run.mkdir(exist_ok=True)
    (run/'request-text.txt').write_text(text)
    np.save(run/'input_ids.npy',np.array(ids,dtype=np.int32))
    x=torch.tensor([ids],device='cuda:0')
    def forward():
        with torch.inference_mode():
            result=model(input_ids=x,attention_mask=torch.ones_like(x),use_cache=False,
                         output_attentions=False,num_logits_to_keep=1)
        return result.logits.detach().float().cpu()
    baseline=forward()
    observer.start(run,len(ids)-128,128)
    traced=forward();layers=observer.finish()
    difference=float((baseline-traced).abs().max())
    assert difference==0 and torch.isfinite(traced).all()
    info={'source_call_id':r['id'],'workflow_id':r['workflow_id'],'agent_key':r['agent_key'],
        'model':'openbmb/NOSA-8B','revision':mod.REVISION,'input_tokens':len(ids),
        'history_tokens':len(ids)-128,'query_suffix_tokens':128,'query_window':[len(ids)-128,len(ids)],
        'observer_max_abs_logit_difference':difference,'layers':layers,
        'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'scope':'Physical native full-prefill selection events on complete text of newly captured prompts; re-tokenized for NOSA. No NOSA application-output quality claim or measured HBM-placement speedup.'}
    (run/'RUN.json').write_text(json.dumps(info,indent=2)+'\n');results.append(info)
    print('NEW_NATIVE_COMPLETE',r['id'],len(ids),difference,flush=True)
(OUT/'SUMMARY.json').write_text(json.dumps({'status':'PHYSICAL_NATIVE_DEMAND_COMPLETE','requests':results,
    'gpu':gpu,'weights_sha256':mod.digest(weights),'code_sha256':mod.digest(SOURCE),
    'pooling':'Published original 32K pooling; no capacity extension',
    'boundary':'Native selection measurement; no transfer/stall timing or end-to-end sparse serving measured.'},indent=2)+'\n')
