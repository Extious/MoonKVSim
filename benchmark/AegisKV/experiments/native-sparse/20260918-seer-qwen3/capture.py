"""Capture real SeerAttention Prefill masks on Qwen3-8B, with pinned public gates."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np
import torch
from transformers import AutoTokenizer, PreTrainedModel
from bootstrap import bootstrap, ROOT, SOURCE, PAD_SOURCE

BASE = Path('/home/comp/zhanzhao/.cache/huggingface/hub/models--Qwen--Qwen3-8B/snapshots/b968826d9c46dd6066d109eabc6255188de91218')
TEXTS = ROOT.parent/'runtime-20260914/data'
M,N,BLOCK,LAYERS = 32768,512,64,36


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2)+'\n')


def verify():
    records={}
    for tag,folder in [('base',BASE),('gate',ROOT/'gate')]:
        meta=json.loads((ROOT/f'{tag}-metadata.json').read_text())
        names=set(json.loads((folder/'model.safetensors.index.json').read_text())['weight_map'].values()) if tag=='base' else {'attn_gate_weights.pth'}
        names|={'config.json'}
        if tag=='base':names|={'tokenizer.json','tokenizer_config.json'}
        entries={x['rfilename']:x for x in meta['siblings']}
        records[tag]=dict(repository=meta['id'],revision=meta['sha'],files={})
        for name in sorted(names):
            entry=entries[name];path=folder/name
            assert path.stat().st_size==entry['size']
            digest=sha(path)
            if entry.get('lfs'):assert digest==entry['lfs']['sha256'],name
            records[tag]['files'][name]=dict(bytes=path.stat().st_size,sha256=digest)
            print('VERIFIED',tag,name,flush=True)
    assert records['base']['revision']==BASE.name
    assert records['gate']['revision']=='ce40326c0ed088757b9cae99273724deb0f0ae85'
    records['status']='verified'
    write(ROOT/'checkpoint-verification.json',records)
    return records


class Observer:
    def __init__(self,forward,model):
        self.enabled=False
        self.original=forward.block_sparse_triton_fn
        forward.block_sparse_triton_fn=self.kernel
        for layer in model.model.layers:
            layer.self_attn.register_forward_pre_hook(self.before)
            layer.self_attn.register_forward_hook(self.after)

    def start(self,folder,history,suffix):
        folder.mkdir(parents=True,exist_ok=True)
        self.folder=folder;self.history=history;self.suffix=suffix
        self.records={};self.enabled=True

    def before(self,module,args):
        if self.enabled:
            self.layer=module.layer_idx
            assert self.layer not in self.records
            self.records[self.layer]=dict(layer_zero_based=self.layer,native_kernel_calls=0)

    def kernel(self,q,k,v,block_sparse_mask,*args,**kwargs):
        if self.enabled:
            row=self.records[self.layer];row['native_kernel_calls']+=1
            mask=block_sparse_mask.detach().cpu().numpy()
            b=(self.history+self.suffix)//BLOCK
            assert mask.dtype==np.bool_ and mask.shape==(1,32,b,b),mask.shape
            assert not np.any(np.triu(mask,1)) and np.all(mask.sum(-1)>0)
            path=self.folder/f'layer-{self.layer+1:02d}.npz'
            np.savez_compressed(path,block_mask=mask[0])
            row.update(trace_format='query_head_query_block_key_block_bool',
                       native_mask_identity_verified=True,selection_shape=list(mask.shape),
                       trace_file=str(path.relative_to(ROOT)),trace_sha256=sha(path),
                       valid_block_selections=int(mask.sum()),causal_and_nonempty=True)
        # The exact captured native mask object is passed unmodified to the native kernel.
        return self.original(q,k,v,block_sparse_mask,*args,**kwargs)

    def after(self,module,args,output):
        if self.enabled:
            row=self.records[self.layer]
            row['output_finite']=bool(torch.isfinite(output[0]).all().item())
            assert row['output_finite'] and row['native_kernel_calls']==1,row
            print('LAYER',self.layer+1,'OK',flush=True)

    def finish(self):
        self.enabled=False
        assert sorted(self.records)==list(range(LAYERS))
        return [self.records[i] for i in range(LAYERS)]


def main():
    verified=verify()
    module,forward=bootstrap()
    config=module.SeerAttnQwen3Config.from_pretrained(ROOT/'gate',local_files_only=True)
    config.base_model=str(BASE)
    config._attn_implementation='sdpa'
    config.seerattn_last_block_dense=False
    assert config.seerattn_threshold==.001 and not config.use_flash_rope
    assert not config.seerattn_chunked_prefill_force_dense
    # Same base-loading operation as the publisher's adapter loader, with loading info
    # exposed so no base or gate parameter can silently remain randomly initialized.
    model,loading=PreTrainedModel.from_pretrained.__func__(module.SeerAttnQwen3ForCausalLM,
        BASE,config=config,torch_dtype=torch.bfloat16,device_map={'':'cuda:0'},
        output_loading_info=True,local_files_only=True,attn_implementation='sdpa')
    write(ROOT/'base-loading.json',loading)
    gate=torch.load(ROOT/'gate/attn_gate_weights.pth',map_location='cpu',weights_only=True)
    expected={name for name,_ in model.named_parameters() if '.attn_gate.' in name}
    assert set(gate)==expected and set(loading['missing_keys'])==expected
    assert not any(loading.get(k) for k in ['unexpected_keys','mismatched_keys','error_msgs'])
    result=model.load_state_dict(gate,strict=False)
    assert not result.unexpected_keys and not (set(result.missing_keys)&expected)
    for name,param in model.named_parameters():
        if name in gate:assert torch.equal(param.detach().cpu(),gate[name].to(param.dtype)),name
    del gate
    model.eval()
    assert len(model.model.layers)==LAYERS
    assert all(isinstance(x.self_attn,module.SeerAttnQwen3Attention) for x in model.model.layers)
    source_files={str(Path(m.__file__).relative_to(SOURCE)):sha(m.__file__)
                  for m in list(sys.modules.values()) if getattr(m,'__file__',None)
                  and Path(m.__file__).is_relative_to(SOURCE)}
    env=dict(model='SeerAttention-Qwen3-8B',checkpoint=verified,
             gate_origin='jiwonsong experimental SeerAttention Prefill adapter; not official SeerAttention-R Decode gates',
             source_repository='https://github.com/jiwonsong-dev/CompactAttention',
             source_revision=subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip(),
             source_sha256=source_files,capture_sha256=sha(__file__),bootstrap_sha256=sha(ROOT/'bootstrap.py'),
             padding_source_sha256=sha(PAD_SOURCE),slurm_job_id=os.getenv('SLURM_JOB_ID'),host=platform.node(),
             gpu=torch.cuda.get_device_name(),packages={x:importlib.metadata.version(x) for x in ['torch','transformers','triton','numpy']},
             native_layer_config=dict(block_size=64,query_block_size=64,init_blocks=0,local_blocks=0,
                                      sparsity_method='threshold',threshold=.001,last_block_dense=False),
             kv_layout=dict(layers=LAYERS,query_heads=32,kv_heads=8,head_dim=128,block_tokens=64,block_bytes_layer=262144),
             rope_scaling=config.rope_scaling,
             evidence='Real native Prefill with public base and trained gate weights; actual original block-sparse kernel inputs. No CompactAttention block-union backend.',
             config_note='Gate checkpoint threshold .001 and YaRN configuration retained. Optional last-two-query-block dense override disabled to avoid end-boundary-dependent selection. This run does not establish sparse accuracy equivalence or physical retry performance.')
    write(ROOT/'measured-environment.json',env)
    observer=Observer(forward,model)
    tokenizer=AutoTokenizer.from_pretrained(BASE,local_files_only=True)
    books=['10146','10321','10356']
    data={book:tokenizer((TEXTS/f'{book}.txt').read_text(),add_special_tokens=True)['input_ids'] for book in books}

    def run_forward(ids):
        inputs=torch.tensor([ids],device='cuda',dtype=torch.long)
        with torch.inference_mode():
            out=model(input_ids=inputs,attention_mask=None,use_cache=False,
                      output_attentions=False,num_logits_to_keep=1)
        return out.logits.detach().float().cpu()

    baseline=run_forward(data[books[0]][:1024])
    observer.start(ROOT/'validation',512,512)
    observed=run_forward(data[books[0]][:1024]);layers=observer.finish()
    delta=float((baseline-observed).abs().max())
    assert delta==0 and bool(torch.isfinite(observed).all())
    write(ROOT/'observer-validation.json',dict(status='passed',max_abs_logit_delta=delta,logits_finite=True,layers=layers))
    for book in books:
        assert len(data[book])>=M+N
        folder=ROOT/'traces'/f'pg19-{book}-M{M}-N{N}'
        observer.start(folder,M,N)
        ids=data[book][:M+N];np.save(folder/'input_ids.npy',np.array(ids,dtype=np.int64))
        run=dict(status='running',book_id=book,M=M,N=N,text_sha256=sha(TEXTS/f'{book}.txt'),input_ids_sha256=sha(folder/'input_ids.npy'))
        write(folder/'run.json',run);start=time.monotonic();torch.cuda.reset_peak_memory_stats()
        try:
            logits=run_forward(ids);layers=observer.finish()
            assert bool(torch.isfinite(logits).all())
            run.update(status='complete',layers=layers,logits_finite=True,elapsed_seconds=time.monotonic()-start,
                       peak_allocated_bytes=torch.cuda.max_memory_allocated(),greedy_next_token_id=int(logits[0,-1].argmax()))
            write(folder/'run.json',run);print('DOCUMENT_COMPLETE',book,run['elapsed_seconds'],flush=True)
        except Exception as exc:
            run.update(status='failed',error=repr(exc));write(folder/'run.json',run);raise
    print('CAPTURE_COMPLETE',flush=True)


if __name__=='__main__':main()
