"""Complete pinned public checkpoints on CPU, retaining all prior artifacts."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
CHUNK = 64 * 1024 * 1024
MODELS = [("Qwen2.5-7B-Instruct-1M", "Qwen/Qwen2.5-7B-Instruct-1M", "e28526f7bb80e2a9c8af03b831a9af3812f18fba", BASE / "runtime-20260921/Qwen2.5-7B-Instruct-1M")]


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def small(repo, revision, dest, entry):
    name = entry["rfilename"]
    assert "/" not in name
    target = dest / name
    if not target.exists():
        url = f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
        with urllib.request.urlopen(url, timeout=90) as response:
            data = response.read()
        assert len(data) == entry["size"]
        temp = target.with_suffix(target.suffix + ".part")
        temp.write_bytes(data)
        temp.replace(target)
    data = target.read_bytes()
    assert len(data) == entry["size"], name
    if entry.get("lfs"):
        assert hashlib.sha256(data).hexdigest() == entry["lfs"]["sha256"], name
    else:
        git_hash = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        assert git_hash == entry["blobId"], (name, git_hash, entry["blobId"])
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def chunk(task):
    repo, revision, entry, start, end, target = task
    size = end - start + 1
    if target.exists() and target.stat().st_size == size:
        return
    temporary = target.with_suffix(".part")
    for attempt in range(4):
        try:
            resume = temporary.stat().st_size if temporary.exists() else 0
            assert 0 <= resume <= size
            if resume < size:
                offset = start + resume
                url = (f"https://huggingface.co/{repo}/resolve/{revision}/"
                       f"{entry['rfilename']}?download=true&chunk={offset}")
                request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{end}"})
                with urllib.request.urlopen(request, timeout=90) as response:
                    assert response.status == 206, response.status
                    assert response.headers.get("Content-Range") == f"bytes {offset}-{end}/{entry['size']}"
                    with temporary.open("ab") as output:
                        shutil.copyfileobj(response, output, 8 * 1024 * 1024)
            assert temporary.stat().st_size == size
            temporary.replace(target)
            return
        except Exception as exc:
            print("RETRY", repo, entry["rfilename"], start, attempt, type(exc).__name__, flush=True)
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def main():
    preparations = []
    # Finish inspectable sources for both models before large transfers.
    for label, repo, revision, dest in MODELS:
        dest.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
        with urllib.request.urlopen(url, timeout=90) as response:
            metadata = json.load(response)
        assert metadata["sha"] == revision and metadata["gated"] is False
        save(ROOT / f"{label}-metadata.json", metadata)
        entries = [e for e in metadata["siblings"] if e["rfilename"] != ".gitattributes"]
        files = {}
        for entry in entries:
            if not entry["rfilename"].endswith(".safetensors"):
                files[entry["rfilename"]] = small(repo, revision, dest, entry)
        preparations.append((label, repo, revision, dest, entries, files))
        print("SOURCES_READY", label, str(dest), flush=True)
    for label, repo, revision, dest, entries, files in preparations:
        weights = [e for e in entries if e["rfilename"].endswith(".safetensors")]
        tasks, missing = [], []
        for entry in weights:
            target = dest / entry["rfilename"]
            if target.exists():
                assert target.stat().st_size == entry["size"], target
                continue
            folder = dest / (entry["rfilename"] + ".download-parts")
            folder.mkdir(exist_ok=True)
            paths = []
            for start in range(0, entry["size"], CHUNK):
                end = min(start + CHUNK, entry["size"]) - 1
                path = folder / str(start)
                tasks.append((repo, revision, entry, start, end, path))
                paths.append(path)
            missing.append((entry, paths))
        print("DOWNLOAD", label, len(tasks), "chunks", flush=True)
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(chunk, task) for task in tasks]
            for i, future in enumerate(as_completed(futures), 1):
                future.result()
                if i % 8 == 0 or i == len(tasks):
                    print("CHUNKS_COMPLETE", label, i, len(tasks), flush=True)
        for entry, paths in missing:
            target = dest / entry["rfilename"]
            assembled = target.with_suffix(target.suffix + ".assembled")
            with assembled.open("wb") as output:
                for path in paths:
                    with path.open("rb") as stream:
                        shutil.copyfileobj(stream, output, 8 * 1024 * 1024)
            assert assembled.stat().st_size == entry["size"]
            assert sha(assembled) == entry["lfs"]["sha256"], assembled
            assembled.replace(target)
        for entry in weights:
            target = dest / entry["rfilename"]
            digest = sha(target)
            assert digest == entry["lfs"]["sha256"], target
            files[entry["rfilename"]] = {"bytes": target.stat().st_size, "sha256": digest,
                                         "upstream_lfs_sha256": entry["lfs"]["sha256"]}
            print("VERIFIED", label, entry["rfilename"], flush=True)
        save(ROOT / f"{label}-checkpoint-verification.json", {
            "status": "verified", "model": repo, "revision": revision,
            "checkpoint": str(dest), "files": files})
        print("CHECKPOINT_READY", label, flush=True)


if __name__ == "__main__":
    main()
