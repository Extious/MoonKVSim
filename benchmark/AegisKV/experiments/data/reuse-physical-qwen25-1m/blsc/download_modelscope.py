"""Login-node range download; every shard must match the pinned HF SHA-256."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

TASK = Path.home() / "aegiskv_reuse_qwen25_1m_20260919"
MODEL = Path.home() / "models/Qwen2.5-7B-Instruct-1M"
STATE = TASK / "setup/model-download"
CHUNK = 64 * 1024**2


def main():
    MODEL.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((TASK / "model-weight-manifest.json").read_text())
    for item in manifest:
        name, size = item["rfilename"], item["size"]
        dest = MODEL / name
        part = MODEL / (name + ".modelscope.partial")
        fd = os.open(part, os.O_CREAT | os.O_RDWR, 0o644)
        os.ftruncate(fd, size)

        def download(start):
            end = min(start + CHUNK, size) - 1
            marker = STATE / f"{name}.{start}.ok"
            if marker.exists():
                return end - start + 1
            for attempt in range(3):
                try:
                    url = ("https://modelscope.cn/models/Qwen/Qwen2.5-7B-Instruct-1M/resolve/master/"
                           + name + f"?download=true&offset={start}")
                    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
                    with urllib.request.urlopen(request, timeout=45) as response:
                        assert response.headers.get("Content-Range") == f"bytes {start}-{end}/{size}"
                        position = start
                        while position <= end:
                            data = response.read(min(4 * 1024**2, end - position + 1))
                            if not data:
                                raise EOFError("Truncated range")
                            assert os.pwrite(fd, data, position) == len(data)
                            position += len(data)
                    marker.write_text("complete\n")
                    return end - start + 1
                except Exception as exc:
                    print(json.dumps({"file": name, "offset": start, "attempt": attempt,
                                      "error": str(exc)}), flush=True)
                    if attempt == 2:
                        raise
                    time.sleep(1 + attempt)
        started = time.monotonic()
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for count in pool.map(download, range(0, size, CHUNK)):
                done += count
                print(json.dumps({"file": name, "bytes": done, "total": size,
                                  "seconds": round(time.monotonic() - started, 1)}), flush=True)
        os.close(fd)
        digest = hashlib.sha256()
        with part.open("rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024**2), b""):
                digest.update(chunk)
        assert digest.hexdigest() == item["lfs"]["sha256"], (name, digest.hexdigest())
        part.replace(dest)
        # Only our cancelled transfer's temporary file, after official verification.
        (MODEL / (name + ".partial")).unlink(missing_ok=True)
        print(json.dumps({"verified": name, "sha256": digest.hexdigest()}), flush=True)
    (STATE / "WEIGHTS_COMPLETE.json").write_text(json.dumps({
        "revision": "e28526f7bb80e2a9c8af03b831a9af3812f18fba", "manifest": manifest,
        "transport": "ModelScope Qwen mirror; accepted only by pinned official HF hashes"}, indent=2))


if __name__ == "__main__":
    main()
