import sys,importlib.util,json
from pathlib import Path
import torch
root=Path('/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/20260918-seer')
spec=importlib.util.spec_from_file_location('seer_original_kernel',root/'checkpoint/block_sparse_attn.py')
kernel=importlib.util.module_from_spec(spec);spec.loader.exec_module(kernel)
torch.manual_seed(42)
q=torch.randn(1,2,256,128,device='cuda',dtype=torch.bfloat16)
k=torch.randn_like(q);v=torch.randn_like(q)
mask=torch.ones((1,2,4,4),device='cuda',dtype=torch.bool).tril()
with torch.inference_mode():
 a=kernel.block_sparse_triton_fn(q,k,v,mask,128**-.5)
 b=torch.nn.functional.scaled_dot_product_attention(q,k,v,is_causal=True)
err=float((a.float()-b.float()).abs().max()); assert torch.isfinite(a).all() and err<.03,err
record=dict(status='passed',purpose='Kernel compatibility smoke test only; synthetic inputs are not Figure 3 data.',max_abs_error_vs_dense_causal=err,gpu=torch.cuda.get_device_name())
(root/'kernel-smoke.json').write_text(json.dumps(record,indent=2)+'\n');print(record)
