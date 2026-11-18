"""BLSC gpu partition, as recorded by the A100-PCIe jobs.

Jobs 1517208 and 1516171 each took one node with two NVIDIA A100-PCIE-40GB
GPUs. Pinned H2D was measured at 23.98 GB/s and HBM read at 1079.20 GB/s
(job 1516171, random BF16, not a full recovery). D2H was not measured
separately; checkpoint copies on this config use the same PCIe figure and
are labeled as such. A peer outside the node is a second node of the same
kind, not a second measured allocation.
"""

from __future__ import annotations

from dataclasses import replace

from .model import Config

GPU_NAME = "NVIDIA A100-PCIE-40GB"
GPUS_PER_NODE = 2
TP = 2
H2D_BYTES_PER_SECOND = 23.98e9
HBM_READ_BYTES_PER_SECOND = 1079.20e9
HBM_BYTES_PER_GPU = 40 * 1024**3
# Slurm job memory request, not a DIMM inventory.
JOB_MEMORY_BYTES = 109952 * 1024**2
SOURCE = "benchmark/AegisKV/experiments/data/reuse-physical-qwen25-1m/blsc"


def config(**changes) -> Config:
    """Two DP workers, one TP=2 group per node, measured PCIe rate."""
    base = Config(
        hosts=(0, 1),
        tp=TP,
        h2d_bytes_per_second=H2D_BYTES_PER_SECOND,
        d2h_bytes_per_second=H2D_BYTES_PER_SECOND,
        hbm_bytes_per_rank=HBM_BYTES_PER_GPU // 2,
        dram_bytes_per_host=JOB_MEMORY_BYTES,
        router_mode="design",
        layers=32,
        depth=4,
        top_k=16,
        kv_bytes_per_token_per_layer_rank=1024,
    )
    return replace(base, **changes)
