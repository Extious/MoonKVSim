"""Logged runtime checks inside the actual Slurm allocation; no model timings."""
import os
from pathlib import Path
import tempfile
import time

print("PYTHON_STARTED", time.time(), flush=True)
assert Path(tempfile.gettempdir()).resolve() == Path(os.environ["TMPDIR"]).resolve()
with tempfile.TemporaryFile() as f:
    f.write(b"aegiskv temporary directory check")
    f.flush()
print("TEMP_READY", tempfile.gettempdir(), flush=True)

import torch

print("TORCH_IMPORTED", torch.__version__, torch.version.cuda, time.time(), flush=True)
torch.cuda.init()
expected = int(os.environ.get("TP", "1"))
assert torch.cuda.device_count() >= expected
devices = []
for i in range(expected):
    props = torch.cuda.get_device_properties(i)
    assert props.major >= 8, "Native BF16/FlashAttention requires Ampere or newer"
    with torch.cuda.device(i):
        x = torch.ones((16, 16), device="cuda", dtype=torch.bfloat16)
        y = x @ x
        torch.cuda.synchronize()
        assert y[0, 0].item() == 16
    devices.append((props.name, props.total_memory, props.major, props.minor))
assert len(set(devices)) == 1, "One run must use a homogeneous GPU group"
print("CUDA_READY", devices, time.time(), flush=True)

from sglang.srt.model_executor.model_runner import ModelRunner

print("MODEL_RUNNER_IMPORTED", time.time(), flush=True)
from sglang.srt.layers.attention.dual_chunk_flashattention_backend import DualChunkFlashAttentionBackend

print("DCA_IMPORTED", time.time(), flush=True)
print("PREFLIGHT_COMPLETE", flush=True)
