"""Brief allocated-GPU check before loading weights; no timing data for Figure 2."""
import json,sys,time
from pathlib import Path
import torch
from flashinfer.activation import silu_and_mul
from flashinfer.norm import rmsnorm
from sgl_kernel.flash_attn import flash_attn_varlen_func,flash_attn_with_kvcache
out=Path(sys.argv[1]);torch.cuda.set_device(0);torch.manual_seed(17)
def rand(*s):return torch.randn(*s,device='cuda',dtype=torch.bfloat16)
with torch.inference_mode():
 q=rand(64,14,128);k=rand(512,2,128);v=rand(512,2,128)
 qi=torch.tensor([0,64],dtype=torch.int32,device='cuda');ki=torch.tensor([0,512],dtype=torch.int32,device='cuda')
 a=flash_attn_varlen_func(q,k,v,qi,ki,max_seqlen_q=64,max_seqlen_k=512,causal=True)
 if isinstance(a,tuple):a=a[0]
 kr=k.repeat_interleave(7,dim=1).transpose(0,1).float();vr=v.repeat_interleave(7,dim=1).transpose(0,1).float()
 scores=q.transpose(0,1).float()@kr.transpose(-1,-2)/(128**.5)
 mask=torch.arange(512,device='cuda')[None,:]>(448+torch.arange(64,device='cuda'))[:,None]
 reference=(scores.masked_fill(mask,-torch.inf).softmax(-1)@vr).transpose(0,1)
 assert torch.allclose(a.float(),reference,rtol=.05,atol=.01)
 pages=torch.arange(32,device='cuda',dtype=torch.int32)[None,:]
 dec=flash_attn_with_kvcache(q[-1:][None],k.view(32,16,2,128),v.view(32,16,2,128),cache_seqlens=torch.tensor([512],device='cuda',dtype=torch.int32),page_table=pages,causal=True)
 if isinstance(dec,tuple):dec=dec[0]
 assert torch.allclose(dec[0,0].float(),reference[-1],rtol=.05,atol=.01)
 x=rand(64,18944);actual=silu_and_mul(x);expected=torch.nn.functional.silu(x[:,:9472].float())*x[:,9472:].float()
 assert torch.allclose(actual.float(),expected,rtol=.02,atol=.02)
 x=rand(64,3584);w=torch.ones(3584,device='cuda',dtype=torch.bfloat16);actual=rmsnorm(x,w,1e-6)
 expected=x.float()*torch.rsqrt(x.float().square().mean(-1,keepdim=True)+1e-6)
 assert torch.allclose(actual.float(),expected,rtol=.02,atol=.02)
 torch.cuda.synchronize()
(out/'gpu-kernel-check.json').write_text(json.dumps({'passed':True,'time':time.time(),'checks':['BF16 GQA varlen 64/512','paged decode page16','FlashInfer fused SiLU','FlashInfer RMSNorm'],'reference':'float32 PyTorch arithmetic; attention rtol .05 atol .01; elementwise rtol/atol .02'},indent=2))
print('GPU_KERNEL_CHECK_PASSED',flush=True)
