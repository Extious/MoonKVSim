"""Verify existing NOSA-8B weights and source against a pinned public revision."""
import json
from pathlib import Path
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / '20260921-concentration-new-models'))
from prepare_checkpoints import sha, small, save

REPO = 'openbmb/NOSA-8B'
REVISION = '6da5609664fa64ea55125a32e7cb70f541d97ea9'
CHECKPOINT = BASE / 'runtime-20260914/NOSA-8B'


def main():
    url = f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true'
    with urllib.request.urlopen(url, timeout=60) as response:
        metadata = json.load(response)
    assert metadata['sha'] == REVISION and metadata['gated'] is False
    save(HERE / 'checkpoint-metadata.json', metadata)
    files = {}
    for entry in metadata['siblings']:
        name = entry['rfilename']
        if name in ('.gitattributes', 'pytorch_model.bin'):
            continue
        if name.endswith('.safetensors'):
            path = CHECKPOINT / name
            assert path.stat().st_size == entry['size']
            digest = sha(path)
            assert digest == entry['lfs']['sha256'], name
            files[name] = dict(bytes=path.stat().st_size, sha256=digest,
                               upstream_lfs_sha256=entry['lfs']['sha256'])
        else:
            files[name] = small(REPO, REVISION, CHECKPOINT, entry)
        print('VERIFIED', name, flush=True)
    save(HERE / 'checkpoint-verification.json', dict(status='verified', model=REPO,
        revision=REVISION, checkpoint=str(CHECKPOINT), files=files))
    print('CHECKPOINT_READY', flush=True)


if __name__ == '__main__':
    main()
