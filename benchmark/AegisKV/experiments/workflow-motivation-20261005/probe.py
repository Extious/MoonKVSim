import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import torch
import transformers
from transformers import AutoModelForCausalLM, AutoTokenizer

out = Path(__file__).resolve().parent / 'runs' / f'probe-{os.environ["SLURM_JOB_ID"]}'
out.mkdir(exist_ok=True)
model_path = Path('/home/comp/zhanzhao/.cache/huggingface/hub/models--Qwen--Qwen3-4B-Instruct-2507/snapshots/cdbee75f17c01a7cc42f958dc650907174af0554')
assert torch.cuda.device_count() == 2
devices = [{'name': torch.cuda.get_device_name(i), 'bytes': torch.cuda.get_device_properties(i).total_memory} for i in range(2)]
tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True, torch_dtype=torch.bfloat16, attn_implementation='sdpa').to('cuda:0').eval()
prompt = tokenizer.apply_chat_template([{'role':'user','content':'Reply with the single word READY.'}], tokenize=True, add_generation_prompt=True, return_tensors='pt').to('cuda:0')
with torch.inference_mode():
    r = model.generate(prompt, max_new_tokens=8, do_sample=False, return_dict_in_generate=True, use_cache=True)
torch.cuda.synchronize()
assert r.past_key_values.get_seq_length() > 0
rows = [(tuple(k.shape), tuple(v.shape), k.numel()*k.element_size()+v.numel()*v.element_size()) for k,v in r.past_key_values]
result = {'status':'PASS', 'purpose':'New environment compatibility probe, not workflow evidence',
    'slurm_job_id':os.environ['SLURM_JOB_ID'],'torch':torch.__version__,'transformers':transformers.__version__,
    'devices':devices,'model_path':str(model_path),'config_sha256':hashlib.sha256((model_path/'config.json').read_bytes()).hexdigest(),
    'response':tokenizer.decode(r.sequences[0,prompt.shape[1]:],skip_special_tokens=True),
    'cache_tokens':r.past_key_values.get_seq_length(),'cache_tensor_bytes':sum(x[2] for x in rows),
    'cache_layers':len(rows)}
(out/'ENVIRONMENT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2),flush=True)
