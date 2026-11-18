"""Transfer already downloaded official weights to BLSC; never allocates a GPU."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
STAGE = Path("/tmp/aegiskv-qwen25-stage")
MODEL = "/home/bingxing2/home/scx8q31/models/Qwen2.5-7B-Instruct-1M"
REVISION = "e28526f7bb80e2a9c8af03b831a9af3812f18fba"
SSH = ["ssh", "-F", "/home/comp/zhanzhao/.ssh/config", "-o", "BatchMode=yes",
       "-o", "ConnectTimeout=12", "-o", "ConnectionAttempts=1", "-o",
       "ProxyCommand=ssh -F /home/comp/zhanzhao/.ssh/config -o BatchMode=yes -o ConnectTimeout=12 -W %h:%p jump",
       "BLSC-A100"]


def transfer(item):
    name = item["rfilename"]
    size = item["size"]
    digest = item["lfs"]["sha256"]
    source = STAGE / name
    assert source.stat().st_size == size
    code = f"""
import hashlib,json,pathlib,sys,time
root=pathlib.Path({MODEL!r});root.mkdir(parents=True,exist_ok=True)
dest=root/{name!r};part=root/({name!r}+'.partial')
h=hashlib.sha256();size=0;start=time.monotonic()
with part.open('wb') as f:
 while True:
  data=sys.stdin.buffer.read(4*1024**2)
  if not data:break
  f.write(data);h.update(data);size+=len(data)
  if size%(256*1024**2)==0:print(json.dumps({{'file':{name!r},'received':size,'seconds':round(time.monotonic()-start,1)}}),flush=True)
assert size=={size!r} and h.hexdigest()=={digest!r},(size,h.hexdigest())
part.replace(dest)
print(json.dumps({{'verified':{name!r},'sha256':h.hexdigest(),'bytes':size}}),flush=True)
"""
    log_path = ROOT / (name + ".transfer.log")
    with source.open("rb") as src, log_path.open("w") as log:
        p = subprocess.run(SSH + ["python3 -c " + shlex.quote(code)], stdin=src,
                           stdout=log, stderr=subprocess.STDOUT)
    if p.returncode:
        raise RuntimeError(f"Transfer failed: {name}; see {log_path}")
    print(json.dumps({"verified": name, "sha256": digest}), flush=True)


def main():
    manifest = json.loads((ROOT.parent / "model-weight-manifest.json").read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(transfer, manifest))
    transfer_metadata()


def transfer_metadata():
    manifest = json.loads((ROOT.parent / "model-weight-manifest.json").read_text())
    metadata = {}
    for name in ["config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json",
                 "merges.txt", "generation_config.json", "model.safetensors.index.json"]:
        url = f"https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-1M/resolve/{REVISION}/{name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        code = f"import pathlib,sys;pathlib.Path({MODEL!r},{name!r}).write_bytes(sys.stdin.buffer.read())"
        subprocess.run(SSH + ["python3 -c " + shlex.quote(code)], input=data, check=True)
        metadata[name] = hashlib.sha256(data).hexdigest()
    record = {"model": "Qwen/Qwen2.5-7B-Instruct-1M", "revision": REVISION,
              "verified_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "shards": manifest, "metadata_sha256": metadata}
    code = f"import pathlib,sys;pathlib.Path({MODEL!r},'WEIGHTS_VERIFIED.json').write_bytes(sys.stdin.buffer.read())"
    subprocess.run(SSH + ["python3 -c " + shlex.quote(code)],
                   input=json.dumps(record, indent=2).encode(), check=True)
    (ROOT / "weights-verified.json").write_text(json.dumps(record, indent=2))
    print("ALL_WEIGHTS_AND_METADATA_TRANSFERRED", flush=True)


if __name__ == "__main__":
    import sys
    if "--metadata-only" in sys.argv:
        transfer_metadata()
    else:
        main()
