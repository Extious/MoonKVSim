"""Bounded synthetic operator diagnosis, NOT paper model-latency samples.

Uses the unchanged measured SGLang DCA implementation and same BF16 shapes.
Compares native per-head dispatch with grouped-head dispatch into its existing
inner DCA function. No weights, full-prefix reconstruction, or quality claim.
"""
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import socket
import statistics
import time


def worker(rank, world, port):
    import torch
    import torch.distributed as dist
    from sglang.srt.layers.attention.dual_chunk_flashattention_backend import DualChunkFlashAttentionBackend

    torch.set_num_threads(4)
    torch.cuda.set_device(rank)
    torch.manual_seed(17)
    dist.init_process_group('nccl', init_method=f'tcp://127.0.0.1:{port}', rank=rank, world_size=world)
    out = Path(os.environ['AEGIS_DIAG_OUT'])
    def write(obj):
        with (out / f'diagnostic-rank{rank}.jsonl').open('a') as f:
            f.write(json.dumps(obj) + '\n')
        print(json.dumps({'rank': rank, **obj}), flush=True)

    props = torch.cuda.get_device_properties(rank)
    source = Path(inspect.getfile(DualChunkFlashAttentionBackend))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == '86fc86a8b2544a22294a3449c39bab689760239326ddbb8be4a95c3d577f18b7'
    write({'event': 'metadata', 'torch': str(torch.__version__), 'gpu': props.name,
           'sms': props.multi_processor_count, 'backend_sha256': digest,
           'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'synthetic': True, 'weights_loaded': False, 'purpose': 'operator attribution only'})

    def bench(fn, repeats=3):
        fn()
        torch.cuda.synchronize()
        times = []
        for _ in range(repeats):
            start = time.perf_counter()
            result = fn()
            torch.cuda.synchronize()
            times.append((time.perf_counter() - start) * 1000)
        return {'median_ms': statistics.median(times), 'samples_ms': times}, result

    with torch.inference_mode():
        # Two typical TP reductions per layer; this is an isolated transport
        # diagnostic, not measured NCCL attribution from the original forward.
        x = torch.zeros((64, 3584), device='cuda', dtype=torch.bfloat16)
        def collectives():
            for _ in range(56):
                dist.all_reduce(x)
        dist.barrier()
        timing, _ = bench(collectives)
        write({'event': 'nccl_56_allreduces', 'tensor_bytes': x.numel() * x.element_size(), **timing})
        backend = DualChunkFlashAttentionBackend.__new__(DualChunkFlashAttentionBackend)
        backend.sparse_attention_enabled = False
        backend.sparse_attention_threshold = 0
        backend.original_max_position_embeddings = 262144
        class GroupedDiagnostic(DualChunkFlashAttentionBackend):
            def _do_flash_attn(self, query_states, *args, **kwargs):
                output, lse = super()._do_flash_attn(query_states, *args, **kwargs)
                # Native dense code only sees one head, so its LSE reshape is
                # accidentally valid there. Preserve FA's [heads, queries]
                # order when exercising grouped heads in this diagnostic.
                nq, nh = query_states.shape[:2]
                lse = lse.transpose(0, 2).reshape(nh, nq).unsqueeze(0)
                return output, lse
        grouped_backend = GroupedDiagnostic.__new__(GroupedDiagnostic)
        grouped_backend.original_max_position_embeddings = 262144
        for length in [8192, 65536, 1010000]:
            q = torch.randn((64, 14, 128), device='cuda', dtype=torch.bfloat16)
            k = torch.randn((length // 16, 16, 2, 128), device='cuda', dtype=torch.bfloat16)
            v = torch.randn_like(k)
            table = torch.arange(length // 16, device='cuda', dtype=torch.int32)
            cuq = torch.tensor([0, 64], device='cuda', dtype=torch.int32)
            cuk = torch.tensor([0, length], device='cuda', dtype=torch.int32)
            scale = torch.ones(1, device='cuda')
            def native():
                return backend._dual_chunk_flash_attn_prefill(
                    q, q, q, q, q, k, v, cuq, cuk, [length], scale,
                    128 ** -0.5, block_table=table.unsqueeze(0),
                    chunk_size=262144, local_size=8192)
            def grouped():
                return grouped_backend._dual_chunk_flash_attn_prefill_func(
                    q, q, q, q, q, k, v, table, 128 ** -0.5,
                    262144, 8192, 1.0, length, sparse_attn_enabled=False, group_size=7)
            dist.barrier()
            native_time, a = bench(native)
            grouped_time, b = bench(grouped)
            error = (a.float() - b.float()).abs()
            write({'event': 'attention_comparison', 'context': length,
                   'native': native_time, 'grouped': grouped_time,
                   'output_max_abs': error.max().item(),
                   'output_relative_l2': ((a.float()-b.float()).norm()/a.float().norm()).item(),
                   'allclose_1e2': torch.allclose(a, b, rtol=0.01, atol=0.01)})
            # Separate transfer of one layer's K and V on both ranks at once.
            hostk = torch.empty_like(k, device='cpu', pin_memory=True)
            hostv = torch.empty_like(v, device='cpu', pin_memory=True)
            hostk.copy_(k); hostv.copy_(v)
            def copy_layer():
                k.copy_(hostk, non_blocking=True)
                v.copy_(hostv, non_blocking=True)
            dist.barrier()
            h2d, _ = bench(copy_layer)
            write({'event': 'h2d_one_layer', 'context': length,
                   'bytes_per_rank': (k.numel()+v.numel())*2, **h2d})
            del hostk, hostv
            if length == 1010000 and rank == 0:
                # Record real kernel launch grids and times, including gathers.
                for name, fn in [('native', native), ('grouped', grouped)]:
                    try:
                        with torch.profiler.profile(activities=[
                            torch.profiler.ProfilerActivity.CPU,
                            torch.profiler.ProfilerActivity.CUDA], record_shapes=True) as prof:
                            fn()
                            torch.cuda.synchronize()
                        prof.export_chrome_trace(str(out / f'{name}-trace.json'))
                        rows = [{'key': e.key, 'count': e.count,
                                 'self_cpu_us': e.self_cpu_time_total,
                                 'self_device_us': e.self_device_time_total,
                                 'device_us': e.device_time_total}
                                for e in prof.key_averages()]
                        (out / f'{name}-operators.json').write_text(json.dumps(rows, indent=2))
                        write({'event': 'profile_saved', 'variant': name})
                    except Exception as exc:
                        write({'event': 'profile_failed', 'variant': name, 'error': repr(exc)})
            dist.barrier()
            del q, k, v, a, b
        write({'event': 'complete'})
    dist.destroy_process_group()


if __name__ == '__main__':
    import torch.multiprocessing as mp
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    mp.spawn(worker, args=(2, port), nprocs=2, join=True)
