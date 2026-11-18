"""Build the pinned, unmodified MInference CUDA index packer."""
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
VENV = BASE / 'runtime-20260914/venv'
os.environ['CUDA_HOME'] = '/usr/local/cuda-12.8'
os.environ['PATH'] = f'{VENV}/bin:/usr/local/cuda-12.8/bin:' + os.environ['PATH']
os.environ['TORCH_CUDA_ARCH_LIST'] = '8.0'
os.environ['MAX_JOBS'] = '2'
from torch.utils.cpp_extension import load

root = BASE / 'runtime-20260921'
source, build = root / 'MInference/csrc', root / 'minference-index-build'
paths = [source / 'kernels.cpp', source / 'vertical_slash_index.cu']
site = Path('/home/comp/zhanzhao/sglang/.venv/lib/python3.12/site-packages/nvidia')
cccl = BASE / 'runtime-20260914/uv-cache/archive-v0/oFvVQ7YRv8D32gN1OblKx/nvidia/cuda_cccl/include'
includes = [site / 'cuda_runtime/include', site / 'cuda_nvcc/include', cccl]
assert (cccl / 'nv/target').is_file()
mod = load('minference_index64', sources=list(map(str, paths)),
    build_directory=str(build), verbose=True, extra_include_paths=list(map(str, includes)),
    extra_cflags=['-O3'], extra_cuda_cflags=['-O3'],
    extra_ldflags=[f'-L{BASE}/runtime-20260914/cuda-lib'])
record = dict(library=mod.__file__,
    source_revision='29ef1974fcb5a1440ccf92d7d7996900230fddcf',
    sources={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    library_sha256=hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest(),
    extra_include_paths=list(map(str, includes)))
(build / 'READY.json').write_text(json.dumps(record, indent=2) + '\n')
