import importlib.metadata as md
import hashlib,inspect,json,os,sys,time,traceback
from pathlib import Path
r=Path('/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919')
m=Path('/home/bingxing2/home/scx8q31/models/Qwen2.5-7B-Instruct-1M')
record={'time':time.time(),'python':sys.executable,'checks':{}}
try:
 import torch
 import sglang
 from transformers import AutoConfig,AutoTokenizer
 record['packages']={n:md.version(n) for n in ['torch','sglang','sglang-kernel','transformers','flashinfer-python','torch-memory-saver']}
 cfg=AutoConfig.from_pretrained(m,local_files_only=True)
 tok=AutoTokenizer.from_pretrained(m,local_files_only=True)
 assert cfg.max_position_embeddings==1010000 and cfg.num_hidden_layers==28
 assert len(tok.encode('An agent restores known KV history.'))>0
 record['checks']['model_metadata']=True
 from sglang.srt.server_args import ServerArgs
 from sglang.srt.model_executor.forward_batch_info import ForwardBatch
 from sglang.bench_one_batch import load_model
 from sglang.srt.layers.attention.dual_chunk_flashattention_backend import DualChunkFlashAttentionBackend
 from sglang.srt.entrypoints.engine import _set_envs_and_config
 record['checks']['runtime_imports']=True
 record['load_model_signature']=str(inspect.signature(load_model))
 record['forward_batch_signature']=str(inspect.signature(ForwardBatch))
 record['passed']=True
except Exception:
 record['passed']=False;record['error']=traceback.format_exc()
(r/'setup/cpu-check.json').write_text(json.dumps(record,indent=2))
print(json.dumps(record,indent=2),flush=True)
sys.exit(0 if record['passed'] else 1)
