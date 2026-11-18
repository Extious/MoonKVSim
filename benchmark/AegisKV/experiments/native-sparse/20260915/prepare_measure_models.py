"""Download and verify pinned weights without allocating a GPU or submitting jobs.

Run as a CPU-only Slurm prerequisite; the measurement job depends on its success.
--verify-only performs the same size/hash checks offline before GPU measurements.
No CUDA context is created and no paper figures are modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone

os.environ['HF_HUB_DISABLE_XET'] = '1'
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '120')
from huggingface_hub import snapshot_download

ROOT = Path('/home/comp/zhanzhao/MoonKVSim')
OUT = ROOT / 'benchmark/AegisKV/experiments/native-sparse/20260915'
STATUS = OUT / 'figure1-expansion-status.json'
MODELS = {
    'NOSA-3B': ('c5a4d505d5811f7555d786a031a4623787da7fb0', 7211741880,
                '991609e62adbec10654d25e8b16f62faedc457feeb3ba9ef8b88eeeea1cad3c1'),
    'NOSA-8B': ('6da5609664fa64ea55125a32e7cb70f541d97ea9', 16370581512,
                '5219c9ec34c4a19650e98b079ccf4911ffb3457e8f67690ca9037c09e89fd477'),
}


def update(**changes):
    value = json.loads(STATUS.read_text())
    value.update(changes, updated_at=datetime.now(timezone.utc).isoformat())
    temp = STATUS.with_suffix('.json.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(STATUS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true', help='Check weights offline; do not download or change campaign state')
    args = parser.parse_args()
    if not args.verify_only:
        update(status='downloading_cpu_prerequisite', preparation_error=None,
               preparation_job_id=os.environ.get('SLURM_JOB_ID'),
               user_decision='Inspect actual idle GPUs, then submit on a suitable available node; not limited to L40S')
    verified = {}
    try:
        for model, (revision, expected_size, expected_hash) in MODELS.items():
            snapshot = ROOT / 'benchmark/AegisKV/experiments/native-sparse/runtime-20260914' / model
            if not args.verify_only:
                print('WAIT_OR_DOWNLOAD', model, revision, flush=True)
                snapshot = Path(snapshot_download('openbmb/' + model, revision=revision,
                               local_dir=snapshot,
                               allow_patterns=['model.safetensors', '*.json', '*.py', 'tokenizer.model'], max_workers=2))
            path = snapshot / 'model.safetensors'
            if not path.is_file() or path.stat().st_size != expected_size:
                raise RuntimeError(f'Missing/incomplete checkpoint: {path}; expected {expected_size} bytes')
            with path.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            if digest != expected_hash:
                raise RuntimeError(f'Checkpoint SHA256 mismatch: {model}: {digest} != {expected_hash}')
            verified[model] = dict(revision=revision, bytes=expected_size, sha256=digest)
            if not args.verify_only:
                update(verified_checkpoints=verified)
            print('VERIFIED', model, digest, flush=True)
        if not args.verify_only:
            checkpoints = json.loads(STATUS.read_text())['new_checkpoints']
            for model in MODELS:
                checkpoints['openbmb/' + model]['download_status'] = 'complete_size_and_sha256_verified'
            update(status='checkpoints_verified', verified_checkpoints=verified, new_checkpoints=checkpoints)
        print('CHECKPOINTS_VERIFIED', flush=True)
    except Exception as exc:
        if not args.verify_only:
            update(status='preparation_failed', preparation_error=repr(exc), verified_checkpoints=verified)
        raise


if __name__ == '__main__':
    main()
