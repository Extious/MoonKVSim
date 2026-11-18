"""Opt-in grouped-head DCA adapter with bounded numerical regression checks."""
import hashlib
import json
import math
from pathlib import Path
import time

from sg_backend import SGLangAdapter as NativeAdapter
from dca_grouped import install, optimized_class, set_variant


class SGLangAdapter(NativeAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.native_class = install(self.backend, short_splits=1)
        self.grouped_class = type(self.backend)
        root = Path(__file__).resolve().parent
        self.provenance.update({
            "optimization": "grouped GQA heads; corrected [heads,queries] LSE; num_splits=1; pack_gqa=False",
            "optimization_source_sha256": {n:hashlib.sha256((root/n).read_bytes()).hexdigest()
                                           for n in ["dca_grouped.py","sg_optimized_backend.py"]},
            "optimized_long_query_splits": 1, "optimized_short_query_splits": 1, "optimized_pack_gqa": False,
            "installed_framework_modified": False,
        })

    def use_native(self, enabled):
        set_variant(self.backend, self.native_class, self.grouped_class, not enabled)

    def run_operator_checks(self):
        torch = self.torch
        out = self.audit_path.parent
        torch.manual_seed(431 + self.rank)
        native = self.native_class.__new__(self.native_class)
        native.sparse_attention_enabled = False
        native.original_max_position_embeddings = 262144
        grouped = self.grouped_class.__new__(self.grouped_class)
        grouped.sparse_attention_enabled = False
        grouped.original_max_position_embeddings = 262144
        grouped.aegis_short_splits = 1
        record = out / f"operator-check-rank{self.rank}.jsonl"
        # Before, across and after the 253952-token DCA effective-chunk edges,
        # including large-Q Prefill, one query, and a partial physical page.
        for length, nq in [(8192,1),(8192,64),(65536,8192),(253953,1),
                           (253970,64),(507905,1),(508000,128),(1010000,1)]:
            queries = [torch.randn((nq,14,128),dtype=torch.bfloat16,device="cuda") for _ in range(5)]
            k = torch.randn((math.ceil(length/16),16,2,128),dtype=torch.bfloat16,device="cuda")
            v = torch.randn_like(k)
            table = torch.arange(k.shape[0],dtype=torch.int32,device="cuda").unsqueeze(0)
            cuq = torch.tensor([0,nq],dtype=torch.int32,device="cuda")
            cuk = torch.tensor([0,length],dtype=torch.int32,device="cuda")
            scale = torch.tensor([max(1.,1.+.1*math.log(length/262144))],device="cuda")
            def run(b):
                return b._dual_chunk_flash_attn_prefill(*queries,k,v,cuq,cuk,[length],scale,
                    128**-.5,block_table=table,chunk_size=262144,local_size=8192)
            a, b = run(native), run(grouped)
            delta = (a.float()-b.float()).abs()
            okay = torch.allclose(a,b,rtol=.01,atol=.02)
            row = {"context":length,"query_tokens":nq,"rank":self.rank,
                   "max_abs":delta.max().item(),"relative_l2":((a.float()-b.float()).norm()/a.float().norm()).item(),
                   "correctness":bool(okay),"timed_for_paper":False}
            if length == 1010000:
                for name, backend in [("native",native),("optimized",grouped)]:
                    run(backend);torch.cuda.synchronize();values=[]
                    for _ in range(3):
                        start=time.perf_counter();run(backend);torch.cuda.synchronize()
                        values.append((time.perf_counter()-start)*1000)
                    row[name+"_layer_ms"] = values
            with record.open("a") as f:f.write(json.dumps(row)+"\n")
            print(json.dumps({"operator_check":row}),flush=True)
            assert okay, row
            del queries,k,v,table,cuq,cuk,scale,a,b,delta
        torch.cuda.synchronize()
