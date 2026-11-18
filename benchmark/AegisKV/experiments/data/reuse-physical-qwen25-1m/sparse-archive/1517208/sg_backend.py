"""Adapter to the remote, already installed SGLang native DCA worker.

No engine source changes. Explicit ForwardBatch and actual paged KV storage;
the same model body used by Qwen2ForCausalLM, ending before lm_head.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace


class SequenceData:
    @classmethod
    def from_seqs(cls, tokens):
        obj = cls()
        obj.tokens = tokens
        obj.computed = 0
        return obj

    def get_num_computed_tokens(self):
        return self.computed

    def update_num_computed_tokens(self, count):
        self.computed += count
        assert self.computed <= len(self.tokens)


class SGLangAdapter:
    def __init__(self, args, contexts, rank, local_rank, world):
        import torch
        import sglang
        from sglang.bench_one_batch import load_model
        from sglang.srt.entrypoints.engine import _set_envs_and_config
        from sglang.srt.layers.moe import initialize_moe_config
        from sglang.srt.layers.quantization.fp4_utils import initialize_fp4_gemm_config
        from sglang.srt.layers.quantization.fp8_utils import initialize_fp8_gemm_config
        from sglang.srt.server_args import ServerArgs

        dca = json.loads((Path(args.model) / "config.json").read_text())["dual_chunk_attention_config"]
        dca["sparse_attention_enabled"] = False
        server = ServerArgs(
            model_path=args.model, tokenizer_path=args.model,
            dtype="bfloat16", kv_cache_dtype="auto", tp_size=world,
            context_length=max(contexts), max_running_requests=1,
            max_total_tokens=max(contexts) + 32, chunked_prefill_size=args.chunk,
            max_prefill_tokens=args.chunk, page_size=16,
            mem_fraction_static=0.9, attention_backend="dual_chunk_flash_attn",
            disable_cuda_graph=True, disable_piecewise_cuda_graph=True,
            disable_custom_all_reduce=True, disable_overlap_schedule=True,
            enable_torch_compile=False, random_seed=17,
            json_model_override_args=json.dumps({"dual_chunk_attention_config": dca}),
        )
        _set_envs_and_config(server)
        initialize_moe_config(server)
        initialize_fp8_gemm_config(server)
        initialize_fp4_gemm_config(server)
        ports = SimpleNamespace(nccl_port=int(os.environ["MASTER_PORT"]))
        wrapped, self.tokenizer = load_model(server, ports, local_rank, rank)
        self.runner = wrapped.torch_runner
        # The ARM64 common_ops wheel omits SM80. Select the official FlashInfer
        # fused SiLU implementation, already CPU-built for A100, for this model.
        # This is a recorded kernel choice shared by all three recovery paths.
        from flashinfer.activation import silu_and_mul
        from sglang.srt.layers.activation import SiluAndMul
        activations = 0
        for module in self.runner.model.modules():
            if isinstance(module, SiluAndMul):
                module._forward_method = silu_and_mul
                activations += 1
        assert activations == self.runner.model_config.hf_config.num_hidden_layers
        self.model = self
        self.cfg = SimpleNamespace(model_config=self.runner.model_config)
        self.framework = f"sglang {sglang.__version__}"
        self.torch = torch
        self.world = world
        self.rank = rank
        self.audit_path = Path(args.output) / f"kernel-audit-rank{rank}.json"
        self.audited_modes = set()
        self.audited_ops = set()
        self.limit = max(contexts)
        self.max_blocks = (self.limit + 15) // 16
        self.pool = self.runner.token_to_kv_pool
        self.backend = self.runner.attn_backend
        assert type(self.backend).__name__ == "DualChunkFlashAttentionBackend"
        assert not self.backend.sparse_attention_enabled
        self.runner.req_to_token_pool.req_to_token[0, :self.limit] = torch.arange(
            16, 16 + self.limit, dtype=torch.int32, device="cuda")
        self.caches = []
        for layer in range(self.runner.model_config.hf_config.num_hidden_layers):
            for get in [self.pool.get_key_buffer, self.pool.get_value_buffer]:
                x = get(layer)[16:16 + self.max_blocks * 16]
                assert x.shape[0] == self.max_blocks * 16 and x.is_contiguous()
                self.caches.append(x.view(1, self.max_blocks, 16, *x.shape[1:]))
        source_root = Path(sglang.__file__).parent
        files = ["srt/models/qwen2.py", "srt/layers/attention/dual_chunk_flashattention_backend.py",
                 "srt/model_executor/model_runner.py", "srt/model_executor/forward_batch_info.py"]
        revision = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.provenance = {"framework_source_sha256": {
            name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in files},
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "framework_git_revision": revision.stdout.strip() if revision.returncode == 0 else None,
            "framework_package_version": sglang.__version__}
        self.provenance["activation_backend"] = "flashinfer.activation.silu_and_mul"
        self.provenance["activation_layers"] = activations
        kernel_record = Path(__file__).resolve().parent / "setup/sm80-ready.json"
        if kernel_record.exists():
            self.provenance["kernel_build"] = json.loads(kernel_record.read_text())
            assert self.runner.model_config.hf_config.hidden_size // self.runner.model_config.hf_config.num_attention_heads == 128

    def forward(self, seq, count, prompt):
        from sglang.srt.model_executor.forward_batch_info import ForwardBatch, ForwardMode
        from sglang.srt.speculative.spec_info import SpeculativeAlgorithm
        torch = self.torch
        start = seq.computed
        end = start + count
        ids = torch.tensor(seq.tokens[start:end], dtype=torch.int64, device="cuda")
        def ints(values):
            return torch.tensor(values, dtype=torch.int32, device="cuda")
        batch = ForwardBatch(
            forward_mode=ForwardMode.EXTEND if prompt else ForwardMode.DECODE,
            batch_size=1, input_ids=ids, req_pool_indices=ints([0]),
            seq_lens=ints([end]), seq_lens_cpu=torch.tensor([end], dtype=torch.int32),
            out_cache_loc=torch.arange(16 + start, 16 + end, dtype=torch.int64, device="cuda"),
            seq_lens_sum=end, orig_seq_lens=ints([len(seq.tokens)]),
            positions=torch.arange(start, end, dtype=torch.int64, device="cuda"),
            extend_num_tokens=count, extend_seq_lens=ints([count]),
            extend_prefix_lens=ints([start]), extend_start_loc=ints([0]),
            extend_prefix_lens_cpu=[start], extend_seq_lens_cpu=[count],
            extend_logprob_start_lens_cpu=[0],
            req_to_token_pool=self.runner.req_to_token_pool,
            token_to_kv_pool=self.pool, attn_backend=self.backend,
            spec_algorithm=SpeculativeAlgorithm.NONE,
            num_token_non_padded=ints(count), num_token_non_padded_cpu=count,
        )
        self.backend.init_forward_metadata(batch)
        mode = "decode" if not prompt else ("tail" if count <= 64 else "prefill")
        if mode not in self.audited_modes:
            # This runs only while constructing untimed reference state, before
            # any measured trial. Reject accidental use of the incompatible
            # ARM64 common_ops CUDA kernels instead of silently falling back.
            from torch.utils._python_dispatch import TorchDispatchMode
            adapter = self
            class Audit(TorchDispatchMode):
                def __torch_dispatch__(self, func, types, args=(), kwargs=None):
                    name = func._schema.name
                    if name.startswith("sgl_kernel::"):
                        adapter.audited_ops.add(name)
                        if name not in {
                            "sgl_kernel::weak_ref_tensor",  # Host-side tensor alias helper.
                            "sgl_kernel::fwd",  # Rebuilt flash_ops, not common_ops.
                            "sgl_kernel::get_scheduler_metadata",  # Rebuilt flash_ops.
                        }:
                            raise RuntimeError(f"Unsupported common_ops CUDA path: {name}")
                    return func(*args, **(kwargs or {}))
            with Audit():
                hidden = self.runner.model.model(ids, batch.positions, batch)
            self.audited_modes.add(mode)
            self.audit_path.write_text(json.dumps({"passed_modes": sorted(self.audited_modes),
                "sgl_ops_observed": sorted(self.audited_ops),
                "activation": "FlashInfer fused SiLU", "timed": False}, indent=2))
        else:
            hidden = self.runner.model.model(ids, batch.positions, batch)
        seq.update_num_computed_tokens(count)
        return hidden

    def compute_logits(self, hidden, unused):
        # Untimed correctness projection with the real tensor-parallel lm_head.
        from sglang.srt.distributed import tensor_model_parallel_all_gather
        logits = self.torch.nn.functional.linear(hidden, self.runner.model.lm_head.weight)
        if self.world > 1:
            logits = tensor_model_parallel_all_gather(logits, dim=-1)
        return logits[..., :self.runner.model_config.hf_config.vocab_size].float()
