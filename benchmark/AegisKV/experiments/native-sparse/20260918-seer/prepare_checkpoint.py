"""Fetch and verify the public, pinned full SeerAttention checkpoint on CPU."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import shutil

ROOT = Path(__file__).resolve().parent
MODEL = 'SeerAttention/SeerAttention-Llama-3.1-8B'
REVISION = '3ef8780dc42486c8187376897075fc17f52f9373'
DEST = ROOT / 'checkpoint'
CHUNK = 64 * 1024 * 1024


def fetch_chunk(task):
    entry, start, end, path = task
    if path.exists() and path.stat().st_size == end-start+1:
        return
    for attempt in range(3):
        try:
            temporary = path.with_suffix('.tmp')
            resume = temporary.stat().st_size if temporary.exists() else 0
            assert 0 <= resume <= end-start+1
            if resume == end-start+1:
                temporary.replace(path)
                return
            offset = start+resume
            url = (f'https://huggingface.co/{MODEL}/resolve/{REVISION}/'
                   f'{entry["rfilename"]}?download=true&chunk={offset}')
            req = urllib.request.Request(url, headers={'Range':f'bytes={offset}-{end}'})
            with urllib.request.urlopen(req, timeout=90) as response, temporary.open('ab') as out:
                expected = f'bytes {offset}-{end}/{entry["size"]}'
                assert response.status == 206 and response.headers.get('Content-Range') == expected
                shutil.copyfileobj(response, out, length=8*1024*1024)
            assert path.with_suffix('.tmp').stat().st_size == end-start+1
            path.with_suffix('.tmp').replace(path)
            print('CHUNK', entry['rfilename'], start, end, flush=True)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def fetch_weights(entries):
    tasks = []
    chunks_by_file = {}
    for entry in entries:
        name = entry['rfilename']
        final = DEST/name
        if final.exists() and final.stat().st_size == entry['size']:
            continue
        folder = DEST/(name+'.chunks')
        folder.mkdir(exist_ok=True)
        prefix = final.with_suffix(final.suffix+'.part')
        if prefix.exists():
            # Reuse only complete contiguous chunks from the interrupted stream.
            with prefix.open('rb') as stream:
                for start in range(0, (prefix.stat().st_size//CHUNK)*CHUNK, CHUNK):
                    chunk = folder/str(start)
                    data = stream.read(CHUNK)
                    if not chunk.exists():
                        chunk.write_bytes(data)
        chunks_by_file[name] = []
        for start in range(0, entry['size'], CHUNK):
            end = min(start+CHUNK, entry['size'])-1
            path = folder/str(start)
            tasks.append((entry,start,end,path))
            chunks_by_file[name].append(path)
    with ThreadPoolExecutor(max_workers=48) as pool:
        list(pool.map(fetch_chunk, tasks))
    for name, chunks in chunks_by_file.items():
        assembled = DEST/(name+'.assembled')
        with assembled.open('wb') as out:
            for path in chunks:
                with path.open('rb') as stream:
                    shutil.copyfileobj(stream,out,length=8*1024*1024)
        assembled.replace(DEST/name)
    # Full-file LFS SHA256, not segment size, decides whether data are trusted.
    return dict(fetch(entry) for entry in entries)


def fetch(entry):
    name = entry['rfilename']
    assert '/' not in name
    path = DEST / name
    size = entry['size']
    expected = entry.get('lfs', {}).get('sha256')
    if not path.exists() or path.stat().st_size != size:
        url = f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}'
        tmp = path.with_suffix(path.suffix + '.part')
        start = time.monotonic()
        print('FETCH', name, size, flush=True)
        with urllib.request.urlopen(url, timeout=90) as response, tmp.open('wb') as target:
            n = reported = 0
            while chunk := response.read(8 * 1024 * 1024):
                target.write(chunk)
                n += len(chunk)
                if n - reported >= 512 * 1024 * 1024:
                    print('PROGRESS', name, n, round(time.monotonic()-start, 1), flush=True)
                    reported = n
        assert tmp.stat().st_size == size, (name, tmp.stat().st_size, size)
        tmp.replace(path)
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert expected is None or sha == expected, (name, sha, expected)
    print('VERIFIED', name, size, flush=True)
    return name, dict(bytes=size, sha256=sha, upstream_lfs_sha256=expected)


if __name__ == '__main__':
    DEST.mkdir(exist_ok=True)
    metadata = json.loads((ROOT / 'SeerAttention-Llama-3.1-8B-metadata.json').read_text())
    assert metadata['sha'] == REVISION and metadata['gated'] is False
    files = [f for f in metadata['siblings'] if f['rfilename'] != '.gitattributes']
    # Complete small inspectable files before fetching the weight shards.
    small = [f for f in files if not f['rfilename'].endswith('.safetensors')]
    large = [f for f in files if f['rfilename'].endswith('.safetensors')]
    result = dict(fetch(f) for f in small)
    result.update(fetch_weights(large))
    (ROOT / 'checkpoint-verification.json').write_text(json.dumps(dict(
        status='verified', model=MODEL, revision=REVISION, files=result), indent=2)+'\n')
    print('CHECKPOINT_READY', flush=True)
