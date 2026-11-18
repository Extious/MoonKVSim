"""Prepare pinned MiniCPM4.1 weights on CPU; never allocate a GPU or publish figures."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

PROJECT = Path('/home/comp/zhanzhao/MoonKVSim')
MODEL = 'openbmb/MiniCPM4.1-8B'
REVISION = '3a8dfed9c79a45e07dbff95bcd49d792343fa1a3'
CHECKPOINT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/runtime-20260914/MiniCPM4.1-8B'
OUT = PROJECT / 'benchmark/AegisKV/experiments/native-sparse/20260915-minicpm4.1-8b'
# File sizes and LFS SHA256 from the pinned Hugging Face revision API.
WEIGHTS = {
    'model-00001-of-00004.safetensors': (4968335472, 'd893df3a00be018df333f102251db12de40d614a39438ee9721398b272b0b9c0'),
    'model-00002-of-00004.safetensors': (4542417008, '064bcba714ff425b660057fd2a09f9e55bbb0db75e52fc5d082ddf3fcf5af11e'),
    'model-00003-of-00004.safetensors': (4936647824, 'a23c3ad2c4c1ca4eae8cbd0fd14cbc0391096cd167bb4969dc49b52abfac7a67'),
    'model-00004-of-00004.safetensors': (1923141264, 'e3809c32918b84150715c343736a27fb4cf082473fb82505f87566d7179588ea'),
}
SOURCE_HASHES = {
    'config.json': '2e6184e20da805d284b0ebba0bf5cf55bb561c6f333b66119fd2cc3f45a7ba15',
    'configuration_minicpm.py': 'f9014f14f71a175a53d48e862ebabb6007a09a2b7dd61eb6a00ddb0cee0ef9a5',
    'modeling_minicpm.py': 'cd81d52e8e0d35d0c35a75ca4d03ed23f19dae29acf085ea24147003c78d8a3a',
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_checkpoint(snapshot=CHECKPOINT):
    """Offline, fail-closed verification; shared by preparation and capture."""
    index = json.loads((snapshot / 'model.safetensors.index.json').read_text())
    if set(index['weight_map'].values()) != set(WEIGHTS):
        raise ValueError('Checkpoint shard inventory differs from pinned revision')
    verified = {}
    for name, (size, expected) in WEIGHTS.items():
        path = snapshot / name
        if not path.is_file() or path.stat().st_size != size:
            raise ValueError(f'Missing/incomplete checkpoint shard: {path}')
        actual = digest(path)
        if actual != expected:
            raise ValueError(f'Checkpoint hash mismatch: {path}')
        verified[name] = dict(bytes=size, sha256=actual)
        print('VERIFIED_SHARD', name, actual, flush=True)
    for name, expected in SOURCE_HASHES.items():
        if digest(snapshot / name) != expected:
            raise ValueError(f'Pinned configuration/source mismatch: {name}')
    tokenizer_hashes = {path.name: digest(path) for path in sorted(snapshot.glob('tokenizer*')) if path.is_file()}
    if 'tokenizer.json' not in tokenizer_hashes or 'tokenizer_config.json' not in tokenizer_hashes:
        raise ValueError('Checkpoint-specific tokenizer files are missing')
    return dict(model=MODEL, revision=REVISION, checkpoint=str(snapshot), checkpoint_weights=verified,
                source_sha256=SOURCE_HASHES, tokenizer_sha256=tokenizer_hashes,
                index_sha256=digest(snapshot / 'model.safetensors.index.json'))


def persist(value):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'checkpoint-verification.json'
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        print(json.dumps(verify_checkpoint(), indent=2))
        return
    os.environ['HF_HUB_DISABLE_XET'] = '1'
    os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT', '120')
    from huggingface_hub import snapshot_download
    status = dict(status='downloading', model=MODEL, revision=REVISION,
                  slurm_job_id=os.environ.get('SLURM_JOB_ID'),
                  started_at=datetime.now(timezone.utc).isoformat())
    persist(status)
    try:
        print('DOWNLOAD', MODEL, REVISION, flush=True)
        snapshot_download(MODEL, revision=REVISION, local_dir=CHECKPOINT,
                          allow_patterns=['*.safetensors', '*.json', '*.py', 'tokenizer.model'], max_workers=2)
        status.update(verify_checkpoint(), status='verified', completed_at=datetime.now(timezone.utc).isoformat())
        persist(status)
        print('CHECKPOINT_VERIFIED', MODEL, flush=True)
    except Exception as exc:
        status.update(status='failed', error=repr(exc))
        persist(status)
        raise


if __name__ == '__main__':
    main()
