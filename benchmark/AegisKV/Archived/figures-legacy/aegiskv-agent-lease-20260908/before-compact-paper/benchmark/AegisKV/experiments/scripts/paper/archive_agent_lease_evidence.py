"""Keep byte-exact durable evidence while using scratch space as a rebuildable cache."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

from paper_paths import ROOT
from three_system_data import sha

ART = ROOT / "output/agent-lease-20260908"
ARCHIVE = ART / "evidence.tar.zst"
MANIFEST = ART / "EVIDENCE_ARCHIVE.json"


def members():
    files = []
    for campaign, count in [("campaign-v3",47),("contention-campaign",4)]:
        croot=ART/campaign; protocol=json.loads((croot/"PROTOCOL.json").read_text())
        jobs=[(c,s) for c,p in protocol["cases"].items() for s in p.get("systems",["mooncake","dram","aegis"])]
        assert len(jobs)==count
        for case, system in jobs:
            path=croot/f"runs/{case}/{system}.json.gz"
            m=json.loads(path.with_name(system+".manifest.json").read_text())
            assert m["status"]=="PASS" and sha(path)==m["raw_sha256"]
            files.append(path)
    files += sorted((ART/"data").rglob("*"))
    files = sorted(p for p in files if p.is_file())
    return {str(p.relative_to(ART)):dict(sha256=sha(p),bytes=p.stat().st_size) for p in files}


def stream_check(archive, expected, destination=None):
    proc=subprocess.Popen(["zstd","-q","-d","--long=30","--stdout",str(archive)],stdout=subprocess.PIPE)
    checked=set()
    try:
        with tarfile.open(fileobj=proc.stdout,mode="r|") as tf:
            for item in tf:
                assert item.isfile() and item.name in expected and item.name not in checked,item.name
                rel=Path(item.name); assert not rel.is_absolute() and ".." not in rel.parts
                digest=hashlib.sha256(); count=0
                handle=tf.extractfile(item)
                out=None
                if destination is not None:
                    target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True);out=target.open("wb")
                try:
                    for chunk in iter(lambda:handle.read(8*1024**2),b""):
                        digest.update(chunk);count+=len(chunk)
                        if out is not None:out.write(chunk)
                finally:
                    if out is not None:out.close()
                assert digest.hexdigest()==expected[item.name]["sha256"] and count==expected[item.name]["bytes"],item.name
                checked.add(item.name)
        # Drain trailing tar padding before waiting on the decompressor.
        for _ in iter(lambda:proc.stdout.read(1024**2),b""):pass
        assert proc.wait()==0 and checked==expected.keys()
    finally:
        proc.stdout.close()
        if proc.poll() is None:proc.terminate();proc.wait()
    return len(checked)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create",action="store_true")
    parser.add_argument("--restore",action="store_true")
    # This cluster points TMPDIR into the quota-limited home filesystem.
    # Use the explicit local scratch mount for this rebuildable cache.
    parser.add_argument("--cache",type=Path,default=Path("/tmp")/f"aegiskv-{os.getuid()}-agent-lease-20260908")
    args=parser.parse_args(); assert not (args.create and args.restore)
    if args.create:
        expected=members()
        if MANIFEST.exists():
            previous=json.loads(MANIFEST.read_text())
            assert previous["members"]==expected,"evidence changed; archive a new revision"
            assert sha(ARCHIVE)==previous["archive_sha256"]
            print("Existing byte-exact evidence archive verified by hash");return
        scratch=args.cache.resolve();scratch.mkdir(parents=True,exist_ok=True);scratch.chmod(0o700)
        filelist=scratch/"archive-members.txt";filelist.write_text("\n".join(expected)+"\n")
        packed=scratch/"evidence.tar.zst.building"
        tar=subprocess.Popen(["tar","-chf","-","-C",str(ART),"-T",str(filelist)],stdout=subprocess.PIPE)
        with (ART/"archive-build.log").open("w") as log:
            comp=subprocess.Popen(["zstd","-q","-T4","-12","--long=30","-f","-o",str(packed)],stdin=tar.stdout,stderr=log)
            tar.stdout.close();assert comp.wait()==0 and tar.wait()==0
        checked=stream_check(packed,expected)
        digest=sha(packed)
        assert not ARCHIVE.exists();shutil.move(str(packed),str(ARCHIVE))
        assert sha(ARCHIVE)==digest
        MANIFEST.write_text(json.dumps(dict(schema="aegiskv.byte_exact_evidence_archive.v1",status="PASS",
            archive_sha256=digest,archive_bytes=ARCHIVE.stat().st_size,members=expected,verified_members=checked,
            raw_gzip_files=sum(n.endswith(".json.gz") for n in expected),
            scope="Original compressed raw bytes and exact derived inputs; source snapshots/configuration/manifests remain in the repository. Scratch copies are reconstructible, not the only evidence.",
            restore_command=".venv/bin/python benchmark/AegisKV/experiments/scripts/paper/archive_agent_lease_evidence.py --restore"),indent=2)+"\n")
        print(json.dumps(dict(status="PASS",members=checked,archive_gib=ARCHIVE.stat().st_size/1024**3)))
        return
    manifest=json.loads(MANIFEST.read_text());assert sha(ARCHIVE)==manifest["archive_sha256"]
    target=args.cache.resolve()/"restored" if args.restore else None
    if target is not None:target.mkdir(parents=True,exist_ok=True)
    checked=stream_check(ARCHIVE,manifest["members"],target)
    if args.restore:
        data=ART/"data"
        if data.is_symlink():data.unlink();data.symlink_to(target/"data",target_is_directory=True)
        elif not data.exists():data.symlink_to(target/"data",target_is_directory=True)
        else:
            for name,item in manifest["members"].items():
                if name.startswith("data/"):assert sha(ART/name)==item["sha256"],name
        for name,item in manifest["members"].items():
            if name.startswith("data/"):continue
            path=ART/name
            if path.is_symlink():path.unlink()
            elif path.exists():
                assert sha(path)==item["sha256"];continue
            path.parent.mkdir(parents=True,exist_ok=True);path.symlink_to(target/name)
    print(json.dumps(dict(status="RESTORED" if args.restore else "VERIFIED",members=checked)))


if __name__=="__main__":main()
