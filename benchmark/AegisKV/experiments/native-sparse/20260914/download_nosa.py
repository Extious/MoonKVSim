"""Fetch the public, pinned NOSA-1B checkpoint and its published code."""
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path('/home/comp/zhanzhao/MoonKVSim/benchmark/AegisKV/experiments/native-sparse/runtime-20260914')
MODEL = ROOT / 'NOSA-1B'
REVISION = '7bdc33fbc1bc80b76b29689ba35ff6a7991b7dee'
BASE = 'https://huggingface.co/openbmb/NOSA-1B'
MODEL.mkdir(parents=True, exist_ok=True)


def open_url(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        'User-Agent': 'AegisKV-research-native-trace'
    }), timeout=60)


with open_url('https://huggingface.co/api/models/openbmb/NOSA-1B/revision/' + REVISION + '?blobs=true') as response:
    info = json.load(response)
assert info['sha'] == REVISION
(ROOT / 'hf-model-info.json').write_text(json.dumps(info, indent=2) + '\n')
files = [x for x in info['siblings'] if x['rfilename'] != '.gitattributes']
# Fetch inspectable code and configuration before the large weight file.
files.sort(key=lambda x: (x['rfilename'].endswith('.bin'), x['rfilename']))
manifest = {'repository': 'openbmb/NOSA-1B', 'revision': REVISION, 'files': {}}
for entry in files:
    name = entry['rfilename']
    assert '/' not in name
    target = MODEL / name
    expected_size = entry.get('size')
    expected_sha = entry.get('lfs', {}).get('sha256')
    if not target.exists() or expected_size is not None and target.stat().st_size != expected_size:
        part = target.with_suffix(target.suffix + '.part')
        start = time.monotonic()
        total = last_report = 0
        print('fetch', name, 'expected_bytes', expected_size, flush=True)
        with open_url(BASE + '/resolve/' + REVISION + '/' + name) as response, part.open('wb') as output:
            while chunk := response.read(4 * 1024 * 1024):
                output.write(chunk)
                total += len(chunk)
                if total - last_report >= 256 * 1024 * 1024:
                    print('progress', name, total, 'bytes', round(time.monotonic()-start,1), 'seconds', flush=True)
                    last_report = total
        if expected_size is not None:
            assert part.stat().st_size == expected_size, (name, part.stat().st_size, expected_size)
        part.rename(target)
    digest = hashlib.file_digest(target.open('rb'), 'sha256').hexdigest()
    if expected_sha:
        assert digest == expected_sha, (name, 'LFS digest mismatch')
    manifest['files'][name] = {'bytes': target.stat().st_size, 'sha256': digest,
                               'upstream_lfs_sha256': expected_sha}
    (ROOT / 'CHECKPOINT_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('verified', name, target.stat().st_size, flush=True)
print('CHECKPOINT_READY', str(MODEL), flush=True)
