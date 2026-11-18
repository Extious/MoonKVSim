"""Create the submission gate from completed CPU checks and verified assets."""
import hashlib
import json
from pathlib import Path
import time

root = Path(__file__).resolve().parent.parent
model = Path('/home/bingxing2/home/scx8q31/models/Qwen2.5-7B-Instruct-1M')
revision = 'e28526f7bb80e2a9c8af03b831a9af3812f18fba'
cpu = json.loads((root / 'setup/cpu-check.json').read_text())
assert cpu['passed'] and all(cpu['checks'].values()), cpu
cuda = json.loads((root / 'setup/cuda-ready.json').read_text())
assert cuda['passed'] and cuda['arch'] == '8.0'
flash = json.loads((root / 'setup/flash-ops-architecture.json').read_text())
assert flash['architectures'].get('sm_80', 0) > 0, 'Installed FlashAttention has no A100 kernels'
assert hashlib.sha256(Path(flash['library']).read_bytes()).hexdigest() == flash['library_sha256']
sm80 = json.loads((root / 'setup/sm80-ready.json').read_text())
assert sm80['passed']
weights = json.loads((root / 'setup/model-download/WEIGHTS_COMPLETE.json').read_text())
metadata = json.loads((model / 'WEIGHTS_VERIFIED.json').read_text())
manifest = json.loads((root / 'model-weight-manifest.json').read_text())
assert weights['revision'] == metadata['revision'] == revision
assert weights['manifest'] == metadata['shards'] == manifest
for entry in manifest:
    assert (model / entry['rfilename']).stat().st_size == entry['size']
for name, digest in metadata['metadata_sha256'].items():
    assert hashlib.sha256((model / name).read_bytes()).hexdigest() == digest
files = ['measure.py', 'sg_backend.py', 'launch_sglang.py', 'aggregate.py',
         'job_environment.sh', 'blsc/run_budgeted.sbatch', 'blsc/budget_submit.py',
         'blsc/driver_check.py', 'blsc/gpu_kernel_check.py']
ready = {
    'weights_sha256_verified': True, 'cpu_imports_passed': True,
    'flash_ops_sm80_available': True,
    'activation_backend': 'flashinfer.activation.silu_and_mul; CPU-built SM80',
    'sm80_libraries': sm80['libraries'],
    'model_revision': revision, 'python': str(root / '.venv/bin/python'),
    'model': str(model), 'created_at': time.time(),
    'runtime_files_sha256': {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files},
    'cpu_check_sha256': hashlib.sha256((root / 'setup/cpu-check.json').read_bytes()).hexdigest(),
    'cpu_kernel_build_sha256': hashlib.sha256((root / 'setup/cuda-ready.json').read_bytes()).hexdigest(),
    'weights_verification_sha256': hashlib.sha256((root / 'setup/model-download/WEIGHTS_COMPLETE.json').read_bytes()).hexdigest(),
}
(root / 'blsc/READY.json').write_text(json.dumps(ready, indent=2) + '\n')
print(json.dumps(ready, indent=2))
