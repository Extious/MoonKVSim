"""Pinned Qwen1M MInference/DCA Prefill with the upstream context threshold.

Use upstream selector and sparse attention kernels. Limit temporary memory by
scheduling up to four query heads from the same KV group at a time. This does
not change the offline sparsity configuration. Compare against upstream's
all-head schedule before accepting model timings.
"""
import hashlib
import ast
import importlib.util
import inspect
import json
import textwrap
from pathlib import Path

from sg_backend import SGLangAdapter as BaseAdapter
from dca_grouped import optimized_class, EXPECTED_SOURCE


def gqa_sparse_function(native):
    """Keep the pinned selector, avoiding its materialized GQA K/V repeats.

    Sparse FlashAttention already accepts different query/KV head counts.
    The selector's three QK products can likewise batch by KV head. Explicit
    AST guards make this transformation fail closed on upstream changes.
    """
    import torch
    module = inspect.getmodule(native)
    tree = ast.parse(textwrap.dedent(inspect.getsource(native._dual_chunk_flash_attn_prefill_func)))

    class GQA(ast.NodeTransformer):
        repeats = 0
        products = 0

        def visit_Assign(self, node):
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in {f"{kv}_states_{part}" for kv in ("k", "v")
                                               for part in ("intra", "succ", "inter")}
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "reshape"
                    and any(isinstance(n, ast.Attribute) and n.attr == "repeat"
                            for n in ast.walk(node.value))):
                self.repeats += 1
                return None
            return self.generic_visit(node)

        def visit_BinOp(self, node):
            if isinstance(node.op, ast.MatMult):
                assert isinstance(node.right, ast.Call)
                assert isinstance(node.right.func, ast.Attribute)
                assert node.right.func.attr == "permute"
                self.products += 1
                return ast.copy_location(ast.Call(func=ast.Name(id="_aegis_gqa_scores", ctx=ast.Load()),
                                                   args=[node.left, node.right.func.value], keywords=[]), node)
            return self.generic_visit(node)

    def scores(query, key):
        nh, nq, dim = query.shape
        length, nk, kd = key.shape
        assert dim == kd and nh % nk == 0
        return torch.bmm(query.reshape(nk, nh // nk * nq, dim),
                         key.permute(1, 2, 0)).reshape(nh, nq, length)

    transform = GQA()
    tree = ast.fix_missing_locations(transform.visit(tree))
    assert transform.repeats == 6 and transform.products == 3
    namespace = dict(vars(module), _aegis_gqa_scores=scores)
    exec(compile(tree, "<pinned-dca-gqa-no-kv-repeat>", "exec"), namespace)
    return namespace["_dual_chunk_flash_attn_prefill_func"]


def sparse_class(native):
    import torch
    dense = optimized_class(native)
    gqa_function = gqa_sparse_function(native)

    class SparseDCA(dense):
        def _dual_chunk_flash_attn_prefill(
            self, q, q_succ, q_inter, q_succ_critical, q_inter_critical,
            k, v, cu_seqlens_q, cu_seqlens_k, orig_seq_lens,
            scaling_factor, softmax_scale, causal=True, window_size=(-1, -1),
            block_table=None, chunk_size=8192, local_size=1024,
        ):
            assert causal and window_size == (-1, -1)
            # Batch one is part of this experiment's fixed contract.
            qs, ks = cu_seqlens_q.cpu().tolist(), cu_seqlens_k.cpu().tolist()
            assert len(qs) == len(ks) == 2 and qs[0] == 0
            sparse = (orig_seq_lens[0] > self.sparse_attention_threshold
                      and qs[-1] >= self.aegis_sparse_min_queries)
            args = (q, q_succ, q_inter, q_succ_critical, q_inter_critical,
                    k, v, cu_seqlens_q, cu_seqlens_k, orig_seq_lens,
                    scaling_factor, softmax_scale, causal, window_size,
                    block_table, chunk_size, local_size)
            if not sparse:
                self.sparse_attention_enabled = False
                try:
                    return dense._dual_chunk_flash_attn_prefill(self, *args)
                finally:
                    self.sparse_attention_enabled = True
            self.aegis_sparse_invocations += 1
            if self.aegis_all_heads_reference:
                return native._dual_chunk_flash_attn_prefill(self, *args)
            key = k if block_table is not None else k[ks[0]:ks[1]]
            value = v if block_table is not None else v[ks[0]:ks[1]]
            nqh, nkh = q.shape[-2], key.shape[-2]
            assert nqh % nkh == 0
            group = nqh // nkh
            if q.shape[0] == 1:
                cfg = self.layer_sparse_attention_config
                assert all(x[0] == "vertical_and_slash" for x in cfg)
                vertical = torch.tensor([x[1] + (100 if x[1] == 30 else 0)
                                         for x in cfg], dtype=torch.int32)
                slash = torch.tensor([x[2] for x in cfg], dtype=torch.int32)
                return gqa_function(self, q, q_succ, q_inter, q_succ_critical,
                    q_inter_critical, key, value,
                    None if block_table is None else block_table[0],
                    softmax_scale, chunk_size, local_size, scaling_factor[0].item(),
                    ks[-1]-ks[0], sparse_attn_enabled=True,
                    heads_vertical_size=vertical, heads_slash_size=slash, group_size=group)
            out = torch.empty_like(q)
            for kh in range(nkh):
                for h0 in range(kh * group, (kh + 1) * group, self.aegis_sparse_head_group):
                    h1 = min(h0 + self.aegis_sparse_head_group, (kh + 1) * group)
                    cfg = self.layer_sparse_attention_config[h0:h1]
                    assert all(x[0] == "vertical_and_slash" for x in cfg)
                    vertical = torch.tensor([x[1] + (100 if x[1] == 30 else 0)
                                             for x in cfg], dtype=torch.int32)
                    slash = torch.tensor([x[2] for x in cfg], dtype=torch.int32)
                    parts = [x[:, h0:h1] for x in (q, q_succ, q_inter,
                             q_succ_critical, q_inter_critical)]
                    out[:, h0:h1] = gqa_function(self,
                        *parts, key[..., kh:kh+1, :], value[..., kh:kh+1, :],
                        None if block_table is None else block_table[0],
                        softmax_scale, chunk_size, local_size,
                        scaling_factor[0].item(), ks[-1]-ks[0],
                        sparse_attn_enabled=True, heads_vertical_size=vertical,
                        heads_slash_size=slash, group_size=h1-h0)
            return out

        def _do_flash_attn(self, *args, **kwargs):
            if kwargs.get("sparse_attn_enabled", False):
                return native._do_flash_attn(self, *args, **kwargs)
            return dense._do_flash_attn(self, *args, **kwargs)

    return SparseDCA


class SGLangAdapter(BaseAdapter):
    def __init__(self, args, contexts, rank, local_rank, world):
        import torch
        root = Path(__file__).resolve().parent
        build = json.loads((root / "setup/sparse-sm80/READY.json").read_text())
        for path, digest in ((build["library"], build["library_sha256"]),
                             (build["wrapper"], build["wrapper_sha256"])):
            assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        torch.ops.load_library(build["library"])
        spec = importlib.util.spec_from_file_location("aegis_sparse_wrapper", build["wrapper"])
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        super().__init__(args, contexts, rank, local_rank, world)
        native = type(self.backend)
        module = inspect.getmodule(native)
        assert hashlib.sha256(Path(inspect.getfile(native)).read_bytes()).hexdigest() == EXPECTED_SOURCE
        for name in ("convert_vertical_slash_indexes", "convert_vertical_slash_indexes_mergehead",
                     "sparse_attn_func"):
            setattr(module, name, getattr(wrapper, name))
        self.sparse_kernel_calls = 0
        def tracked_sparse(*a, **kw):
            self.sparse_kernel_calls += 1
            return wrapper.sparse_attn_func(*a, **kw)
        module.sparse_attn_func = tracked_sparse
        config_path = root / "sparse-config/Qwen2.5_7B_Instruct_1M.json"
        manifest = json.loads((root / "sparse-config/manifest.json").read_text())
        expected = manifest["files"]["minference/configs/Qwen2.5_7B_Instruct_1M.json"]["sha256"]
        assert hashlib.sha256(config_path.read_bytes()).hexdigest() == expected
        config = json.loads(config_path.read_text())
        assert len(config) == 28 and all(len(layer) == 28 for layer in config)
        b = self.backend
        b.sparse_attention_config = config
        b.sparse_attention_enabled = True
        b.arange = torch.arange(b.sparse_attention_last_q, device="cuda")
        b.last_q_mask = b.arange[None, None, :, None] >= b.arange[None, None, None, :]
        b.__class__ = sparse_class(native)
        b.aegis_sparse_head_group = args.sparse_head_group
        b.aegis_sparse_min_queries = 1
        b.aegis_short_splits = 1
        b.aegis_all_heads_reference = False
        b.aegis_sparse_invocations = 0
        assert args.sparse_head_group in (1, 2, 4, 7)
        self.native_class = native
        self.sparse_module = module
        self.provenance.update(
            sparse_kernel_build=build, sparse_config=manifest,
            sparse_config_sha256=expected, sparse_head_group=args.sparse_head_group,
            sparse_min_queries=1, sparse_context_threshold=b.sparse_attention_threshold,
            sparse_gqa_schedule="no materialized K/V repetition; one query batches all heads; prefix groups at most four query heads",
            short_query_attention="MInference/DCA above 32K; grouped dense DCA at/below 32K",
            sparse_adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.provenance["sparse_runtime_enabled"] = True

    def use_reference(self, enabled):
        self.backend.aegis_all_heads_reference = enabled

    def run_operator_checks(self):
        torch = self.torch
        gen = torch.Generator(device="cuda").manual_seed(1701 + self.rank)
        b = self.backend
        rows = []
        # Real sparse config and boundary-crossing shapes, compared with the
        # original all-head schedule using the same upstream CUDA kernels.
        for length, count in ((65536, 1), (65536, 128), (253968, 128),
                              (300000, 128), (300000, 1), (600000, 1)):
            nh, nk, dim = 14, 2, 128
            q = [torch.randn((count, nh, dim), generator=gen, device="cuda", dtype=torch.bfloat16)
                 for _ in range(5)]
            k = torch.randn((length, nk, dim), generator=gen, device="cuda", dtype=torch.bfloat16)
            v = torch.randn(k.shape, generator=gen, device="cuda", dtype=torch.bfloat16)
            b.layer_sparse_attention_config = b.get_sparse_attention_config(0)
            aq = torch.tensor([0, count], dtype=torch.int32, device="cuda")
            ak = torch.tensor([0, length], dtype=torch.int32, device="cuda")
            scale = torch.ones(1, device="cuda")
            kwargs = dict(chunk_size=262144, local_size=8192)
            b.aegis_all_heads_reference = True
            ref = b._dual_chunk_flash_attn_prefill(*q, k, v, aq, ak, [length], scale,
                                                 dim**-.5, **kwargs)
            b.aegis_all_heads_reference = False
            actual = b._dual_chunk_flash_attn_prefill(*q, k, v, aq, ak, [length], scale,
                                                    dim**-.5, **kwargs)
            finite = bool(torch.isfinite(actual).all() and torch.isfinite(ref).all())
            error = float((actual.float()-ref.float()).abs().max())
            okay = finite and bool(torch.allclose(actual, ref, rtol=.01, atol=.02))
            row = dict(context_tokens=length, queries=count, head_group=b.aegis_sparse_head_group,
                       rank=self.rank, check="grouped_vs_upstream_sparse", max_abs=error,
                       finite=finite, correctness=okay)
            rows.append(row)
            with self.audit_path.with_name(f"sparse-operator-rank{self.rank}.jsonl").open("a") as f:
                f.write(json.dumps(row)+"\n")
            assert okay, row
            del q, k, v, ref, actual
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        return rows
