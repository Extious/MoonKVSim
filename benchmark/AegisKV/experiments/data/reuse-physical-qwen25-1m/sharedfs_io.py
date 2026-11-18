"""Aligned, direct file I/O for a serialized shared-filesystem KV baseline.

No Torch imports: the same byte-buffer path is checked on CPU before a GPU
allocation. O_DIRECT and file-specific cache eviction address the Linux client
page cache; remote filesystem/service caches remain uncontrolled.
"""
import argparse
import ctypes
import hashlib
import json
import mmap
import os
from pathlib import Path
import subprocess
import time
import uuid

ALIGNMENT = 65536
IO_CHUNK = 16 * 1024**2


def aligned_size(n):
    return ((n + ALIGNMENT - 1) // ALIGNMENT) * ALIGNMENT


def residency(path):
    """Count resident Linux file pages without faulting in file contents."""
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    mapping = None
    try:
        size = os.fstat(fd).st_size
        mapping = mmap.mmap(fd, size, flags=mmap.MAP_PRIVATE,
                            prot=mmap.PROT_READ | mmap.PROT_WRITE)
        address = ctypes.addressof(ctypes.c_char.from_buffer(mapping))
        n = (size + mmap.PAGESIZE - 1) // mmap.PAGESIZE
        vec = (ctypes.c_ubyte * n)()
        libc = ctypes.CDLL(None, use_errno=True)
        code = libc.mincore(ctypes.c_void_p(address), ctypes.c_size_t(size), vec)
        if code:
            raise OSError(ctypes.get_errno(), "mincore failed")
        return dict(pages=n, resident_pages=sum(v & 1 for v in vec),
                    page_bytes=mmap.PAGESIZE)
    finally:
        if mapping is not None:
            mapping.close()
        os.close(fd)


def evict_own_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)
    result = residency(path)
    if result["resident_pages"]:
        raise RuntimeError(f"Client file pages still resident: {result}")
    return result


def digest_views(views):
    h = hashlib.sha256()
    for v in views:
        h.update(v)
    return h.hexdigest()


def direct_io(path, views, *, write=False):
    """Read/write each aligned view in order; views include explicit padding."""
    flags = os.O_DIRECT | os.O_CLOEXEC
    flags |= os.O_WRONLY | os.O_CREAT | os.O_EXCL if write else os.O_RDONLY
    start = time.perf_counter()
    fd = os.open(path, flags, 0o600)
    expected = sum(len(v) for v in views)
    offset = 0
    try:
        if not write:
            assert os.fstat(fd).st_size == expected
        for view in views:
            assert len(view) % ALIGNMENT == 0
            assert ctypes.addressof(ctypes.c_char.from_buffer(view)) % ALIGNMENT == 0
            for first in range(0, len(view), IO_CHUNK):
                chunk = view[first:first + IO_CHUNK]
                count = (os.pwritev if write else os.preadv)(fd, [chunk], offset)
                if count != len(chunk):
                    raise IOError(f"Short direct I/O: {count} != {len(chunk)}")
                offset += count
        if write:
            os.fsync(fd)
    finally:
        os.close(fd)
    return dict(bytes=offset, elapsed_ms=(time.perf_counter() - start) * 1000,
                direct_io=True, io_chunk_bytes=IO_CHUNK)


def probe(directory, size=64 * 1024**2):
    """Small random-payload roundtrip; only removes its own unique test file."""
    directory = Path(directory)
    assert directory.is_dir()
    path = directory / (".aegis-directio-probe-" + uuid.uuid4().hex)
    allocation = mmap.mmap(-1, size + ALIGNMENT)
    address = ctypes.addressof(ctypes.c_char.from_buffer(allocation))
    shift = (-address) % ALIGNMENT
    view = memoryview(allocation)[shift:shift + size]
    try:
        for start in range(0, size, IO_CHUNK):
            view[start:start + IO_CHUNK] = os.urandom(min(IO_CHUNK, size - start))
        original = digest_views([view])
        write = direct_io(path, [view], write=True)
        before = evict_own_file(path)
        for start in range(0, size, IO_CHUNK):
            view[start:start + IO_CHUNK] = bytes(min(IO_CHUNK, size - start))
        read = direct_io(path, [view])
        after = residency(path)
        same = digest_views([view]) == original
        assert same and not after["resident_pages"], (same, after)
        return dict(correctness=same, bytes=size, write=write, read=read,
                    client_cache_before=before, client_cache_after=after,
                    server_cache="uncontrolled; not a cold-device measurement",
                    mount=subprocess.check_output(["findmnt", "-J", "-T", str(directory),
                                                   "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"], text=True))
    finally:
        if path.exists():
            path.unlink()
        view.release()
        allocation.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-directory", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    report = probe(args.probe_directory)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
